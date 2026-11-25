"""Encrypted, retention-bound storage for the wellbeing tools.

Privacy by design choices:

* Payloads are encrypted at rest with Fernet (AES-128-CBC + HMAC-SHA256).
* The resident pseudonym is never stored in clear: rows are keyed by
  ``HMAC-SHA256(key, subject)`` so a stolen DB file cannot be joined with
  other datasets without the key.
* Every row has a hard retention limit; ``purge_expired`` runs periodically.
* ``erase_subject`` implements the GDPR right to erasure (Art. 17).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from cryptography.fernet import Fernet

_SCHEMA = """
CREATE TABLE IF NOT EXISTS mood (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    subject TEXT NOT NULL,
    ts INTEGER NOT NULL,
    payload BLOB NOT NULL
);
CREATE INDEX IF NOT EXISTS mood_subject_ts ON mood(subject, ts);
CREATE TABLE IF NOT EXISTS reminder (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    subject TEXT NOT NULL,
    due_ts INTEGER NOT NULL,
    created_ts INTEGER NOT NULL,
    delivered INTEGER NOT NULL DEFAULT 0,
    payload BLOB NOT NULL
);
CREATE INDEX IF NOT EXISTS reminder_subject_due ON reminder(subject, due_ts);
"""


@dataclass(frozen=True)
class Reminder:
    id: int
    due_ts: int
    text: str


class WellbeingStore:
    def __init__(self, db_path: Path | str, key: str, retention_days: int = 30) -> None:
        raw = base64.urlsafe_b64decode(key.encode())
        if len(raw) != 32:
            raise ValueError("data key must be a 32-byte urlsafe-base64 Fernet key")
        self._fernet = Fernet(key.encode())
        # Derive an independent key for pseudonym hashing (domain separation).
        self._hmac_key = hashlib.sha256(b"moody-subject-v1" + raw).digest()
        self.retention_s = retention_days * 86400
        self._lock = threading.Lock()
        self._db = sqlite3.connect(str(db_path), check_same_thread=False, isolation_level=None)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA secure_delete=ON")  # overwrite deleted content on disk
        self._db.executescript(_SCHEMA)

    # -- helpers -----------------------------------------------------------------
    def _sid(self, subject: str) -> str:
        if not subject or len(subject) > 128:
            raise ValueError("invalid subject")
        return hmac.new(self._hmac_key, subject.encode(), hashlib.sha256).hexdigest()

    def _enc(self, obj: dict) -> bytes:
        return self._fernet.encrypt(json.dumps(obj, ensure_ascii=False).encode())

    def _dec(self, blob: bytes) -> dict:
        return json.loads(self._fernet.decrypt(blob))

    # -- mood journal ---------------------------------------------------------------
    def add_mood(self, subject: str, score: int, note: str | None, now: float | None = None) -> int:
        if not 1 <= score <= 5:
            raise ValueError("score must be between 1 and 5")
        note = (note or "").strip()[:280] or None
        with self._lock:
            cur = self._db.execute(
                "INSERT INTO mood(subject, ts, payload) VALUES (?, ?, ?)",
                (self._sid(subject), int(now or time.time()), self._enc({"score": score, "note": note})),
            )
            return int(cur.lastrowid)

    def mood_entries(self, subject: str, days: int, now: float | None = None) -> list[dict]:
        since = int((now or time.time()) - days * 86400)
        with self._lock:
            rows = self._db.execute(
                "SELECT ts, payload FROM mood WHERE subject=? AND ts>=? ORDER BY ts",
                (self._sid(subject), since),
            ).fetchall()
        return [{"ts": ts, **self._dec(blob)} for ts, blob in rows]

    # -- reminders --------------------------------------------------------------------
    def add_reminder(self, subject: str, text: str, due_ts: int, now: float | None = None) -> int:
        text = text.strip()[:200]
        if not text:
            raise ValueError("empty reminder")
        with self._lock:
            pending = self._db.execute(
                "SELECT COUNT(*) FROM reminder WHERE subject=? AND delivered=0", (self._sid(subject),)
            ).fetchone()[0]
            if pending >= 50:
                raise ValueError("too many pending reminders")
            cur = self._db.execute(
                "INSERT INTO reminder(subject, due_ts, created_ts, payload) VALUES (?, ?, ?, ?)",
                (self._sid(subject), int(due_ts), int(now or time.time()), self._enc({"text": text})),
            )
            return int(cur.lastrowid)

    def list_reminders(self, subject: str) -> list[Reminder]:
        with self._lock:
            rows = self._db.execute(
                "SELECT id, due_ts, payload FROM reminder WHERE subject=? AND delivered=0 ORDER BY due_ts",
                (self._sid(subject),),
            ).fetchall()
        return [Reminder(i, d, self._dec(p)["text"]) for i, d, p in rows]

    def cancel_reminder(self, subject: str, reminder_id: int) -> bool:
        with self._lock:
            cur = self._db.execute(
                "DELETE FROM reminder WHERE id=? AND subject=?", (int(reminder_id), self._sid(subject))
            )
            return cur.rowcount > 0

    def pop_due(self, subject: str, now: float | None = None) -> list[Reminder]:
        now_i = int(now or time.time())
        sid = self._sid(subject)
        with self._lock:
            rows = self._db.execute(
                "SELECT id, due_ts, payload FROM reminder WHERE subject=? AND delivered=0 AND due_ts<=?",
                (sid, now_i),
            ).fetchall()
            if rows:
                self._db.executemany("UPDATE reminder SET delivered=1 WHERE id=?", [(r[0],) for r in rows])
        return [Reminder(i, d, self._dec(p)["text"]) for i, d, p in rows]

    # -- data subject rights & retention -------------------------------------------
    def erase_subject(self, subject: str) -> int:
        sid = self._sid(subject)
        with self._lock:
            n = self._db.execute("DELETE FROM mood WHERE subject=?", (sid,)).rowcount
            n += self._db.execute("DELETE FROM reminder WHERE subject=?", (sid,)).rowcount
            self._db.execute("VACUUM")
        return n

    def export_subject(self, subject: str) -> dict:
        return {
            "mood": self.mood_entries(subject, days=10_000),
            "reminders": [r.__dict__ for r in self.list_reminders(subject)],
        }

    def purge_expired(self, now: float | None = None) -> int:
        cutoff = int((now or time.time()) - self.retention_s)
        with self._lock:
            n = self._db.execute("DELETE FROM mood WHERE ts<?", (cutoff,)).rowcount
            n += self._db.execute(
                "DELETE FROM reminder WHERE (delivered=1 AND due_ts<?) OR due_ts<?",
                (int(now or time.time()) - 86400, cutoff),
            ).rowcount
        return n
