# Versteigerungs-Immobilien Österreich

Öffentliche Website, die Immobilien aus Versteigerungsedikten der
[Ediktsdatei](https://edikte.justiz.gv.at) übersichtlich mit Filter & Suche zeigt.
Objekte werden manuell über einen passwortgeschützten Admin-Bereich eingetragen.

## Lokal starten

```powershell
pip install -r requirements.txt
$env:ADMIN_PASSWORD = "ein-sicheres-passwort"
python -m uvicorn app.main:app --reload
```

- Website: http://127.0.0.1:8000
- Admin: http://127.0.0.1:8000/admin (Benutzer `admin`, Passwort aus `ADMIN_PASSWORD`)

## Automatischer Abgleich mit der Ediktsdatei

Die App durchsucht die Ediktsdatei selbst (alle Bundesländer) und verarbeitet nur neue Edikte:

| Edikt-Art | Was passiert |
|---|---|
| Versteigerung | Objekt wird angelegt (inkl. Kartenposition) |
| Verschiebung | neuer Termin wird beim Objekt eingetragen (bzw. Objekt angelegt) |
| Entfall des Termins | Objekt wird ausgeblendet |
| Zuschlag, Meistbotsverteilung | ignoriert |

- Läuft automatisch alle 24 Stunden (`AUTO_SYNC_STUNDEN`, `0` = aus), erster Lauf 1 Minute nach dem Start.
- Manuell: Admin → **Abgleich mit Ediktsdatei**, oder `python -m app.sync` (optional mit Bundesländern: `python -m app.sync Wien Tirol`).
- Nur bestimmte Bundesländer: `SYNC_BUNDESLAENDER=Wien,Niederösterreich`.
- Abrufe sind absichtlich gedrosselt (1 Sekunde Pause, `SYNC_PAUSE`); der erste Lauf für ganz Österreich dauert ca. 15–25 Minuten.

## Edikte per Link importieren

1. In der Ediktsdatei suchen, die Ergebnisliste (oder einzelne Edikt-Links) kopieren.
2. Admin → **Edikte importieren** → einfügen → **Importieren**.
3. Jedes Edikt wird abgerufen und angelegt; bereits vorhandene werden aktualisiert
   (erkannt an der Edikt-ID, z. B. bei geänderten Terminen).

Alternativ per Kommandozeile: `python -m app.importer liste.txt`

## Objekt manuell eintragen

1. Edikt auf edikte.justiz.gv.at öffnen, Text markieren und kopieren.
2. Im Admin „+ Neues Objekt“ → Text einfügen → **Text auslesen**.
3. Vorausgefüllte Felder prüfen/ergänzen, Link zum Edikt eintragen, speichern.

## Konfiguration (Umgebungsvariablen)

| Variable | Zweck |
|---|---|
| `ADMIN_PASSWORD` | Pflicht für den Admin-Bereich (ohne ist er gesperrt) |
| `ADMIN_USER` | Admin-Benutzername (Standard `admin`) |
| `SITE_NAME` | Name der Website |
| `IMPRESSUM` | Impressumstext (Pflicht für öffentliche Seiten in AT) |
| `EDIKT_DB` | Pfad zur SQLite-Datei (Standard `data/edikte.db`) |
| `AUTO_SYNC_STUNDEN` | Intervall für den automatischen Abgleich (Standard `24`, `0` = aus) |
| `SYNC_BUNDESLAENDER` | Nur diese Bundesländer abgleichen (kommagetrennt) |
| `GEOCODER_USER_AGENT` | Kennung für Nominatim, z. B. `meine-seite.at (kontakt@…)` |
| `TILE_URL`, `TILE_ATTRIBUTION` | Kartenkacheln (Standard: basemap.at, frei nutzbar, CC BY 4.0) |

## In GitHub Codespaces ausprobieren

Auf GitHub: **Code → Codespaces → Create codespace on main**. Abhängigkeiten werden
installiert und die Website startet automatisch auf Port 8000 (Admin-Passwort `test123`,
oder vorher ein Codespaces-Secret `ADMIN_PASSWORD` anlegen). Der erste Abgleich startet
nach einer Minute.

## Vor dem Veröffentlichen beachten

- **Keine Namen von Verpflichteten** oder anderen Personen übernehmen (DSGVO).
- Impressum setzen (§ 5 ECG, § 25 MedienG).
- Admin nur über **HTTPS** betreiben (Basic-Auth schickt das Passwort sonst im Klartext).
- Nutzungsbedingungen der Ediktsdatei prüfen; Verweis aufs Original-Edikt stets angeben.
