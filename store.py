"""Локальное хранилище сообщений (SQLite) для настольного Telegram-чата.

Каждое изменение сообщения увеличивает глобальный счётчик ``rev``.
Клиент запрашивает "что изменилось после rev=N" — так UI обновляется
без полной перерисовки и без потерь при правках/докачке файлов.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any, Iterable

SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id         INTEGER NOT NULL,
    chat_id    INTEGER NOT NULL,
    direction  TEXT    NOT NULL,          -- 'in' | 'out'
    date       INTEGER NOT NULL,          -- unix, секунды
    text       TEXT    NOT NULL DEFAULT '',
    caption    TEXT    NOT NULL DEFAULT '',
    kind       TEXT    NOT NULL DEFAULT 'text',
    media      TEXT,                      -- JSON с метаданными вложения
    fwd        TEXT,                      -- JSON с информацией о пересылке
    transcript TEXT,                      -- расшифровка голосового
    transcript_state TEXT,                -- queued | running | done | error
    transcript_error TEXT,                -- текст ошибки распознавания
    local_path TEXT,                      -- локальный файл, если уже скачан
    status     TEXT    NOT NULL DEFAULT 'ok',   -- ok | failed
    error      TEXT,
    edited     INTEGER NOT NULL DEFAULT 0,
    rev        INTEGER NOT NULL,
    PRIMARY KEY (id, chat_id)
);
CREATE INDEX IF NOT EXISTS idx_messages_rev  ON messages(rev);
CREATE INDEX IF NOT EXISTS idx_messages_date ON messages(date);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS chats (
    chat_id    INTEGER PRIMARY KEY,
    title      TEXT,
    username   TEXT,
    first_name TEXT,
    last_name  TEXT,
    photo_path TEXT,
    allowed    INTEGER NOT NULL DEFAULT 0,
    last_date  INTEGER,
    last_text  TEXT,
    added_at   INTEGER
);

CREATE TABLE IF NOT EXISTS known_users (
    user_id    INTEGER PRIMARY KEY,
    username   TEXT,
    first_name TEXT,
    last_name  TEXT,
    photo_path TEXT,
    last_seen  INTEGER,
    start_seen INTEGER NOT NULL DEFAULT 0
);
"""


def _display_name(first_name: str | None, last_name: str | None,
                  username: str | None, fallback: str = "") -> str:
    name = " ".join(part for part in (first_name, last_name) if part).strip()
    if name:
        return name
    if username:
        return "@" + username.lstrip("@")
    return fallback or "Без имени"


class Store:
    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._db = sqlite3.connect(str(db_path), check_same_thread=False, timeout=30)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA synchronous=NORMAL")
        self._db.executescript(SCHEMA)
        self._migrate()
        self._db.commit()

    def _migrate(self) -> None:
        columns = {row[1] for row in self._db.execute("PRAGMA table_info(messages)")}
        if "fwd" not in columns:
            self._db.execute("ALTER TABLE messages ADD COLUMN fwd TEXT")
        if "transcript" not in columns:
            self._db.execute("ALTER TABLE messages ADD COLUMN transcript TEXT")
        if "transcript_state" not in columns:
            self._db.execute("ALTER TABLE messages ADD COLUMN transcript_state TEXT")
        if "transcript_error" not in columns:
            self._db.execute("ALTER TABLE messages ADD COLUMN transcript_error TEXT")

    # ------------------------------------------------------------------ meta
    def meta_get(self, key: str, default: str | None = None) -> str | None:
        with self._lock:
            row = self._db.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default

    def meta_set(self, key: str, value: Any) -> None:
        with self._lock, self._db:
            self._db.execute(
                "INSERT INTO meta(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, str(value)),
            )

    def _next_rev(self) -> int:
        row = self._db.execute("SELECT value FROM meta WHERE key = 'rev'").fetchone()
        rev = int(row["value"]) + 1 if row else 1
        self._db.execute(
            "INSERT INTO meta(key, value) VALUES('rev', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (str(rev),),
        )
        return rev

    def current_rev(self) -> int:
        with self._lock:
            row = self._db.execute("SELECT value FROM meta WHERE key = 'rev'").fetchone()
        return int(row["value"]) if row else 0

    # -------------------------------------------------------------- messages
    def upsert(self, msg: dict[str, Any]) -> dict[str, Any]:
        """Вставить сообщение или обновить существующее (по id+chat_id)."""
        with self._lock, self._db:
            rev = self._next_rev()
            self._db.execute(
                """
                INSERT INTO messages
                    (id, chat_id, direction, date, text, caption, kind, media, fwd,
                     transcript, transcript_state, transcript_error,
                     local_path, status, error, edited, rev)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id, chat_id) DO UPDATE SET
                    date             = excluded.date,
                    text             = excluded.text,
                    caption          = excluded.caption,
                    kind             = excluded.kind,
                    media            = COALESCE(excluded.media, messages.media),
                    fwd              = COALESCE(excluded.fwd, messages.fwd),
                    transcript       = COALESCE(excluded.transcript, messages.transcript),
                    transcript_state = COALESCE(excluded.transcript_state, messages.transcript_state),
                    transcript_error = COALESCE(excluded.transcript_error, messages.transcript_error),
                    local_path       = COALESCE(excluded.local_path, messages.local_path),
                    status           = excluded.status,
                    error            = excluded.error,
                    edited           = excluded.edited,
                    rev              = excluded.rev
                """,
                (
                    int(msg["id"]),
                    int(msg["chat_id"]),
                    msg.get("direction", "in"),
                    int(msg["date"]),
                    msg.get("text") or "",
                    msg.get("caption") or "",
                    msg.get("kind") or "text",
                    json.dumps(msg["media"], ensure_ascii=False) if msg.get("media") else None,
                    json.dumps(msg["fwd"], ensure_ascii=False) if msg.get("fwd") else None,
                    msg.get("transcript"),
                    msg.get("transcript_state"),
                    msg.get("transcript_error"),
                    msg.get("local_path"),
                    msg.get("status") or "ok",
                    msg.get("error"),
                    1 if msg.get("edited") else 0,
                    rev,
                ),
            )
            row = self._db.execute(
                "SELECT * FROM messages WHERE id = ? AND chat_id = ?",
                (int(msg["id"]), int(msg["chat_id"])),
            ).fetchone()
        return self.public(row)

    def patch(self, msg_id: int, chat_id: int, **fields: Any) -> dict[str, Any] | None:
        allowed = {"text", "caption", "kind", "media", "fwd", "transcript",
                   "transcript_state", "transcript_error",
                   "local_path", "status", "error", "edited"}
        sets, values = [], []
        for key, value in fields.items():
            if key not in allowed:
                raise ValueError(f"нельзя менять поле {key}")
            if key in ("media", "fwd") and value is not None and not isinstance(value, str):
                value = json.dumps(value, ensure_ascii=False)
            sets.append(f"{key} = ?")
            values.append(value)
        if not sets:
            return self.get(msg_id, chat_id)
        with self._lock, self._db:
            rev = self._next_rev()
            sets.append("rev = ?")
            values.append(rev)
            values.extend([msg_id, chat_id])
            self._db.execute(
                f"UPDATE messages SET {', '.join(sets)} WHERE id = ? AND chat_id = ?", values
            )
            row = self._db.execute(
                "SELECT * FROM messages WHERE id = ? AND chat_id = ?", (msg_id, chat_id)
            ).fetchone()
        return self.public(row) if row else None

    def get(self, msg_id: int, chat_id: int) -> dict[str, Any] | None:
        with self._lock:
            row = self._db.execute(
                "SELECT * FROM messages WHERE id = ? AND chat_id = ?", (msg_id, chat_id)
            ).fetchone()
        return self.public(row) if row else None

    def get_raw(self, msg_id: int) -> sqlite3.Row | None:
        with self._lock:
            return self._db.execute("SELECT * FROM messages WHERE id = ?", (msg_id,)).fetchone()

    def after(self, rev: int, limit: int = 500) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._db.execute(
                "SELECT * FROM messages WHERE rev > ? ORDER BY rev ASC LIMIT ?", (rev, limit)
            ).fetchall()
        return [self.public(r) for r in rows]

    def recent(self, limit: int = 80) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._db.execute(
                "SELECT * FROM (SELECT * FROM messages ORDER BY date DESC, id DESC LIMIT ?) "
                "ORDER BY date ASC, id ASC",
                (limit,),
            ).fetchall()
        return [self.public(r) for r in rows]

    def before(self, msg_id: int, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._db.execute(
                "SELECT * FROM (SELECT * FROM messages WHERE id < ? "
                "ORDER BY date DESC, id DESC LIMIT ?) ORDER BY date ASC, id ASC",
                (msg_id, limit),
            ).fetchall()
        return [self.public(r) for r in rows]

    def has_before(self, msg_id: int) -> bool:
        with self._lock:
            row = self._db.execute(
                "SELECT 1 FROM messages WHERE id < ? LIMIT 1", (msg_id,)
            ).fetchone()
        return row is not None

    def failed_media(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._db.execute(
                "SELECT * FROM messages WHERE local_path IS NULL AND media IS NOT NULL "
                "AND error IS NOT NULL AND error != '' ORDER BY date ASC"
            ).fetchall()
        return [dict(r) for r in rows]

    def pending_transcriptions(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._db.execute(
                "SELECT id, kind, local_path FROM messages "
                "WHERE transcript_state IN ('queued', 'running') ORDER BY date ASC"
            ).fetchall()
        return [dict(r) for r in rows]

    def pending_downloads(self) -> Iterable[dict[str, Any]]:
        with self._lock:
            rows = self._db.execute(
                "SELECT * FROM messages WHERE kind != 'text' AND local_path IS NULL "
                "AND media IS NOT NULL AND status = 'ok' ORDER BY date ASC"
            ).fetchall()
        return [self.public(r) for r in rows]

    def count(self) -> int:
        with self._lock:
            row = self._db.execute("SELECT COUNT(*) AS n FROM messages").fetchone()
        return int(row["n"])

    # ------------------------------------------------------------------ чаты
    def upsert_chat(self, chat_id: int, *, title: str | None = None,
                    username: str | None = None, first_name: str | None = None,
                    last_name: str | None = None, photo_path: str | None = None,
                    allowed: bool | None = None, last_date: int | None = None,
                    last_text: str | None = None) -> dict[str, Any]:
        existing = self.get_chat(chat_id)
        now = int(__import__("time").time())
        with self._lock, self._db:
            if existing:
                self._db.execute(
                    """
                    UPDATE chats SET
                        title      = COALESCE(?, title),
                        username   = COALESCE(?, username),
                        first_name = COALESCE(?, first_name),
                        last_name  = COALESCE(?, last_name),
                        photo_path = COALESCE(?, photo_path),
                        allowed    = COALESCE(?, allowed),
                        last_date  = COALESCE(?, last_date),
                        last_text  = COALESCE(?, last_text),
                        added_at   = CASE WHEN ? = 1 AND added_at IS NULL THEN ? ELSE added_at END
                    WHERE chat_id = ?
                    """,
                    (
                        title, username, first_name, last_name, photo_path,
                        None if allowed is None else (1 if allowed else 0),
                        last_date, last_text,
                        None if allowed is None else (1 if allowed else 0),
                        now, int(chat_id),
                    ),
                )
            else:
                self._db.execute(
                    """
                    INSERT INTO chats(chat_id, title, username, first_name, last_name,
                                      photo_path, allowed, last_date, last_text, added_at)
                    VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        int(chat_id), title, username, first_name, last_name, photo_path,
                        1 if allowed else 0, last_date, last_text,
                        now if allowed else None,
                    ),
                )
        return self.get_chat(chat_id) or {}

    def get_chat(self, chat_id: int) -> dict[str, Any] | None:
        with self._lock:
            row = self._db.execute("SELECT * FROM chats WHERE chat_id = ?", (int(chat_id),)).fetchone()
        return self._chat_public(row) if row else None

    def list_chats(self, allowed_only: bool = True) -> list[dict[str, Any]]:
        query = "SELECT * FROM chats"
        params: tuple[Any, ...] = ()
        if allowed_only:
            query += " WHERE allowed = 1"
        query += " ORDER BY COALESCE(last_date, added_at, 0) DESC"
        with self._lock:
            rows = self._db.execute(query, params).fetchall()
        return [self._chat_public(row) for row in rows]

    def set_chat_allowed(self, chat_id: int, allowed: bool) -> dict[str, Any] | None:
        with self._lock, self._db:
            self._db.execute(
                "UPDATE chats SET allowed = ?, added_at = COALESCE(added_at, ?) WHERE chat_id = ?",
                (1 if allowed else 0, int(__import__("time").time()), int(chat_id)),
            )
        return self.get_chat(chat_id)

    def delete_chat(self, chat_id: int) -> None:
        with self._lock, self._db:
            self._db.execute("DELETE FROM messages WHERE chat_id = ?", (int(chat_id),))
            self._db.execute("DELETE FROM chats WHERE chat_id = ?", (int(chat_id),))

    def update_chat_last(self, chat_id: int, date: int, text: str) -> None:
        with self._lock, self._db:
            self._db.execute(
                "UPDATE chats SET last_date = ?, last_text = ? WHERE chat_id = ?",
                (int(date), (text or "")[:200], int(chat_id)),
            )

    def backfill_chat_last(self) -> None:
        """Заполнить превью чатов по уже существующей истории сообщений."""
        with self._lock:
            rows = self._db.execute(
                "SELECT c.chat_id, m.date, m.text, m.caption, m.kind FROM chats c "
                "JOIN messages m ON m.chat_id = c.chat_id "
                "WHERE m.date = (SELECT MAX(m2.date) FROM messages m2 WHERE m2.chat_id = c.chat_id)"
            ).fetchall()
        for row in rows:
            text = row["caption"] or row["text"] or {
                "voice": "Голосовое сообщение",
                "audio": "Аудио",
                "photo": "Фото",
                "video": "Видео",
                "document": "Файл",
                "sticker": "Стикер",
            }.get(row["kind"], "Сообщение")
            self.update_chat_last(int(row["chat_id"]), int(row["date"]), text)

    def set_chat_photo(self, chat_id: int, photo_path: str) -> None:
        with self._lock, self._db:
            self._db.execute(
                "UPDATE chats SET photo_path = ? WHERE chat_id = ?",
                (photo_path, int(chat_id)),
            )
            self._db.execute(
                "UPDATE known_users SET photo_path = ? WHERE user_id = ?",
                (photo_path, int(chat_id)),
            )

    # ---------------------------------------------------------- известные люди
    def upsert_known_user(self, user_id: int, *, username: str | None = None,
                          first_name: str | None = None, last_name: str | None = None,
                          last_seen: int | None = None, start_seen: bool = False,
                          photo_path: str | None = None) -> dict[str, Any]:
        with self._lock, self._db:
            self._db.execute(
                """
                INSERT INTO known_users(user_id, username, first_name, last_name,
                                        photo_path, last_seen, start_seen)
                VALUES(?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    username   = COALESCE(excluded.username, known_users.username),
                    first_name = COALESCE(excluded.first_name, known_users.first_name),
                    last_name  = COALESCE(excluded.last_name, known_users.last_name),
                    photo_path = COALESCE(excluded.photo_path, known_users.photo_path),
                    last_seen  = COALESCE(excluded.last_seen, known_users.last_seen),
                    start_seen = MAX(known_users.start_seen, excluded.start_seen)
                """,
                (
                    int(user_id), username, first_name, last_name, photo_path,
                    last_seen, 1 if start_seen else 0,
                ),
            )
        return self.get_known_user(user_id) or {}

    def get_known_user(self, user_id: int) -> dict[str, Any] | None:
        with self._lock:
            row = self._db.execute("SELECT * FROM known_users WHERE user_id = ?", (int(user_id),)).fetchone()
        return self._known_public(row) if row else None

    def list_known_users(self, query: str = "", limit: int = 200) -> list[dict[str, Any]]:
        sql = "SELECT * FROM known_users"
        params: list[Any] = []
        query = (query or "").strip().lstrip("@")
        if query:
            sql += " WHERE username LIKE ? OR first_name LIKE ? OR last_name LIKE ? OR CAST(user_id AS TEXT) LIKE ?"
            like = f"%{query}%"
            params = [like, like, like, like]
        sql += " ORDER BY COALESCE(last_seen, 0) DESC LIMIT ?"
        params.append(int(limit))
        with self._lock:
            rows = self._db.execute(sql, params).fetchall()
        return [self._known_public(row) for row in rows]

    # ------------------------------------------------ сообщения по одному чату
    def recent_for_chat(self, chat_id: int, limit: int = 40) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._db.execute(
                "SELECT * FROM (SELECT * FROM messages WHERE chat_id = ? "
                "ORDER BY date DESC, id DESC LIMIT ?) ORDER BY date ASC, id ASC",
                (int(chat_id), limit),
            ).fetchall()
        return [self.public(r) for r in rows]

    def after_for_chat(self, chat_id: int, rev: int, limit: int = 500) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._db.execute(
                "SELECT * FROM messages WHERE chat_id = ? AND rev > ? ORDER BY rev ASC LIMIT ?",
                (int(chat_id), rev, limit),
            ).fetchall()
        return [self.public(r) for r in rows]

    def before_for_chat(self, chat_id: int, msg_id: int, limit: int = 40) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._db.execute(
                "SELECT * FROM (SELECT * FROM messages WHERE chat_id = ? AND id < ? "
                "ORDER BY date DESC, id DESC LIMIT ?) ORDER BY date ASC, id ASC",
                (int(chat_id), int(msg_id), limit),
            ).fetchall()
        return [self.public(r) for r in rows]

    def has_before_chat(self, chat_id: int, msg_id: int) -> bool:
        with self._lock:
            row = self._db.execute(
                "SELECT 1 FROM messages WHERE chat_id = ? AND id < ? LIMIT 1",
                (int(chat_id), int(msg_id)),
            ).fetchone()
        return row is not None

    def delete_chat_messages(self, chat_id: int) -> None:
        with self._lock, self._db:
            self._db.execute("DELETE FROM messages WHERE chat_id = ?", (int(chat_id),))

    # ------------------------------------------------------------------ utils
    @staticmethod
    def _chat_public(row: sqlite3.Row) -> dict[str, Any]:
        name = _display_name(row["first_name"], row["last_name"], row["username"],
                             row["title"] or str(row["chat_id"]))
        return {
            "id": int(row["chat_id"]),
            "title": row["title"] or name,
            "name": name,
            "username": row["username"],
            "avatar": row["photo_path"],
            "allowed": bool(row["allowed"]),
            "last_date": row["last_date"],
            "last_text": row["last_text"] or "",
            "added_at": row["added_at"],
        }

    @staticmethod
    def _known_public(row: sqlite3.Row) -> dict[str, Any]:
        name = _display_name(row["first_name"], row["last_name"], row["username"],
                             str(row["user_id"]))
        return {
            "id": int(row["user_id"]),
            "name": name,
            "username": row["username"],
            "avatar": row["photo_path"],
            "last_seen": row["last_seen"],
            "start_seen": bool(row["start_seen"]),
        }

    # ----------------------------------------------------------------- utils
    @staticmethod
    def public(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        media = None
        if row["media"]:
            try:
                media = json.loads(row["media"])
            except (TypeError, ValueError):
                media = None
        fwd = None
        if row["fwd"]:
            try:
                fwd = json.loads(row["fwd"])
            except (TypeError, ValueError):
                fwd = None
        return {
            "id": row["id"],
            "chat_id": row["chat_id"],
            "dir": row["direction"],
            "date": row["date"],
            "text": row["text"],
            "caption": row["caption"],
            "kind": row["kind"],
            "media": media,
            "fwd": fwd,
            "transcript": row["transcript"] or "",
            "transcript_state": row["transcript_state"] or "",
            "transcript_error": row["transcript_error"] or "",
            "local": bool(row["local_path"] and Path(row["local_path"]).is_file()),
            "status": row["status"],
            "error": row["error"],
            "edited": bool(row["edited"]),
            "rev": row["rev"],
        }

    def close(self) -> None:
        with self._lock:
            self._db.close()
