"""Liest Felder aus einem kopierten Versteigerungsedikt (Text aus edikte.justiz.gv.at).

Das Ergebnis ist nur ein Vorschlag zum Vorausfüllen des Formulars – vor dem
Speichern immer kontrollieren. Namen von Verpflichteten werden bewusst NICHT
übernommen (Datenschutz).
"""
import re

from .db import BUNDESLAENDER, OBJEKTARTEN


def parse_eur(value):
    """'EUR 250.000,00' / '€ 1.234,--' / '250000' -> 250000.0"""
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    s = re.sub(r"(?i)eur|€|\s", "", s).replace(",--", "").replace(",-", "")
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"\d{1,3}(\.\d{3})+", s):
        s = s.replace(".", "")
    try:
        return float(s)
    except ValueError:
        return None


def _find(pattern, text, flags=re.IGNORECASE):
    m = re.search(pattern, text, flags)
    return m.group(1).strip() if m else None


def _termin(text):
    m = re.search(
        r"Versteigerungstermin[^\d]{0,40}(\d{1,2})\.(\d{1,2})\.(\d{4})(?:[^\d]{1,15}(\d{1,2})[:.](\d{2}))?",
        text, re.IGNORECASE,
    )
    if not m:
        return None
    d, mo, y, h, mi = m.groups()
    return f"{y}-{int(mo):02d}-{int(d):02d}T{int(h or 0):02d}:{mi or '00'}"


def parse_edikt(text):
    text = text.replace("\xa0", " ")
    data = {}

    data["aktenzeichen"] = _find(r"\b(\d{1,3}\s+E\s+\d+/\d{2}\s*[a-z]?)\b", text)
    data["gericht"] = _find(r"((?:Bezirksgericht|BG)\s+[A-ZÄÖÜ][\wäöüß\-]+(?:[ ]+[A-ZÄÖÜ][\wäöüß\-]+){0,2})", text, 0)
    data["termin"] = _termin(text)
    data["schaetzwert"] = parse_eur(_find(r"Schätzwert\s*:?\s*((?:EUR|€)?\s*[\d.,]+(?:,--)?)", text))
    data["geringstes_gebot"] = parse_eur(_find(r"Geringstes\s+Gebot\s*:?\s*((?:EUR|€)?\s*[\d.,]+(?:,--)?)", text))

    flaeche = _find(r"(?:Nutzfläche|Wohnfläche|Fläche|Grundfläche)\s*:?\s*(?:ca\.?\s*)?([\d.,]+)\s*m", text)
    if flaeche:
        data["flaeche"] = parse_eur(flaeche)

    m = re.search(r"\b(\d{4})\s+([A-ZÄÖÜ][\wäöüß.\- ]{1,40}?)(?:,|\n|$)", text)
    if m:
        data["plz"], data["ort"] = m.group(1), m.group(2).strip()
        line_start = text.rfind("\n", 0, m.start()) + 1
        adresse = text[line_start:m.start()].strip(" ,:")
        adresse = re.sub(r"(?i)^(objektadresse|adresse|liegenschaftsadresse)\s*:?\s*", "", adresse)
        if adresse:
            data["adresse"] = adresse

    lower = text.lower()
    data["bundesland"] = next((b for b in BUNDESLAENDER if b.lower() in lower), None)
    data["objektart"] = next((o for o in OBJEKTARTEN if o.lower() in lower), None)

    return {k: v for k, v in data.items() if v not in (None, "")}
