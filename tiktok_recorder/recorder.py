"""
Recorder-Modul.

Verantwortlich für:
- Erkennen, ob ein TikTok-Streamer gerade live ist
- Starten und Stoppen der Aufnahme via Streamlink/FFmpeg
- Verwalten laufender Aufnahmen pro Streamer

Benötigte Drittanbieter-Tools:
- streamlink (https://streamlink.github.io/) — empfohlen
- ffmpeg     (https://ffmpeg.org/)            — als Fallback / wird von streamlink genutzt

Optional kann die Live-Status-Erkennung über die Bibliothek `TikTokLive` erfolgen,
falls installiert. Andernfalls greift ein einfacher HTML-Scrape-Fallback.
"""
from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

import requests

from . import database as db
from .config import ensure_output_dir, load_config

log = logging.getLogger("recorder")


# --------------------------------------------------------------------------- #
# Live-Status-Erkennung
# --------------------------------------------------------------------------- #

_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    # WICHTIG: KEIN Accept-Encoding setzen!
    # Sonst fordert TikTok mit "br" (Brotli) komprimierte Antworten,
    # und falls das brotli-Paket nicht installiert ist, kann requests
    # die Antwort nicht dekomprimieren — die Folge wäre Binärmüll
    # statt HTML, und _get_room_id würde nichts finden.
    # Ohne diesen Header lässt requests gzip/deflate automatisch zu
    # und kann beides nativ dekomprimieren.
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
    "Referer": "https://www.tiktok.com/",
}


def _new_session() -> requests.Session:
    """
    Erstellt eine Session mit Cookies. TikTok setzt beim ersten Aufruf
    Tracking-Cookies, die bei Folgeanfragen mitgesendet werden müssen,
    sonst kommen 403/leere Antworten zurück.
    """
    s = requests.Session()
    s.headers.update(_BROWSER_HEADERS)
    try:
        # Initial-Request, um Cookies zu sammeln
        s.get("https://www.tiktok.com/", timeout=15)
    except requests.RequestException:
        pass
    return s


def _get_room_id(username: str) -> Optional[str]:
    """
    Holt die aktuelle Room-ID eines Benutzers über die Live-Seite.
    Die Room-ID ist nur gesetzt, wenn der User gerade einen Live-Stream hat.
    """
    url = f"https://www.tiktok.com/@{username}/live"
    session = _new_session()
    try:
        r = session.get(url, timeout=15, allow_redirects=True)
    except requests.RequestException as e:
        log.warning("Netzwerkfehler beim Abrufen von @%s: %s", username, e)
        return None

    if r.status_code != 200:
        log.warning(
            "Status %s für @%s (Server evtl. blockiert)", r.status_code, username
        )
        return None

    html = r.text

    # TikTok liefert im HTML einen JSON-Block mit "roomId"
    patterns = [
        r'"roomId":"(\d+)"',
        r'"room_id":"(\d+)"',
        r'room_id=(\d+)',
        r'"roomId":(\d+)',
    ]
    for pat in patterns:
        m = re.search(pat, html)
        if m:
            room_id = m.group(1)
            if room_id and room_id != "0":
                log.debug("Room-ID gefunden für @%s: %s", username, room_id)
                return room_id

    # Heuristik: Wenn die Seite eindeutig "offline" enthält, ist der User nicht live
    if "LIVE has ended" in html or '"isLive":false' in html:
        log.debug("@%s ist offline (Heuristik)", username)
        return None

    log.debug("Keine Room-ID in HTML für @%s gefunden", username)
    return None


def _check_live_via_webcast(room_id: str) -> Optional[bool]:
    """
    Fragt den TikTok webcast API-Endpoint nach dem Status der Room-ID.
    status == 2 bedeutet "live", status == 4 bedeutet "beendet".
    """
    url = (
        "https://webcast.tiktok.com/webcast/room/info/"
        f"?aid=1988&room_id={room_id}"
    )
    try:
        r = requests.get(url, headers=_BROWSER_HEADERS, timeout=15)
        if r.status_code != 200:
            return None
        data = r.json()
    except (requests.RequestException, ValueError) as e:
        log.debug("Webcast-Check fehlgeschlagen für Room %s: %s", room_id, e)
        return None

    # Bekannte Antwort-Strukturen:
    #   {"data": {"status": 2, ...}}
    #   {"data": {"room": {"status": 2, ...}}}
    try:
        payload = data.get("data", {}) if isinstance(data, dict) else {}
        status = payload.get("status")
        if status is None and isinstance(payload.get("room"), dict):
            status = payload["room"].get("status")
        if status is None:
            return None
        return int(status) == 2
    except (AttributeError, TypeError, ValueError):
        return None


def is_user_live(username: str) -> bool:
    """
    Prüft, ob ein Streamer derzeit live ist.

    Strategie:
    1. Room-ID aus der /live-Seite extrahieren
    2. Status über den Webcast-API-Endpoint verifizieren
    3. Fällt die API aus, gilt eine vorhandene Room-ID alleine bereits als Indikator
    """
    room_id = _get_room_id(username)
    if not room_id:
        log.info("Live-Check @%s: keine Room-ID → offline", username)
        return False

    status = _check_live_via_webcast(room_id)
    if status is None:
        # API-Aufruf fehlgeschlagen — konservativ: vorhandene Room-ID als "live" werten
        log.info(
            "Live-Check @%s: Room-ID %s vorhanden, Webcast-API blockt → "
            "werte als LIVE", username, room_id,
        )
        return True

    log.info(
        "Live-Check @%s: Room-ID %s, API-Status=%s → %s",
        username, room_id, status, "LIVE" if status else "offline",
    )
    return status


# --------------------------------------------------------------------------- #
# Aufnahme
# --------------------------------------------------------------------------- #

def _safe_filename(name: str) -> str:
    """Bereinigt einen Dateinamen von ungültigen Zeichen."""
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .") or "untitled"


def _build_output_path(username: str) -> Path:
    """
    Erstellt den Pfad für eine neue Aufnahme.

    Wir nehmen zunächst als .ts (MPEG-Transport-Stream) auf, weil das der
    native HLS-Containerformat ist. Nach dem Stopp wird mit ffmpeg in eine
    echte MP4 mit +faststart remuxt (siehe _remux_to_mp4).
    """
    cfg = load_config()
    base = ensure_output_dir(cfg["output_dir"])
    user_dir = base / _safe_filename(username)
    user_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    return user_dir / f"{username}_{timestamp}.ts"


def _streamlink_available() -> bool:
    return shutil.which("streamlink") is not None


def _ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def _remux_to_mp4(ts_path: Path) -> Optional[Path]:
    """
    Wandelt eine .ts-Datei mit ffmpeg in eine browser-kompatible .mp4 um.

    Strategie (zweistufig):
    1. Wenn `reencode_on_remux=True` (Standard): Video wird auf eine feste
       Auflösung skaliert und neu encodiert. Audio bleibt copy. Das ist
       robust gegen Auflösungs- und Codec-Wechsel mitten im Stream
       (häufig bei Multi-Guest-Streams), kostet aber CPU.
    2. Wenn `reencode_on_remux=False`: Reiner Copy-Mode (schnell, aber
       bricht bei Stream-Discontinuities — Bild friert ein, Audio läuft).

    Bei Fehlschlag des Re-Encodes wird automatisch auf Copy-Mode zurückgefallen,
    damit du wenigstens eine Datei hast.

    Wichtige ffmpeg-Flags in beiden Modi:
    - `-fflags +genpts+igndts+discardcorrupt`: bricht nicht bei kaputten
      DTS-Werten ab, generiert PTS neu, verwirft beschädigte Pakete
    - `-err_detect ignore_err`: tolerant gegen Bitstream-Fehler
    - `-avoid_negative_ts make_zero`: gleicht negative Timestamps aus
    - `-bsf:a aac_adtstoasc`: AAC für MP4-Container vorbereiten
    - `-movflags +faststart`: moov-Atom vorne (Browser-Streaming)
    """
    if not _ffmpeg_available():
        log.warning(
            "ffmpeg nicht gefunden — .ts-Datei bleibt unverändert: %s", ts_path
        )
        return None

    cfg = load_config()
    use_reencode = cfg.get("reencode_on_remux", True)
    mp4_path = ts_path.with_suffix(".mp4")

    def _build_cmd(reencode: bool) -> list:
        base = [
            "ffmpeg", "-y",
            "-fflags", "+genpts+igndts+discardcorrupt",
            "-err_detect", "ignore_err",
            "-i", str(ts_path),
            "-avoid_negative_ts", "make_zero",
        ]
        if reencode:
            # Video: H.264 encodieren mit fester Skalierung auf Höhe 1280 px,
            # Breite "auto" (Verhältnis bleibt). Falls Stream zwischendrin die
            # Auflösung wechselt, skaliert der Filter alle Frames einheitlich.
            # `setsar=1` setzt das Sample-Aspect-Ratio konstant — ohne das
            # könnten Players die Frames falsch strecken.
            return base + [
                "-vf", "scale=-2:1280:flags=lanczos,setsar=1",
                "-c:v", "libx264",
                "-preset", "veryfast",     # gut Balance CPU/Qualität
                "-crf", "23",              # vernünftige Qualität
                "-pix_fmt", "yuv420p",     # max Browser-Kompatibilität
                "-c:a", "copy",
                "-bsf:a", "aac_adtstoasc",
                "-movflags", "+faststart",
                str(mp4_path),
            ]
        else:
            # Reiner Copy-Mode (schnell, aber empfindlich)
            return base + [
                "-c", "copy",
                "-bsf:a", "aac_adtstoasc",
                "-movflags", "+faststart",
                str(mp4_path),
            ]

    def _try_run(reencode: bool) -> bool:
        cmd = _build_cmd(reencode)
        mode = "re-encode" if reencode else "copy"
        log.info("Remuxe (%s) %s -> %s", mode, ts_path.name, mp4_path.name)
        try:
            result = subprocess.run(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                timeout=3600,    # bei langen Streams + Re-Encode genug Zeit
            )
        except (subprocess.TimeoutExpired, OSError) as e:
            log.exception("Remux-Fehler (%s) für %s: %s", mode, ts_path, e)
            return False

        if (
            result.returncode != 0
            or not mp4_path.exists()
            or mp4_path.stat().st_size == 0
        ):
            err = result.stderr.decode("utf-8", errors="replace")[-800:]
            log.warning("ffmpeg-Remux (%s) fehlgeschlagen: %s", mode, err)
            try:
                if mp4_path.exists():
                    mp4_path.unlink()
            except OSError:
                pass
            return False
        return True

    # Erst die gewünschte Methode probieren
    success = _try_run(use_reencode)

    # Falls Re-Encode fehlgeschlagen ist: Copy als Fallback
    if not success and use_reencode:
        log.warning("Re-Encode fehlgeschlagen, versuche Copy-Mode als Fallback")
        success = _try_run(False)

    if not success:
        return None

    # Original .ts löschen
    try:
        ts_path.unlink()
    except OSError as e:
        log.warning("Konnte .ts nicht löschen: %s", e)

    log.info(
        "Remux erfolgreich: %s (%.1f MB)",
        mp4_path.name, mp4_path.stat().st_size / 1024 / 1024,
    )
    return mp4_path


class RecordingProcess:
    """Repräsentiert einen laufenden Aufnahmeprozess für einen Streamer."""

    def __init__(self, username: str):
        self.username = username
        self.process: Optional[subprocess.Popen] = None
        self.filepath: Optional[Path] = None
        self.rec_id: Optional[int] = None
        self.started_at: Optional[float] = None
        self._log_file = None

    def start(self) -> bool:
        """Startet die Aufnahme. Gibt True bei Erfolg zurück."""
        self.filepath = _build_output_path(self.username)
        url = f"https://www.tiktok.com/@{self.username}/live"

        if _streamlink_available():
            # Robuste Optionen gegen verpixelte / abgehackte Aufnahmen
            # und gegen Stream-Discontinuities (z.B. bei Multi-Guest-Streams,
            # wo TikTok mitten im Stream die Auflösung wechselt):
            cmd = [
                "streamlink",
                "--hls-live-restart",
                "--hls-live-edge", "6",
                "--stream-segment-attempts", "10",
                "--stream-segment-threads", "3",
                "--stream-segment-timeout", "20",
                "--stream-timeout", "120",
                "--ringbuffer-size", "128M",
                "--retry-streams", "3",
                "--retry-max", "5",
                # HLS-Playlist-Reload-Versuche bei Discontinuities erhöhen
                "--hls-playlist-reload-attempts", "5",
                # Keine Discontinuities filtern — alle Segmente schreiben
                # damit ffmpeg sie später beim Remux zu einer durchgehenden
                # Datei zusammenfügen kann
                "--hls-segment-stream-data",
                "--loglevel", "warning",
                "-o", str(self.filepath),
                url,
                "best,1080p,720p,source",
            ]
        elif _ffmpeg_available():
            # Sehr einfacher FFmpeg-Fallback (versucht direkt, die Seite zu pullen)
            # Forciere MPEG-TS-Container, damit _remux_to_mp4 danach sauber wandelt
            cmd = [
                "ffmpeg", "-y",
                "-i", url,
                "-c", "copy",
                "-f", "mpegts",
                str(self.filepath),
            ]
        else:
            log.error("Weder streamlink noch ffmpeg gefunden — Aufnahme nicht möglich.")
            return False

        try:
            log.info("Starte Aufnahme: %s -> %s", self.username, self.filepath)
            # streamlink-Ausgabe in eine Log-Datei neben die Aufnahme schreiben,
            # damit man verlorene Segmente & Warnungen später nachvollziehen kann
            self._log_file = open(
                str(self.filepath) + ".streamlink.log", "wb"
            )
            self.process = subprocess.Popen(
                cmd,
                stdout=self._log_file,
                stderr=subprocess.STDOUT,
            )
            self.started_at = time.time()
            self.rec_id = db.add_recording(self.username, str(self.filepath))
            return True
        except OSError as e:
            log.exception("Fehler beim Starten der Aufnahme für %s: %s", self.username, e)
            if hasattr(self, "_log_file") and self._log_file:
                self._log_file.close()
            return False

    def is_running(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def stop(self) -> None:
        """Stoppt die Aufnahme, remuxt nach MP4 und finalisiert den DB-Eintrag."""
        if self.process and self.is_running():
            log.info("Stoppe Aufnahme für %s", self.username)
            try:
                self.process.terminate()
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
            except Exception as e:
                log.warning("Fehler beim Stoppen: %s", e)

        # Streamlink-Log schließen
        if self._log_file:
            try:
                self._log_file.close()
            except OSError:
                pass
            self._log_file = None

        # .ts -> .mp4 remuxen, damit die Datei im Browser abspielbar ist
        final_path = self.filepath
        if (
            final_path
            and final_path.exists()
            and final_path.suffix.lower() == ".ts"
            and final_path.stat().st_size > 0
        ):
            mp4 = _remux_to_mp4(final_path)
            if mp4 is not None:
                final_path = mp4

        if self.rec_id is not None and final_path is not None:
            duration = int(time.time() - (self.started_at or time.time()))
            try:
                size = final_path.stat().st_size if final_path.exists() else 0
            except OSError:
                size = 0
            # DB-Pfad aktualisieren, falls sich durch Remuxing der Pfad geändert hat
            if final_path != self.filepath:
                db.update_recording_path(self.rec_id, str(final_path))
            db.finalize_recording(self.rec_id, duration, size)


# --------------------------------------------------------------------------- #
# Hintergrund-Manager
# --------------------------------------------------------------------------- #

class RecorderManager:
    """
    Verwaltet alle Streamer in einem Hintergrund-Thread.
    Prüft regelmäßig den Live-Status und startet/stoppt Aufnahmen automatisch.
    """

    def __init__(self, on_event=None):
        """
        :param on_event: optionaler Callback (event_type:str, username:str, info:dict)
                         für GUI-Benachrichtigungen.
        """
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._active: Dict[str, RecordingProcess] = {}
        self._splitting: set = set()   # Usernames, die gerade gesplittet werden
        self._lock = threading.Lock()
        self.on_event = on_event

    # -------- Lifecycle --------

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="RecorderLoop")
        self._thread.start()
        log.info("RecorderManager gestartet.")

    def stop(self) -> None:
        log.info("RecorderManager wird gestoppt …")
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
        with self._lock:
            for rp in list(self._active.values()):
                rp.stop()
            self._active.clear()

    # -------- Public API --------

    def active_streamers(self) -> Dict[str, RecordingProcess]:
        with self._lock:
            return dict(self._active)

    def is_recording(self, username: str) -> bool:
        with self._lock:
            if username in self._splitting:
                return True
            rp = self._active.get(username)
            return bool(rp and rp.is_running())

    def split_recording(self, username: str) -> bool:
        """
        Stoppt die aktuelle Aufnahme und startet nahtlos eine neue für denselben
        Streamer.

        - Die alte Datei wird finalisiert und ist direkt ansehbar
        - Eine neue Aufnahme läuft ab diesem Moment weiter
        - Der Haupt-Loop wird während des Splits daran gehindert, eine weitere
          Aufnahme parallel zu starten (via _splitting-Set)

        :return: True bei Erfolg, False wenn keine aktive Aufnahme existiert
        """
        with self._lock:
            if username in self._splitting:
                return False                       # bereits ein Split im Gange
            old = self._active.get(username)
            if not old or not old.is_running():
                return False
            self._splitting.add(username)
            del self._active[username]

        try:
            log.info("Splitte Aufnahme für %s", username)
            old.stop()
            self._emit("recording_stopped", username)

            new = RecordingProcess(username)
            if not new.start():
                log.warning("Neue Aufnahme nach Split fehlgeschlagen: %s", username)
                return False

            with self._lock:
                self._active[username] = new
            self._emit(
                "recording_started",
                username,
                {"filepath": str(new.filepath), "split": True},
            )
            return True
        finally:
            with self._lock:
                self._splitting.discard(username)

    def check_now(self, username: str) -> None:
        """
        Löst sofort eine Live-Prüfung für einen einzelnen Streamer aus.
        Läuft in einem Worker-Thread, damit die GUI nicht blockiert.
        """
        def _worker():
            try:
                cfg = load_config()
                self._handle_streamer(username, cfg)
            except Exception as e:
                log.exception("Sofort-Check fehlgeschlagen für %s: %s", username, e)

        threading.Thread(target=_worker, daemon=True, name=f"CheckNow-{username}").start()

    # -------- Loop --------

    def _emit(self, event: str, username: str, info: Optional[dict] = None) -> None:
        if self.on_event:
            try:
                self.on_event(event, username, info or {})
            except Exception as e:  # GUI-Callback darf den Loop nicht killen
                log.warning("on_event Callback Fehler: %s", e)

    def _run(self) -> None:
        while not self._stop.is_set():
            cfg = load_config()
            interval = max(30, int(cfg.get("check_interval", 120)))

            try:
                streamers = db.list_streamers()
            except Exception as e:
                log.exception("Fehler beim Laden der Streamer-Liste: %s", e)
                streamers = []

            for s in streamers:
                if self._stop.is_set():
                    break
                username = s["username"]
                try:
                    self._handle_streamer(username, cfg)
                except Exception as e:
                    log.exception("Fehler bei Streamer %s: %s", username, e)

            # Beendete Aufnahmen aufräumen
            with self._lock:
                for u, rp in list(self._active.items()):
                    if not rp.is_running():
                        rp.stop()
                        del self._active[u]
                        self._emit("recording_stopped", u)

            # Pausieren — aber unterbrechbar bleiben
            self._stop.wait(interval)

    def _handle_streamer(self, username: str, cfg: dict) -> None:
        already = self.is_recording(username)
        live = is_user_live(username)

        if live and not already and cfg.get("autostart_recording", True):
            rp = RecordingProcess(username)
            if rp.start():
                with self._lock:
                    self._active[username] = rp
                self._emit("recording_started", username, {"filepath": str(rp.filepath)})
        elif not live and already:
            with self._lock:
                rp = self._active.pop(username, None)
            if rp:
                rp.stop()
                self._emit("recording_stopped", username)
