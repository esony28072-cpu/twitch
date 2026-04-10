"""
Konfigurationsmodul für den TikTok Live Recorder.
Enthält Standardpfade, Konstanten und Lade-/Speicherfunktionen für Einstellungen.
"""
import json
import os
from pathlib import Path

# Basis-Verzeichnisse
APP_DIR = Path.home() / ".tiktok_recorder"
APP_DIR.mkdir(exist_ok=True)

CONFIG_FILE = APP_DIR / "config.json"
DB_FILE = APP_DIR / "recordings.db"
LOG_FILE = APP_DIR / "recorder.log"

# Standard-Einstellungen
DEFAULT_CONFIG = {
    "output_dir": str(Path.home() / "TikTokRecordings"),
    "check_interval": 120,           # Sekunden zwischen den Live-Checks
    "notifications_enabled": True,
    "dark_mode": True,
    "video_format": "mp4",
    "autostart_recording": True,
    "reencode_on_remux": True,       # Re-Encode statt Copy beim Remux:
                                     # robuster gegen Auflösungs-/Codec-Wechsel
                                     # mitten im Stream (z.B. Multi-Guest-Streams),
                                     # braucht aber mehr CPU
}


def load_config() -> dict:
    """Lädt die Konfiguration aus der JSON-Datei oder erstellt eine neue."""
    if not CONFIG_FILE.exists():
        save_config(DEFAULT_CONFIG)
        return DEFAULT_CONFIG.copy()
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        # Fehlende Schlüssel mit Defaults ergänzen
        for k, v in DEFAULT_CONFIG.items():
            cfg.setdefault(k, v)
        return cfg
    except (json.JSONDecodeError, OSError):
        return DEFAULT_CONFIG.copy()


def save_config(cfg: dict) -> None:
    """Speichert die Konfiguration in die JSON-Datei."""
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)


def ensure_output_dir(path: str) -> Path:
    """Stellt sicher, dass das Ausgabeverzeichnis existiert."""
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p
