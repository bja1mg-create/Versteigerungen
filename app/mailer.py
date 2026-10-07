"""E-Mail-Benachrichtigung über neue Versteigerungen.

Nach jedem Abgleich werden alle noch nicht gemeldeten Objekte (aktiv, Termin in
der Zukunft) in einer Mail verschickt und danach als gemeldet markiert. Schlägt
der Versand fehl, bleiben sie ungemeldet und kommen beim nächsten Lauf mit.

Konfiguration (Umgebungsvariablen oder .env):
    SMTP_HOST, SMTP_PORT (587 = STARTTLS, 465 = SSL), SMTP_USER, SMTP_PASSWORD
    MAIL_FROM   Absender (Standard: SMTP_USER)
    MAIL_TO     Empfänger, mehrere mit Komma getrennt
    SITE_URL    Adresse der Website für Links in der Mail (z. B. https://meine-seite.at)

Test:  python -m app.mailer --test     (schickt eine Mail mit den 3 nächsten Terminen)
"""
import html
import os
import smtplib
import ssl
import sys
from datetime import datetime
from email.message import EmailMessage
from email.utils import formataddr

from . import db
from .formatierung import datum, eur


def konfiguriert():
    return bool(os.environ.get("SMTP_HOST") and empfaenger())


def empfaenger():
    # Später erweiterbar, z. B. um eine Liste aus einem Google Sheet.
    return [a.strip() for a in os.environ.get("MAIL_TO", "").split(",") if a.strip()]


def _site_url():
    return os.environ.get("SITE_URL", "http://127.0.0.1:8000").rstrip("/")


def _ort(o):
    return ", ".join(x for x in (o["adresse"], " ".join(y for y in (o["plz"], o["ort"]) if y)) if x)


def nachricht(objekte, betreff_prefix=""):
    site, name = _site_url(), os.environ.get("SITE_NAME", "Versteigerungs-Immobilien Österreich")
    anzahl = len(objekte)
    betreff = f"{betreff_prefix}{anzahl} neue Versteigerung{'en' if anzahl != 1 else ''} in Österreich"

    text = [f"{betreff}\n"]
    zeilen = []
    for o in objekte:
        titel = o["titel"] or o["objektart"] or "Liegenschaft"
        link = f"{site}/objekt/{o['id']}"
        text.append(
            f"- {titel} – {_ort(o)} ({o['bundesland'] or '?'})\n"
            f"  Schätzwert {eur(o['schaetzwert'])}, geringstes Gebot {eur(o['geringstes_gebot'])}\n"
            f"  Termin: {datum(o['termin'])}\n  {link}\n")
        e = html.escape
        zeilen.append(f"""
        <tr>
          <td style="padding:8px;border-bottom:1px solid #e5e2db">
            <a href="{e(link)}" style="color:#1f5f8b;font-weight:600;text-decoration:none">{e(titel)}</a><br>
            <span style="color:#66707c">{e(_ort(o))}</span><br>
            <span style="color:#66707c;font-size:12px">{e(o['objektart'] or '')}</span>
          </td>
          <td style="padding:8px;border-bottom:1px solid #e5e2db">{e(o['bundesland'] or '')}</td>
          <td style="padding:8px;border-bottom:1px solid #e5e2db;text-align:right;white-space:nowrap">{e(eur(o['schaetzwert']))}</td>
          <td style="padding:8px;border-bottom:1px solid #e5e2db;text-align:right;white-space:nowrap">{e(eur(o['geringstes_gebot']))}</td>
          <td style="padding:8px;border-bottom:1px solid #e5e2db;white-space:nowrap">{e(datum(o['termin']))}</td>
        </tr>""")
    text.append(f"\nAlle Angebote und Karte: {site}/karte\n"
                "Alle Angaben ohne Gewähr. Maßgeblich ist das Edikt in der Ediktsdatei der Justiz.")

    th = 'style="padding:8px;text-align:left;border-bottom:2px solid #1f5f8b;font-size:12px;color:#66707c"'
    html_body = f"""<!doctype html><html><body style="margin:0;background:#f6f5f2;font-family:Segoe UI,Arial,sans-serif;color:#1d232b">
  <div style="max-width:760px;margin:0 auto;padding:20px">
    <h2 style="margin:0 0 4px">{html.escape(betreff)}</h2>
    <p style="margin:0 0 16px;color:#66707c">{html.escape(name)} · {datetime.now():%d.%m.%Y}</p>
    <table style="width:100%;border-collapse:collapse;background:#fff;font-size:14px">
      <tr><th {th}>Objekt</th><th {th}>Bundesland</th><th {th}>Schätzwert</th><th {th}>Geringstes Gebot</th><th {th}>Termin</th></tr>
      {''.join(zeilen)}
    </table>
    <p><a href="{html.escape(site)}/karte" style="color:#1f5f8b">Alle Angebote auf der Karte ansehen</a></p>
    <p style="color:#66707c;font-size:12px">Alle Angaben ohne Gewähr. Maßgeblich ist ausschließlich das Edikt in der Ediktsdatei der Justiz.</p>
  </div></body></html>"""

    msg = EmailMessage()
    msg["Subject"] = betreff
    absender = os.environ.get("MAIL_FROM") or os.environ.get("SMTP_USER", "")
    msg["From"] = formataddr((name, absender))
    msg["To"] = absender  # Empfänger stehen in Bcc, damit sie sich gegenseitig nicht sehen
    msg.set_content("\n".join(text))
    msg.add_alternative(html_body, subtype="html")
    return msg


def senden(msg, an):
    host = os.environ["SMTP_HOST"]
    port = int(os.environ.get("SMTP_PORT", "587"))
    user, password = os.environ.get("SMTP_USER"), os.environ.get("SMTP_PASSWORD")
    ctx = ssl.create_default_context()
    if port == 465:
        server = smtplib.SMTP_SSL(host, port, context=ctx, timeout=30)
    else:
        server = smtplib.SMTP(host, port, timeout=30)
        server.starttls(context=ctx)
    with server:
        if user:
            server.login(user, password or "")
        server.send_message(msg, to_addrs=an)


def neue_melden(log=print):
    """Verschickt alle ungemeldeten Objekte. Liefert die Anzahl gemeldeter Objekte."""
    if not konfiguriert():
        return 0
    objekte = db.ungemeldet(datetime.now().strftime("%Y-%m-%dT%H:%M"))
    if not objekte:
        log("Mail: keine neuen Versteigerungen")
        return 0
    try:
        senden(nachricht(objekte), empfaenger())
    except Exception as exc:
        log(f"Mail: Versand fehlgeschlagen ({exc}) – wird beim nächsten Abgleich wiederholt")
        return 0
    db.als_gemeldet_markieren([o["id"] for o in objekte])
    log(f"Mail: {len(objekte)} neue Versteigerung(en) an {len(empfaenger())} Empfänger gesendet")
    return len(objekte)


def testmail():
    """Testmail mit den nächsten Terminen; markiert nichts als gemeldet."""
    objekte = db.search(now_iso=datetime.now().strftime("%Y-%m-%dT%H:%M"))[:3]
    senden(nachricht(objekte, betreff_prefix="[TEST] "), empfaenger())
    return len(objekte)


if __name__ == "__main__":
    db.init_db()
    if not konfiguriert():
        sys.exit("Mail nicht konfiguriert: SMTP_HOST und MAIL_TO in .env setzen (siehe .env.example).")
    if "--test" in sys.argv:
        print(f"Testmail mit {testmail()} Objekten an {', '.join(empfaenger())} gesendet.")
    else:
        neue_melden()
