"""Adressen -> Koordinaten über Nominatim (OpenStreetMap).

Nutzungsregeln von Nominatim: max. 1 Anfrage/Sekunde, eindeutiger User-Agent,
Ergebnisse cachen (wir speichern sie in der Datenbank und fragen nur einmal).
"""
import json
import os
import re
import time
import urllib.parse
import urllib.request

from .db import BUNDESLAENDER

NOMINATIM = os.environ.get("NOMINATIM_URL", "https://nominatim.openstreetmap.org/search")
USER_AGENT = os.environ.get("GEOCODER_USER_AGENT", "edikt-immo/1.0 (Versteigerungs-Immobilien)")

_last_request = 0.0


def _query(params):
    global _last_request
    wait = 1.1 - (time.monotonic() - _last_request)
    if wait > 0:
        time.sleep(wait)
    url = NOMINATIM + "?" + urllib.parse.urlencode(
        {**params, "countrycodes": "at", "format": "jsonv2", "addressdetails": 1, "limit": 1})
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            results = json.load(resp)
    finally:
        _last_request = time.monotonic()
    return results[0] if results else None


def strasse_bereinigen(adresse):
    """'Lazarettgasse 37 u. 37a' -> 'Lazarettgasse 37', 'Zeillergasse 85/Dorngasse 2' -> 'Zeillergasse 85'."""
    if not adresse:
        return None
    s = re.split(r"\s+(?:u\.|und|bzw\.)\s+|/|,|;|&", adresse)[0]
    return s.strip() or None


def geocode(adresse, plz, ort):
    """Liefert dict(lat, lon, geo_genau, bundesland?) oder None.

    geo_genau = 1: Adresse gefunden; 0: nur PLZ/Ort (ungefähre Lage).
    """
    if not (plz or ort):
        return None
    strasse = strasse_bereinigen(adresse)
    attempts = []
    if strasse:
        attempts.append(({"street": strasse, "postalcode": plz or "", "city": ort or ""}, 1))
        attempts.append(({"street": strasse, "city": ort or ""}, 1))
    attempts.append(({"postalcode": plz or "", "city": ort or ""}, 0))
    for params, genau in attempts:
        if not any(params.values()):
            continue
        hit = _query({k: v for k, v in params.items() if v})
        if hit:
            result = {"lat": float(hit["lat"]), "lon": float(hit["lon"]), "geo_genau": genau}
            state = (hit.get("address") or {}).get("state")
            if state in BUNDESLAENDER:
                result["bundesland"] = state
            return result
    return None


def geocode_sicher(data):
    """Wie geocode(), aber Fehler (Netzwerk etc.) ergeben {} statt einer Exception."""
    try:
        return geocode(data.get("adresse"), data.get("plz"), data.get("ort")) or {}
    except Exception:
        return {}
