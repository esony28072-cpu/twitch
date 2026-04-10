"""
Datenbankmodul (SQLite) für Streamer und Aufnahmen.
Verwaltet die Persistenz der Streamer-Liste und Metadaten zu allen Aufnahmen.
"""
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from typing import List, Optional, Dict, Any

from .config import DB_FILE


SCHEMA = """
CREATE TABLE IF NOT EXISTS streamers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    added_at TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS recordings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL,
    title TEXT,
    filepath TEXT NOT NULL,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    duration_seconds INTEGER DEFAULT 0,
    file_size INTEGER DEFAULT 0
);
"""


@contextmanager
def get_conn():
    """Kontextmanager für eine SQLite-Verbindung."""
    conn = sqlite3.connect(str(DB_FILE))
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    """Initialisiert das Datenbankschema."""
    with get_conn() as conn:
        conn.executescript(SCHEMA)


# ---------- Streamer-Operationen ----------

def add_streamer(username: str) -> bool:
    """Fügt einen neuen Streamer hinzu. Gibt False zurück, falls bereits vorhanden."""
    username = username.strip().lstrip("@")
    if not username:
        return False
    try:
        with get_conn() as conn:
            conn.execute(
                "INSERT INTO streamers (username, added_at) VALUES (?, ?)",
                (username, datetime.now().isoformat()),
            )
        return True
    except sqlite3.IntegrityError:
        return False


def remove_streamer(username: str) -> None:
    """Entfernt einen Streamer aus der Datenbank."""
    with get_conn() as conn:
        conn.execute("DELETE FROM streamers WHERE username = ?", (username,))


def list_streamers() -> List[Dict[str, Any]]:
    """Gibt alle Streamer als Liste von Dictionaries zurück."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM streamers ORDER BY username COLLATE NOCASE"
        ).fetchall()
        return [dict(r) for r in rows]


# ---------- Aufnahme-Operationen ----------

def add_recording(username: str, filepath: str, title: Optional[str] = None) -> int:
    """Erstellt einen neuen Aufnahme-Eintrag und gibt dessen ID zurück."""
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO recordings (username, title, filepath, started_at)
               VALUES (?, ?, ?, ?)""",
            (username, title, filepath, datetime.now().isoformat()),
        )
        return cur.lastrowid


def finalize_recording(rec_id: int, duration: int, file_size: int) -> None:
    """Schließt eine Aufnahme ab und speichert Dauer & Dateigröße."""
    with get_conn() as conn:
        conn.execute(
            """UPDATE recordings
               SET ended_at = ?, duration_seconds = ?, file_size = ?
               WHERE id = ?""",
            (datetime.now().isoformat(), duration, file_size, rec_id),
        )


def update_recording_path(rec_id: int, new_path: str) -> None:
    """Aktualisiert den Dateipfad einer Aufnahme (z.B. nach .ts->.mp4 Remux)."""
    with get_conn() as conn:
        conn.execute(
            "UPDATE recordings SET filepath = ? WHERE id = ?",
            (new_path, rec_id),
        )


def list_recordings(username: Optional[str] = None) -> List[Dict[str, Any]]:
    """Listet Aufnahmen, optional gefiltert nach Streamer."""
    with get_conn() as conn:
        if username:
            rows = conn.execute(
                "SELECT * FROM recordings WHERE username = ? ORDER BY started_at DESC",
                (username,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM recordings ORDER BY started_at DESC"
            ).fetchall()
        return [dict(r) for r in rows]


def delete_recording(rec_id: int) -> None:
    """Entfernt einen Aufnahme-Eintrag aus der Datenbank."""
    with get_conn() as conn:
        conn.execute("DELETE FROM recordings WHERE id = ?", (rec_id,))
