"""Преобразование объектов Telegram Bot API в записи хранилища."""

from __future__ import annotations

from i18n import tr

from typing import Any


def _best_photo(sizes: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not sizes:
        return None
    # самые крупные размеры обычно в конце; берём максимальный по площади
    return max(sizes, key=lambda s: (s.get("width", 0) * s.get("height", 0)))


def _media_for(data: dict[str, Any], kind: str) -> dict[str, Any] | None:
    media: dict[str, Any] = {"file_id": data.get("file_id")}

    for key in ("file_name", "mime_type", "file_size", "duration", "width", "height",
                "performer", "title", "emoji"):
        if key in data and data[key] is not None:
            media[key] = data[key]

    if kind == "sticker":
        media["animated"] = bool(data.get("is_animated"))
        media["video"] = bool(data.get("is_video"))
        media["thumbnail"] = data.get("thumbnail", {}).get("file_id") if data.get("thumbnail") else None

    if kind in ("video", "animation", "video_note", "video"):
        thumb = data.get("thumbnail") or data.get("thumb")
        if thumb:
            media["thumb_file_id"] = thumb.get("file_id")

    return media


def _forward_info(message: dict[str, Any]) -> dict[str, Any] | None:
    """Информация о пересылке: «Переслано от …» / «из канала …»."""
    origin = message.get("forward_origin")
    if isinstance(origin, dict):
        kind = origin.get("type")
        if kind == "user":
            user = origin.get("user") or {}
            name = " ".join(
                part for part in (user.get("first_name"), user.get("last_name")) if part
            ).strip()
            return {
                "type": "user",
                "name": name or user.get("username") or tr('backend.127'),
                "username": user.get("username"),
                "id": user.get("id"),
            }
        if kind == "hidden_user":
            return {
                "type": "hidden_user",
                "name": origin.get("sender_user_name") or tr('backend.127'),
            }
        if kind in ("chat", "channel"):
            chat = origin.get("chat") or {}
            return {
                "type": kind,
                "name": chat.get("title") or tr('backend.128'),
                "username": chat.get("username"),
                "id": chat.get("id"),
                "message_id": origin.get("message_id"),
            }

    # старый формат (для совместимости)
    if message.get("forward_from"):
        user = message["forward_from"]
        name = " ".join(
            part for part in (user.get("first_name"), user.get("last_name")) if part
        ).strip()
        return {
            "type": "user",
            "name": name or user.get("username") or tr('backend.127'),
            "username": user.get("username"),
            "id": user.get("id"),
        }
    if message.get("forward_from_chat"):
        chat = message["forward_from_chat"]
        return {
            "type": "channel" if chat.get("type") == "channel" else "chat",
            "name": chat.get("title") or tr('backend.128'),
            "username": chat.get("username"),
            "id": chat.get("id"),
        }
    if message.get("forward_sender_name"):
        return {"type": "hidden_user", "name": message["forward_sender_name"]}
    if message.get("forward_date"):
        return {"type": "hidden_user", "name": tr('backend.127')}
    return None


def normalize(message: dict[str, Any]) -> dict[str, Any] | None:
    """Вернуть запись сообщения или None, если тип не поддержан."""
    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    msg_id = message.get("message_id")
    if chat_id is None or msg_id is None:
        return None

    date = int(message.get("date") or 0)
    text = message.get("text") or ""
    caption = message.get("caption") or ""

    kind = "text"
    media: dict[str, Any] | None = None

    if message.get("photo"):
        kind = "photo"
        media = _media_for(_best_photo(message["photo"]) or {}, kind)
        if media:
            media["thumb_file_id"] = media.get("file_id")
    elif message.get("video"):
        kind = "video"
        media = _media_for(message["video"], kind)
    elif message.get("animation"):
        kind = "animation"
        media = _media_for(message["animation"], kind)
    elif message.get("video_note"):
        kind = "video_note"
        media = _media_for(message["video_note"], kind)
    elif message.get("voice"):
        kind = "voice"
        media = _media_for(message["voice"], kind)
    elif message.get("audio"):
        kind = "audio"
        media = _media_for(message["audio"], kind)
    elif message.get("sticker"):
        kind = "sticker"
        media = _media_for(message["sticker"], kind)
    elif message.get("document"):
        kind = "document"
        media = _media_for(message["document"], kind)
        if media:
            mime = (media.get("mime_type") or "").lower()
            media["is_image"] = mime.startswith("image/")
    elif message.get("location"):
        kind = "location"
        loc = message["location"]
        media = {"lat": loc.get("latitude"), "lon": loc.get("longitude")}
    elif message.get("contact"):
        kind = "contact"
        c = message["contact"]
        media = {
            "first_name": c.get("first_name"),
            "last_name": c.get("last_name"),
            "phone": c.get("phone_number"),
            "user_id": c.get("user_id"),
        }
    elif message.get("poll"):
        kind = "poll"
        p = message["poll"]
        media = {"question": p.get("question"), "options": [o.get("text") for o in p.get("options", [])]}
    elif message.get("dice"):
        kind = "dice"
        d = message["dice"]
        media = {"emoji": d.get("emoji"), "value": d.get("value")}
    else:
        # служебные сообщения (вход в чат, закрепление и т.п.)
        if not text:
            return None

    if media is not None and message.get("media_group_id"):
        media["group"] = str(message["media_group_id"])

    return {
        "id": int(msg_id),
        "chat_id": int(chat_id),
        "direction": "in",
        "date": date,
        "text": text,
        "caption": caption,
        "kind": kind,
        "media": media,
        "fwd": _forward_info(message),
        "status": "ok",
        "error": None,
        "edited": 0,
    }

