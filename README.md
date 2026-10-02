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

## Edikte importieren (empfohlen)

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

## Vor dem Veröffentlichen beachten

- **Keine Namen von Verpflichteten** oder anderen Personen übernehmen (DSGVO).
- Impressum setzen (§ 5 ECG, § 25 MedienG).
- Admin nur über **HTTPS** betreiben (Basic-Auth schickt das Passwort sonst im Klartext).
- Nutzungsbedingungen der Ediktsdatei prüfen; Verweis aufs Original-Edikt stets angeben.
