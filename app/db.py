import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

DB_PATH = Path(os.environ.get("EDIKT_DB", Path(__file__).resolve().parent.parent / "data" / "edikte.db"))

BUNDESLAENDER = [
    "Burgenland", "Kärnten", "Niederösterreich", "Oberösterreich", "Salzburg",
    "Steiermark", "Tirol", "Vorarlberg", "Wien",
]

# Vorschläge für das Admin-Formular (Kategorien wie in der Ediktsdatei).
OBJEKTARTEN = [
    "Eigentumswohnung", "Wohnungseigentumsobjekt", "Einfamilienhaus", "Zweifamilienhaus",
    "Mehrfamilienhaus", "Reihenhaus", "Hausanteil", "gemischt genutztes Haus", "Baugrund",
    "land- und forstwirtschaftlich genutzte Liegenschaft", "Gewerbliche Liegenschaft",
    "Superädifikat", "Kfz-Abstellplatz", "Sonstiges",
]

# Felder, die über Formular/Import geschrieben werden.
FIELDS = [
    "aktenzeichen", "gericht", "titel", "bundesland", "plz", "ort", "adresse", "objektart",
    "flaeche", "grundflaeche", "schaetzwert", "geringstes_gebot", "vadium", "termin",
    "termin_ort", "bekannt_gemacht", "beschreibung", "edikt_url", "edikt_id", "lat", "lon",
    "geo_genau", "aktiv",
]
NUMERIC_FIELDS = ("flaeche", "grundflaeche", "schaetzwert", "geringstes_gebot", "vadium")
COORD_FIELDS = ("lat", "lon")

# Spalten, die nach der ersten Version dazugekommen sind (werden bei Bedarf ergänzt).
MIGRATIONS = {
    "titel": "TEXT", "grundflaeche": "REAL", "vadium": "REAL", "bekannt_gemacht": "TEXT",
    "edikt_id": "TEXT", "lat": "REAL", "lon": "REAL", "geo_genau": "INTEGER",
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS objekte (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    aktenzeichen     TEXT NOT NULL,
    gericht          TEXT,
    bundesland       TEXT,
    plz              TEXT,
    ort              TEXT,
    adresse          TEXT,
    objektart        TEXT,
    flaeche          REAL,
    schaetzwert      REAL,
    geringstes_gebot REAL,
    termin           TEXT,  -- ISO 'YYYY-MM-DDTHH:MM'
    termin_ort       TEXT,
    beschreibung     TEXT,
    edikt_url        TEXT,
    aktiv            INTEGER NOT NULL DEFAULT 1,
    created_at       TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at       TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_objekte_termin ON objekte(termin);
CREATE INDEX IF NOT EXISTS idx_objekte_bundesland ON objekte(bundesland);
-- Bereits verarbeitete Edikte (alle Arten), damit sie beim Abgleich nicht erneut abgerufen werden.
CREATE TABLE IF NOT EXISTS edikte_gesehen (
    edikt_id    TEXT PRIMARY KEY,
    art         TEXT,
    ergebnis    TEXT,
    gesehen_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


@contextmanager
def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with connect() as conn:
        conn.executescript(SCHEMA)
        existing = {r["name"] for r in conn.execute("PRAGMA table_info(objekte)")}
        for col, typ in MIGRATIONS.items():
            if col not in existing:
                conn.execute(f"ALTER TABLE objekte ADD COLUMN {col} {typ}")
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_objekte_edikt_id ON objekte(edikt_id)")


def objektarten():
    """Objektarten, die bei aktiven Objekten tatsächlich vorkommen (für den Filter)."""
    with connect() as conn:
        return [r[0] for r in conn.execute(
            "SELECT DISTINCT objektart FROM objekte WHERE aktiv = 1 AND objektart IS NOT NULL"
            " ORDER BY objektart COLLATE NOCASE")]


def get_by_edikt_id(edikt_id):
    with connect() as conn:
        return conn.execute("SELECT * FROM objekte WHERE edikt_id = ?", (edikt_id,)).fetchone()


SORTS = {
    "termin": "termin IS NULL, termin ASC",
    "schaetzwert_auf": "schaetzwert IS NULL, schaetzwert ASC",
    "schaetzwert_ab": "schaetzwert IS NULL, schaetzwert DESC",
    "neu": "created_at DESC",
}


def search(q=None, bundesland=None, objektarten=None, preis_min=None, preis_max=None,
           gebot_min=None, gebot_max=None, flaeche_min=None, nur_kommende=True, sort="termin",
           now_iso=None):
    where, params = ["aktiv = 1"], []
    if q:
        where.append("(aktenzeichen LIKE ? OR ort LIKE ? OR plz LIKE ? OR adresse LIKE ?"
                     " OR beschreibung LIKE ? OR gericht LIKE ? OR titel LIKE ?)")
        params += [f"%{q}%"] * 7
    if bundesland:
        where.append("bundesland = ?")
        params.append(bundesland)
    if objektarten:
        where.append(f"objektart IN ({', '.join('?' * len(objektarten))})")
        params += objektarten
    for spalte, op, wert in (("schaetzwert", ">=", preis_min), ("schaetzwert", "<=", preis_max),
                             ("geringstes_gebot", ">=", gebot_min), ("geringstes_gebot", "<=", gebot_max)):
        if wert is not None:
            where.append(f"{spalte} {op} ?")
            params.append(wert)
    if flaeche_min is not None:
        where.append("flaeche >= ?")
        params.append(flaeche_min)
    if nur_kommende and now_iso:
        where.append("(termin IS NULL OR termin >= ?)")
        params.append(now_iso)
    order = SORTS.get(sort, SORTS["termin"])
    sql = f"SELECT * FROM objekte WHERE {' AND '.join(where)} ORDER BY {order}"
    with connect() as conn:
        return conn.execute(sql, params).fetchall()


def ohne_koordinaten():
    with connect() as conn:
        return conn.execute("SELECT * FROM objekte WHERE lat IS NULL OR lon IS NULL").fetchall()


def passende_objekte(aktenzeichen, adresse, plz):
    """Objekte zum selben Verfahren an derselben Adresse (für Verschiebung/Entfall)."""
    with connect() as conn:
        return conn.execute(
            "SELECT * FROM objekte WHERE aktenzeichen = ? AND IFNULL(adresse, '') = IFNULL(?, '')"
            " AND IFNULL(plz, '') = IFNULL(?, '')", (aktenzeichen, adresse, plz)).fetchall()


def gesehene_ids():
    with connect() as conn:
        ids = {r[0] for r in conn.execute("SELECT edikt_id FROM edikte_gesehen")}
        ids |= {r[0] for r in conn.execute("SELECT edikt_id FROM objekte WHERE edikt_id IS NOT NULL")}
        return ids


def als_gesehen_markieren(edikt_id, art, ergebnis):
    with connect() as conn:
        conn.execute("INSERT OR REPLACE INTO edikte_gesehen (edikt_id, art, ergebnis) VALUES (?, ?, ?)",
                     (edikt_id, art, ergebnis))


def get(objekt_id):
    with connect() as conn:
        return conn.execute("SELECT * FROM objekte WHERE id = ?", (objekt_id,)).fetchone()


def all_objekte():
    with connect() as conn:
        return conn.execute("SELECT * FROM objekte ORDER BY termin IS NULL, termin DESC").fetchall()


def insert(data):
    cols = [f for f in FIELDS if f in data]
    with connect() as conn:
        cur = conn.execute(
            f"INSERT INTO objekte ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
            [data[c] for c in cols],
        )
        return cur.lastrowid


def update(objekt_id, data):
    cols = [f for f in FIELDS if f in data]
    with connect() as conn:
        conn.execute(
            f"UPDATE objekte SET {', '.join(f'{c} = ?' for c in cols)}, updated_at = datetime('now')"
            " WHERE id = ?",
            [data[c] for c in cols] + [objekt_id],
        )


def delete(objekt_id):
    with connect() as conn:
        conn.execute("DELETE FROM objekte WHERE id = ?", (objekt_id,))
