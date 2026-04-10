"""
TikTok Live Recorder — Hauptprogramm (Web-Version).

Startet Logging, initialisiert die Datenbank und öffnet die Web-GUI im Browser.

Aufruf:
    python main.py

Umgebungsvariablen (für Server-Betrieb):
    TTR_HOST       Host-Adresse (Standard: 127.0.0.1, Server: 0.0.0.0)
    TTR_PORT       TCP-Port (Standard: 8765)
    TTR_OPEN       "1" = Browser öffnen, "0" = nicht öffnen (Standard: 1)
    TTR_AUTH_USER  optional: Basic-Auth Benutzername
    TTR_AUTH_PASS  optional: Basic-Auth Passwort

Beispiel (Server):
    TTR_HOST=0.0.0.0 TTR_OPEN=0 TTR_AUTH_USER=admin TTR_AUTH_PASS=secret python main.py
"""
import logging
import os
import sys

from tiktok_recorder.config import LOG_FILE
from tiktok_recorder.database import init_db
from tiktok_recorder.web import run_web


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(LOG_FILE, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


def main() -> int:
    setup_logging()
    log = logging.getLogger("main")
    log.info("Starte TikTok Live Recorder (Web-GUI) …")
    init_db()

    host = os.environ.get("TTR_HOST", "45.84.199.167")
    port = int(os.environ.get("TTR_PORT", "8765"))
    open_browser = os.environ.get("TTR_OPEN", "1") == "1"
    auth_user = os.environ.get("TTR_AUTH_USER")
    auth_pass = os.environ.get("TTR_AUTH_PASS")

    run_web(
        host=host,
        port=port,
        open_browser=open_browser,
        auth_user=auth_user,
        auth_pass=auth_pass,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
