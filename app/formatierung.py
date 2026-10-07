"""Anzeigeformate (Website und E-Mail)."""
from datetime import datetime


def eur(value):
    if value is None:
        return "–"
    return "€ " + f"{value:,.0f}".replace(",", ".")


def datum(value):
    if not value:
        return "–"
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return value
    return dt.strftime("%d.%m.%Y, %H:%M Uhr") if dt.hour or dt.minute else dt.strftime("%d.%m.%Y")


def m2(value):
    if value is None:
        return "–"
    return f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".").removesuffix(",00") + " m²"
