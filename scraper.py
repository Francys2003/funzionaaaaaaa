#!/usr/bin/env python3
"""
Barbero Alert — Scraper automatico
Scarica gli eventi da vassallidibarbero.it e aggiorna events.json
Usato da GitHub Actions ogni giorno alle 8:00
"""

import json
import re
import hashlib
import urllib.request
from datetime import datetime, date
from html.parser import HTMLParser

# ── SITI DA MONITORARE ────────────────────────────────────────────────────
SOURCES = [
    "https://www.vassallidibarbero.it/category/eventi-barbero/",
    "https://www.vassallidibarbero.it/category/eventi-barbero/page/2/",
]

# ── PARSER HTML ───────────────────────────────────────────────────────────
class EventParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.events = []
        self._in_h3 = False
        self._current_url = ""
        self._current_title = ""
        self._capture = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "h3":
            self._in_h3 = True
        if tag == "a" and self._in_h3:
            self._current_url = attrs.get("href", "")
            self._capture = True

    def handle_endtag(self, tag):
        if tag == "h3":
            self._in_h3 = False
            self._capture = False
            if self._current_title and self._current_url:
                self.events.append({
                    "title": self._current_title.strip(),
                    "url": self._current_url.strip()
                })
            self._current_title = ""
            self._current_url = ""

    def handle_data(self, data):
        if self._capture:
            self._current_title += data


# ── ESTRAI DATA DALL'URL ──────────────────────────────────────────────────
def extract_date_from_url(url):
    """Estrae YYYY/MM/DD dall'URL WordPress tipo /2026/03/02/..."""
    m = re.search(r'/(\d{4})/(\d{2})(?:/(\d{2}))?/', url)
    if m:
        y, mo, d = m.group(1), m.group(2), m.group(3) or "01"
        try:
            dt = date(int(y), int(mo), int(d))
            if dt >= date.today():
                return dt.isoformat()
        except ValueError:
            pass
    return None


# ── INDOVINA LOCATION E TYPE DAL TITOLO ──────────────────────────────────
def guess_meta(title, url):
    title_low = title.lower()
    url_low   = url.lower()

    # Tipo evento
    event_type = "Conferenza"
    if any(w in title_low for w in ["podcast", "chiedilo"]):
        event_type = "Podcast"
    elif any(w in title_low for w in ["festival", "festa della storia"]):
        event_type = "Festival"
    elif any(w in title_low for w in ["lezione", "università", "accademico"]):
        event_type = "Lezione pubblica"
    elif any(w in title_low for w in ["bookcity", "salone", "fiera", "libri"]):
        event_type = "Fiera/Salone"
    elif any(w in title_low for w in ["teatro", "spettacolo"]):
        event_type = "Teatro"
    elif any(w in title_low for w in ["tour", "sudafrica", "estero"]):
        event_type = "Tour internazionale"

    # Location
    cities = {
        "roma": "Roma", "milano": "Milano", "torino": "Torino",
        "bologna": "Bologna", "napoli": "Napoli", "firenze": "Firenze",
        "venezia": "Venezia", "genova": "Genova", "bari": "Bari",
        "urbino": "Urbino", "cuneo": "Cuneo", "palermo": "Palermo",
        "circo massimo": "Circo Massimo, Roma",
        "nuvola": "La Nuvola, Roma",
        "auditorium": "Auditorium Parco della Musica, Roma",
        "sudafrica": "Sudafrica",
        "castenedolo": "Castenedolo (BS)",
        "classico": "Torino",
    }
    location = "Italia"
    for key, val in cities.items():
        if key in title_low or key in url_low:
            location = val
            break

    return event_type, location


# ── GENERA ID UNIVOCO ─────────────────────────────────────────────────────
def make_id(url):
    return "b-" + hashlib.md5(url.encode()).hexdigest()[:10]


# ── FETCH URL ─────────────────────────────────────────────────────────────
def fetch(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (compatible; BarberoAlertBot/1.0)"
    })
    with urllib.request.urlopen(req, timeout=15) as r:
        return r.read().decode("utf-8", errors="replace")


# ── CARICA EVENTS.JSON ESISTENTE ─────────────────────────────────────────
def load_existing():
    try:
        with open("events.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


# ── MAIN ─────────────────────────────────────────────────────────────────
def main():
    existing = load_existing()
    existing_ids = {e["id"] for e in existing}
    existing_urls = {e["url"] for e in existing}

    new_events = []
    today_str = date.today().isoformat()

    print(f"[{datetime.now().strftime('%H:%M:%S')}] Avvio scraping...")

    for source_url in SOURCES:
        print(f"  → Scarico {source_url}")
        try:
            html = fetch(source_url)
            parser = EventParser()
            parser.feed(html)

            for raw in parser.events:
                url = raw["url"]
                title = raw["title"]

                if not url or url in existing_urls:
                    continue

                ev_date = extract_date_from_url(url)
                if not ev_date:
                    continue  # salta eventi senza data futura leggibile

                ev_type, location = guess_meta(title, url)
                ev_id = make_id(url)

                if ev_id in existing_ids:
                    continue

                event = {
                    "id": ev_id,
                    "title": title,
                    "date": ev_date,
                    "location": location,
                    "type": ev_type,
                    "url": url,
                    "source": "vassallidibarbero.it",
                    "isNew": True,
                    "addedOn": today_str
                }
                new_events.append(event)
                print(f"    ✅ NUOVO: {title} ({ev_date})")

        except Exception as e:
            print(f"    ⚠️  Errore su {source_url}: {e}")

    # Merge: nuovi + esistenti, solo eventi futuri
    all_events = new_events + existing
    all_events = [
        e for e in all_events
        if e.get("date", "0000") >= today_str
    ]

    # Rimuovi duplicati per id
    seen = set()
    deduped = []
    for e in all_events:
        if e["id"] not in seen:
            seen.add(e["id"])
            deduped.append(e)

    # Ordina per data
    deduped.sort(key=lambda e: e["date"])

    # Scrivi events.json
    with open("events.json", "w", encoding="utf-8") as f:
        json.dump(deduped, f, ensure_ascii=False, indent=2)

    print(f"\n✅ Salvati {len(deduped)} eventi totali ({len(new_events)} nuovi) in events.json")

    # Aggiorna barbero-alert.html iniettando i dati freschi
    update_html(deduped)


# ── AGGIORNA IL FILE HTML CON I NUOVI EVENTI ─────────────────────────────
def update_html(events):
    try:
        with open("barbero-alert.html", "r", encoding="utf-8") as f:
            html = f.read()

        json_str = json.dumps(events, ensure_ascii=False, indent=2)

        # Sostituisce il blocco SEED_EVENTS nell'HTML
        new_block = f"const SEED_EVENTS = {json_str};"
        html = re.sub(
            r"const SEED_EVENTS\s*=\s*\[[\s\S]*?\];",
            new_block,
            html,
            count=1
        )

        with open("barbero-alert.html", "w", encoding="utf-8") as f:
            f.write(html)

        print("✅ barbero-alert.html aggiornato con i nuovi eventi")
    except FileNotFoundError:
        print("⚠️  barbero-alert.html non trovato, solo events.json aggiornato")


if __name__ == "__main__":
    main()
