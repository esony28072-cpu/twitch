# 🎬 TikTok Live Recorder

Ein Python-Programm mit **Web-GUI**, das automatisch erkennt, wenn ausgewählte
TikTok-Streamer live gehen, und ihre Streams lokal aufzeichnet. Die App läuft
als lokaler Webserver und öffnet sich automatisch im Browser.

## ✨ Features

- **Web-GUI** – startet automatisch im Browser unter http://127.0.0.1:8765
- **Streamer-Verwaltung** – Hinzufügen / Entfernen / Liste anzeigen
- **Sofort-Prüfung** neuer Streamer – keine Wartezeit auf den nächsten Intervall
- **Automatische Aufnahme** via `streamlink` (oder `ffmpeg` als Fallback)
- **✂ Split-Funktion** – aktuelle Aufnahme wird gespeichert, eine neue startet
  sofort ohne Unterbrechung des Livestreams. Perfekt für lange Streams!
- **Video-Player** im Browser – Aufnahmen direkt aus der Oberfläche abspielen
- **Download**-Button für jede Aufnahme
- **Strukturierte Ablage** – Ein Ordner pro Streamer, Zeitstempel im Dateinamen
- **Metadaten-Datenbank** (SQLite) – Startzeit, Dauer, Größe
- **Dark Mode UI**, Toast-Benachrichtigungen
- **Logging** in `~/.tiktok_recorder/recorder.log`

## 📁 Projektstruktur

```
project/
├── main.py                 # Einstiegspunkt (startet den Webserver)
├── requirements.txt
├── README.md
└── tiktok_recorder/
    ├── __init__.py
    ├── config.py           # Einstellungen / Pfade
    ├── database.py         # SQLite (Streamer + Aufnahmen)
    ├── recorder.py         # Live-Erkennung + Aufnahme + Split + Background-Thread
    └── web.py              # Flask-Webserver + Single-Page-App
```

## 🛠 Installation

### 1. Python-Abhängigkeiten

```bash
pip install -r requirements.txt
```

### 2. Externe Tools installieren

Du brauchst **mindestens eines** der beiden Tools im `PATH`:

- **streamlink** (empfohlen) – `pip install streamlink`
- **ffmpeg** – siehe https://ffmpeg.org/download.html
  - Windows: über [gyan.dev](https://www.gyan.dev/ffmpeg/builds/)
  - macOS:  `brew install ffmpeg`
  - Linux:  `sudo apt install ffmpeg`

### 3. Programm starten

```bash
python main.py
```

Der Browser öffnet sich automatisch unter **http://127.0.0.1:8765**.
Falls nicht, rufe diesen Link einfach manuell auf.

## 🚀 Bedienung

### Streamer hinzufügen
Tab **„👥 Streamer"** → Benutzernamen eingeben (ohne `@`) → **„➕ Hinzufügen"**.
Der neue Streamer wird sofort geprüft — falls er bereits live ist, startet die
Aufnahme innerhalb weniger Sekunden.

### ✂ Aufnahme splitten (Highlight-Feature)
Während eine Aufnahme läuft, erscheint bei dem Streamer ein **„✂ Splitten"**-Button.
Ein Klick darauf:
1. stoppt die aktuelle Aufnahme und finalisiert sie (du kannst sie sofort ansehen)
2. startet sofort eine neue Aufnahme — der Livestream geht nahtlos in die neue Datei

So kannst du lange Streams in handliche Stücke zerlegen und frühere Teile
anschauen, während der Stream noch weiterläuft.

### Aufnahme ansehen
Tab **„📂 Aufnahmen"** → bei der gewünschten Zeile auf **„▶ Abspielen"** klicken.
Der Video-Player öffnet sich direkt im Browser — mit Seeking-Unterstützung.

### Speicherort
Standard: `~/TikTokRecordings/<benutzername>/<benutzername>_YYYY-MM-DD_HH-MM-SS.mp4`
Änderbar im Tab **⚙ Einstellungen**.

### Konfiguration & Logs
Liegen in `~/.tiktok_recorder/`:
- `config.json` – Einstellungen
- `recordings.db` – SQLite-Datenbank
- `recorder.log` – Log-Datei

## 🔗 REST-API (Bonus)

Die Web-GUI nutzt intern eine saubere JSON-API — du kannst sie auch extern
ansprechen, z.B. für Automatisierung:

| Methode | Endpoint | Beschreibung |
|---|---|---|
| GET  | `/api/streamers` | Alle Streamer mit Live-Status |
| POST | `/api/streamers` | `{"username": "..."}` hinzufügen |
| DELETE | `/api/streamers/<name>` | Entfernen |
| POST | `/api/streamers/<name>/check` | Sofort prüfen |
| POST | `/api/streamers/check-all` | Alle sofort prüfen |
| POST | `/api/streamers/<name>/split` | Laufende Aufnahme splitten |
| GET  | `/api/recordings?username=<name>` | Aufnahmen (optional gefiltert) |
| DELETE | `/api/recordings/<id>` | DB-Eintrag löschen |
| GET  | `/api/recordings/<id>/video` | Videodatei streamen |
| GET/POST | `/api/config` | Einstellungen lesen/schreiben |

## ⚠ Hinweise

- Der Server lauscht standardmäßig nur auf **127.0.0.1** (localhost) — von
  außen nicht erreichbar. Falls du das ändern willst, passe `main.py` an
  und ersetze den Host durch `0.0.0.0`.
- TikTok bietet keine offizielle Public-API für Live-Status. Das Programm
  nutzt zuerst die Bibliothek [`TikTokLive`](https://pypi.org/project/TikTokLive/)
  falls installiert, und fällt sonst auf eine Room-ID-Extraktion +
  Webcast-API-Prüfung zurück.
- Beachte stets das Urheberrecht und die Persönlichkeitsrechte der Streamer.

## 🛑 Beenden

Drücke im Terminal `Strg+C` — der Server fährt herunter, laufende Aufnahmen
werden sauber gestoppt und finalisiert.
