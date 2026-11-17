"""Информация о пользователях и аватарки для мультичатового приложения."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from tgclient import Telegram, TelegramError

log = logging.getLogger(__name__)


def chat_payload(chat: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": int(chat.get("id") or 0),
        "type": chat.get("type"),
        "title": chat.get("title"),
        "username": chat.get("username"),
        "first_name": chat.get("first_name"),
        "last_name": chat.get("last_name"),
    }


def resolve_chat(tg: Telegram, query: str, known_users: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Найти пользователя по ID или @username через Bot API (с запасным поиском)."""
    raw = (query or "").strip()
    if not raw:
        raise ValueError("Пустой ID или username")
    candidates: list[Any] = []
    if raw.lstrip("-").isdigit():
        candidates.append(int(raw))
    else:
        name = raw if raw.startswith("@") else "@" + raw
        candidates.append(name)

    last_error: Exception | None = None
    for candidate in candidates:
        try:
            data = tg.call("getChat", {"chat_id": candidate}, timeout=20)
            if data:
                return chat_payload(data)
        except TelegramError as exc:
            last_error = exc
            log.info("getChat(%s): %s", candidate, exc)

    if known_users:
        needle = raw.lstrip("@").lower()
        numeric = int(raw) if raw.lstrip("-").isdigit() else None
        for user in known_users:
            if numeric is not None and int(user.get("id") or 0) == numeric:
                return {
                    "id": numeric,
                    "type": "private",
                    "username": user.get("username"),
                    "first_name": user.get("name"),
                    "last_name": None,
                }
            username = (user.get("username") or "").lower()
            if username and username == needle:
                return {
                    "id": int(user["id"]),
                    "type": "private",
                    "username": user.get("username"),
                    "first_name": user.get("name"),
                    "last_name": None,
                }

    raise ValueError(
        f"Пользователь не найден ({last_error or 'нет такого username/ID'}). "
        "Он должен хотя бы раз написать боту /start."
    )


def _best_photo(sizes: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not sizes:
        return None
    return max(sizes, key=lambda item: int(item.get("width", 0)) * int(item.get("height", 0)))


def download_avatar(tg: Telegram, user_id: int, dest_dir: Path) -> Path | None:
    """Скачать актуальный аватар пользователя (если Telegram его отдаёт)."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{int(user_id)}.jpg"
    try:
        photos = tg.call(
            "getUserProfilePhotos", {"user_id": int(user_id), "limit": 1}, timeout=20
        )
    except TelegramError as exc:
        log.info("Аватар %s недоступен: %s", user_id, exc)
        return None

    rows = (photos or {}).get("photos") or []
    if not rows:
        return None
    best = _best_photo(rows[0])
    if not best:
        return None
    try:
        info = tg.get_file(best["file_id"])
        tg.download(info["file_path"], dest, limit=15 * 1024 * 1024)
    except (TelegramError, OSError) as exc:
        log.warning("Не удалось скачать аватар %s: %s", user_id, exc)
        return None
    return dest if dest.is_file() else None
