"""Importiert Versteigerungsedikte direkt von edikte.justiz.gv.at.

Eingabe ist beliebiger Text mit Links auf Edikte (z. B. eine kopierte
Ergebnisliste). Jede Detailseite wird abgerufen, ausgelesen und anhand der
Edikt-ID angelegt bzw. aktualisiert.

Aufruf von der Kommandozeile:
    python -m app.importer liste.txt      (oder Text über stdin)
"""
import html as htmllib
import re
import sys
import time
import urllib.request
from datetime import datetime

from . import db
from .geocode import geocode_sicher
from .parser import parse_eur

HOST = "https://edikte.justiz.gv.at"
URL_RE = re.compile(r"https?://edikte\.justiz\.gv\.at/edikte/ex/exedi3\.nsf/(?:alldoc|0)/([0-9a-fA-F]{32})")
ROW_RE = re.compile(
    r'<span class="col-sm-3 text-right">(?:<strong>)?(.*?):?\s*(?:</strong>)?</span>\s*'
    r'<p class="col-sm-9">(.*?)</p>', re.S)
USER_AGENT = "Mozilla/5.0 (edikt-immo Import; manuell ausgelöst)"


def extract_ids(text):
    """Alle Edikt-IDs aus einem Text, Reihenfolge erhalten, ohne Duplikate."""
    return list(dict.fromkeys(m.lower() for m in URL_RE.findall(text)))


def edikt_url(edikt_id):
    return f"{HOST}/edikte/ex/exedi3.nsf/alldoc/{edikt_id}!OpenDocument"


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _text(fragment):
    fragment = re.sub(r"<br\s*/?>", "\n", fragment)
    return htmllib.unescape(re.sub(r"<[^>]+>", "", fragment)).replace("\xa0", " ").strip()


def _termin(value):
    m = re.search(r"(\d{1,2})\.(\d{1,2})\.(\d{4})(?:\D+(\d{1,2}):(\d{2}))?", value or "")
    if not m:
        return None
    d, mo, y, h, mi = m.groups()
    return f"{y}-{int(mo):02d}-{int(d):02d}T{int(h or 0):02d}:{mi or '00'}"


def _datum(value):
    m = re.search(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", value or "")
    return f"{m[3]}-{int(m[2]):02d}-{int(m[1]):02d}" if m else None


def bundesland_aus_plz(plz):
    """Näherung über die PLZ (Grenzfälle v. a. NÖ/Burgenland, Osttirol) – im Admin prüfbar."""
    if not plz or not plz[:2].isdigit():
        return None
    p2 = int(plz[:2])
    if plz[0] == "1":
        return "Wien"
    if plz[0] in "23":
        return "Niederösterreich"
    if plz[0] == "4":
        return "Oberösterreich"
    if plz[0] == "5":
        return "Salzburg"
    if plz[0] == "6":
        return "Vorarlberg" if p2 >= 67 else "Tirol"
    if plz[0] == "7":
        return "Burgenland"
    if plz[0] == "8":
        return "Steiermark"
    if plz[0] == "9":
        return "Tirol" if p2 == 99 else "Kärnten"
    return None


ARTEN_PREFIX = r"^(?:Versteigerung|Verschiebung|Entfall des Termins|Zuschlag \w+ Überbot|Meistbotsverteilung)\s*(?:-\s*)?"


def felder(page):
    """Alle 'Bezeichnung: Wert'-Zeilen einer Detailseite plus Titel (ohne Edikt-Art)."""
    rows = {}
    for label, value in ROW_RE.findall(page):
        rows.setdefault(_text(label), _text(value))
    titel = re.search(r'class="page-header[^"]*"><h1><small>(.*?)</small>', page, re.S)
    titel = re.sub(ARTEN_PREFIX, "", _text(titel.group(1)) if titel else "")
    return rows, titel


def parse_detail(page):
    rows, titel = felder(page)

    data = {
        "titel": titel or None,
        "gericht": re.sub(r"\s*\(\d+\)\s*$", "", rows.get("Dienststelle", "")) or None,
        "aktenzeichen": rows.get("Aktenzeichen"),
        "termin": _termin(rows.get("Versteigerungstermin") or rows.get("Neuer Versteigerungstermin")),
        "termin_ort": rows.get("Versteigerungsort") or rows.get("Neuer Ort"),
        "bekannt_gemacht": _datum(rows.get("Bekannt gemacht am")),
        "adresse": rows.get("Liegenschaftsadresse"),
        "objektart": rows.get("Kategorie(n)"),
        "flaeche": parse_eur(re.sub(r"m²|m\^2", "", rows.get("Objektgröße", ""))),
        "grundflaeche": parse_eur(re.sub(r"m²|m\^2", "", rows.get("Grundstücksgröße", ""))),
        "schaetzwert": parse_eur(rows.get("Schätzwert")),
        "geringstes_gebot": parse_eur(rows.get("Geringstes Gebot")),
        "vadium": parse_eur(rows.get("Vadium")),
    }

    m = re.match(r"(\d{4})\s+(.+)", rows.get("PLZ/Ort", ""))
    if m:
        data["plz"], data["ort"] = m.group(1), m.group(2).strip()
        data["bundesland"] = bundesland_aus_plz(data["plz"])

    # Nur objektbezogene Beschreibungen übernehmen – keine Parteien-/Kontaktangaben.
    teile = [rows[k] for k in rows if k.startswith("Beschreibung (")]
    zubehoer = rows.get("Beschreibung des mitzuversteigernden Zubehörs")
    if zubehoer and zubehoer.lower() not in ("kein zubehör", "keines", "-"):
        teile.append("Zubehör: " + zubehoer)
    data["beschreibung"] = "\n\n".join(teile) or None
    # Gutachten-PDFs werden bewusst nicht direkt verlinkt: ihre Dateinamen enthalten oft
    # Personennamen. Der Weg zum Gutachten führt über das verlinkte Original-Edikt.

    return {k: v for k, v in data.items() if v not in (None, "")}


def import_edikt(edikt_id, page=None):
    """Ein Versteigerungsedikt abrufen und anlegen/aktualisieren -> (status, info)."""
    url = edikt_url(edikt_id)
    try:
        data = parse_detail(page if page is not None else fetch(url))
    except Exception as exc:  # Netzwerk-/Parsefehler pro Edikt melden, Rest weiter importieren
        return "Fehler", str(exc)
    if not data.get("aktenzeichen"):
        return "Fehler", "Kein Aktenzeichen gefunden – Seite anders aufgebaut?"
    data.update(edikt_url=url, edikt_id=edikt_id)
    info = f"{data['aktenzeichen']} · {data.get('plz', '')} {data.get('ort', '')} · {data.get('titel', '')}"
    existing = db.get_by_edikt_id(edikt_id)
    adresse_neu = not existing or existing["lat"] is None or any(
        existing[k] != data.get(k) for k in ("adresse", "plz", "ort"))
    if adresse_neu:
        data.update(geocode_sicher(data))
        if "lat" not in data:
            info += " · ohne Kartenposition"
    if existing:
        db.update(existing["id"], data)  # 'aktiv' bleibt, wie im Admin gesetzt
        return "aktualisiert", info
    db.insert({**data, "aktiv": 1})
    return "neu", info


def import_ids(ids, pause=1.0):
    """Liefert Liste von (edikt_id, status, info)."""
    results = []
    for i, edikt_id in enumerate(ids):
        if i:
            time.sleep(pause)  # Server der Justiz schonen
        results.append((edikt_id, *import_edikt(edikt_id)))
    return results


if __name__ == "__main__":
    db.init_db()
    text = open(sys.argv[1], encoding="utf-8").read() if len(sys.argv) > 1 else sys.stdin.read()
    ids = extract_ids(text)
    print(f"{len(ids)} Edikt-Links gefunden – Import startet ({datetime.now():%H:%M:%S})")
    for edikt_id, status, info in import_ids(ids):
        print(f"[{status:12}] {info}")
