from pathlib import Path

from dotenv import load_dotenv

# Lokale Einstellungen (z. B. Mail-Zugangsdaten) aus .env laden – die Datei ist in .gitignore.
# Bereits gesetzte Umgebungsvariablen haben Vorrang.
load_dotenv(Path(__file__).resolve().parent.parent / ".env")
