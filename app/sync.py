"""Automatischer Abgleich mit der Ediktsdatei.

Durchsucht die Versteigerungen je Bundesland und verarbeitet nur Edikte, die
noch nicht bekannt sind:

- Versteigerung        -> Objekt anlegen
- Verschiebung         -> neuen Termin beim passenden Objekt eintragen
- Entfall des Termins  -> passendes Objekt ausblenden
- Zuschlag, Meistbotsverteilung -> nur als gesehen merken (Termin ist vorbei)

Aufruf:  python -m app.sync            (alle Bundesländer)
         python -m app.sync Wien Tirol (nur diese)
"""
import os
import re
import sys
import threading
import time
import urllib.parse
from datetime import datetime

from . import db, mailer
from .importer import HOST, _termin, _text, edikt_url, felder, fetch, import_edikt

SUCH_URL = (HOST + "/edikte/ex/exedi3.nsf/suchedi?SearchView&subf=eex&SearchOrder=4"
            "&SearchMax=4999&retfields=&ftquery=&query=")
# Codes der Ediktsdatei für das Feld [BL]
BL_CODES = {
    "Wien": 0, "Niederösterreich": 1, "Burgenland": 2, "Oberösterreich": 3, "Salzburg": 4,
    "Steiermark": 5, "Kärnten": 6, "Tirol": 7, "Vorarlberg": 8,
}
LISTEN_ZEILE = re.compile(
    r'href="alldoc/([0-9a-fA-F]{32})!OpenDocument"[^>]*>([^<]+)</a></td><td>(.*?)</td><td>(.*?)</td>', re.S)
PAUSE = float(os.environ.get("SYNC_PAUSE", "1.0"))  # Sekunden zwischen Abrufen bei der Justiz


def liste(bundesland):
    """Ergebnisliste eines Bundeslands -> [(edikt_id, art, text)]."""
    query = urllib.parse.quote(f"([BL]=({BL_CODES[bundesland]}))", safe="()")
    page = fetch(SUCH_URL + query)
    eintraege = []
    for edikt_id, art_text, adresse, objekt in LISTEN_ZEILE.findall(page):
        art = re.sub(r"\s*\(.*$", "", _text(art_text))
        eintraege.append((edikt_id.lower(), art, f"{_text(adresse)} · {_text(objekt)}"))
    return eintraege


def _passend(rows, titel):
    m = re.match(r"(\d{4})", rows.get("PLZ/Ort", ""))
    kandidaten = db.passende_objekte(rows.get("Aktenzeichen"), rows.get("Liegenschaftsadresse")
                                     or rows.get("Adresse"), m.group(1) if m else None)
    if len(kandidaten) > 1 and titel:
        genauer = [o for o in kandidaten if o["titel"] == titel]
        kandidaten = genauer or kandidaten
    return kandidaten


def verschiebung(edikt_id):
    page = fetch(edikt_url(edikt_id))
    rows, titel = felder(page)
    # Nur Verschiebungen der Versteigerung selbst; "Neuer Tagsatzungstermin" betrifft
    # die Meistbotsverteilung nach einer bereits erfolgten Versteigerung.
    termin = _termin(rows.get("Neuer Versteigerungstermin"))
    if not termin:
        return "ignoriert", "betrifft nicht die Versteigerung"
    objekte = _passend(rows, titel)
    if not objekte:
        # Ursprüngliches Edikt nicht bekannt -> Objekt direkt aus der Verschiebung anlegen
        return import_edikt(edikt_id, page)
    for o in objekte:
        neu = {"termin": termin}
        if rows.get("Neuer Ort"):
            neu["termin_ort"] = rows["Neuer Ort"]
        db.update(o["id"], neu)
    return "verschoben", f"{rows.get('Aktenzeichen')} → {termin.replace('T', ' ')}"


def entfall(edikt_id):
    rows, titel = felder(fetch(edikt_url(edikt_id)))
    objekte = _passend(rows, titel)
    if not objekte:
        return "ignoriert", f"{rows.get('Aktenzeichen', '?')}: kein passendes Objekt"
    for o in objekte:
        db.update(o["id"], {"aktiv": 0})
    return "ausgeblendet", f"{rows.get('Aktenzeichen')} · Termin entfallen"


def abgleich(bundeslaender=None, log=print):
    """Führt den Abgleich durch; liefert Zähler je Ergebnis."""
    db.init_db()
    bekannt = db.gesehene_ids()
    zaehler = {}
    for bl in bundeslaender or BL_CODES:
        try:
            eintraege = liste(bl)
        except Exception as exc:
            log(f"{bl}: Liste nicht abrufbar ({exc})")
            zaehler["Fehler"] = zaehler.get("Fehler", 0) + 1
            continue
        neu = [e for e in eintraege if e[0] not in bekannt]
        log(f"{bl}: {len(eintraege)} Edikte, davon {len(neu)} neu")
        time.sleep(PAUSE)
        for edikt_id, art, text in neu:
            handler = {"Versteigerung": import_edikt, "Verschiebung": verschiebung,
                       "Entfall des Termins": entfall}.get(art)
            try:
                status, info = handler(edikt_id) if handler else ("ignoriert", art)
            except Exception as exc:
                status, info = "Fehler", f"{text}: {exc}"
            if status != "Fehler":  # Fehler beim nächsten Lauf erneut versuchen
                db.als_gesehen_markieren(edikt_id, art, status)
                bekannt.add(edikt_id)
            zaehler[status] = zaehler.get(status, 0) + 1
            if status != "ignoriert":
                log(f"  [{status}] {info}")
            if handler:  # nur nach echten Abrufen pausieren
                time.sleep(PAUSE)
    return zaehler


# ---------- Hintergrund-Betrieb für die Web-App ----------

class Status:
    def __init__(self):
        self.lock = threading.Lock()
        self.laeuft = False
        self.gestartet = None
        self.beendet = None
        self.log = []
        self.ergebnis = None

    def schreiben(self, zeile):
        self.log.append(f"{datetime.now():%H:%M:%S} {zeile}")
        del self.log[:-300]  # nur die letzten Zeilen behalten


status = Status()


def starte_im_hintergrund(bundeslaender=None):
    """Startet einen Abgleich in einem Thread. False, wenn schon einer läuft."""
    with status.lock:
        if status.laeuft:
            return False
        status.laeuft, status.gestartet, status.beendet = True, datetime.now(), None
        status.log, status.ergebnis = [], None

    def lauf():
        try:
            status.ergebnis = abgleich(bundeslaender, log=status.schreiben)
            status.schreiben("Fertig: " + ", ".join(f"{k} {v}" for k, v in status.ergebnis.items()))
            mailer.neue_melden(log=status.schreiben)
        except Exception as exc:
            status.schreiben(f"Abgebrochen: {exc}")
        finally:
            status.laeuft, status.beendet = False, datetime.now()

    threading.Thread(target=lauf, daemon=True, name="edikt-sync").start()
    return True


def starte_zeitplan(stunden):
    """Abgleich alle `stunden` Stunden (erster Lauf kurz nach dem Start)."""
    def schleife():
        time.sleep(60)
        while True:
            starte_im_hintergrund(konfigurierte_bundeslaender())
            time.sleep(stunden * 3600)

    threading.Thread(target=schleife, daemon=True, name="edikt-sync-zeitplan").start()


def konfigurierte_bundeslaender():
    wert = os.environ.get("SYNC_BUNDESLAENDER", "").strip()
    if not wert:
        return None
    return [b.strip() for b in wert.split(",") if b.strip() in BL_CODES]


if __name__ == "__main__":
    auswahl = [a for a in sys.argv[1:] if a in BL_CODES] or konfigurierte_bundeslaender()
    print(f"Abgleich startet {datetime.now():%d.%m.%Y %H:%M} – {', '.join(auswahl or BL_CODES)}")
    ergebnis = abgleich(auswahl)
    print("Fertig:", ergebnis)
    mailer.neue_melden()
