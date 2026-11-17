"""Минимальный синхронный клиент Telegram Bot API (без сторонних SDK)."""

from __future__ import annotations

import logging
import mimetypes
import os
import time
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote

import requests

log = logging.getLogger(__name__)

API_ROOT = "https://api.telegram.org"

#: Лимиты Bot API, о которых стоит помнить
BOT_DOWNLOAD_LIMIT = 20 * 1024 * 1024
BOT_UPLOAD_LIMIT = 50 * 1024 * 1024


class TelegramError(Exception):
    def __init__(self, description: str, code: int | None = None,
                 retry_after: int | None = None) -> None:
        super().__init__(description)
        self.description = description
        self.code = code
        self.retry_after = retry_after

    def human(self) -> str:
        """Понятный пользователю текст ошибки."""
        text = self.description
        low = text.lower()
        if "chat not found" in low:
            return "Чат не найден: сначала напишите боту в Telegram (кнопка Start)."
        if "bot was blocked" in low or "user is deactivated" in low:
            return "Бот заблокирован пользователем в Telegram."
        if "bot can't initiate conversation" in low:
            return "Бот не может начать диалог первым — напишите ему /start в Telegram."
        if "too big" in low:
            return "Файл слишком большой для Bot API (документы — до 50 МБ, видео — до 50 МБ, фото — до 10 МБ)."
        if "invalid file" in low or "wrong file" in low:
            return "Telegram не принял файл (неподдерживаемый формат или повреждён)."
        if "unauthorized" in low:
            return "Неверный токен бота в config.json."
        if self.code == 429:
            return f"Telegram ограничил частоту запросов, подождите {self.retry_after or 5} с."
        return text


class Telegram:
    def __init__(self, token: str, api_base: str = API_ROOT, files_base: str = "") -> None:
        self.token = token.strip()
        self.api_base = (api_base or API_ROOT).rstrip("/")
        self.files_base = (files_base or "").rstrip("/")
        self._session = requests.Session()
        self._session.headers["User-Agent"] = "TgDeskChat/1.0 (+pywebview)"

    # ---------------------------------------------------------------- core
    def _url(self, method: str) -> str:
        return f"{self.api_base}/bot{self.token}/{method}"

    def call(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        files: dict[str, Any] | None = None,
        timeout: float = 45,
        retries: int = 1,
    ) -> Any:
        attempt = 0
        while True:
            try:
                resp = self._session.post(
                    self._url(method), data=params or {}, files=files, timeout=timeout
                )
            except requests.RequestException as exc:
                if attempt >= retries:
                    raise TelegramError(f"Нет связи с Telegram: {exc}") from exc
                attempt += 1
                time.sleep(1.5 * attempt)
                continue

            try:
                payload = resp.json()
            except ValueError:
                raise TelegramError(f"Telegram вернул не JSON (HTTP {resp.status_code})")

            if payload.get("ok"):
                return payload.get("result")

            desc = payload.get("description") or f"HTTP {resp.status_code}"
            retry_after = (payload.get("parameters") or {}).get("retry_after")
            if retry_after and attempt < 1:
                attempt += 1
                time.sleep(min(int(retry_after), 30))
                continue
            raise TelegramError(desc, payload.get("error_code"), retry_after)

    # ------------------------------------------------------------- методы
    def get_me(self) -> dict[str, Any]:
        return self.call("getMe", timeout=20)

    def get_updates(self, offset: int, timeout: int = 25) -> list[dict[str, Any]]:
        return self.call(
            "getUpdates",
            {
                "offset": offset,
                "timeout": timeout,
                "allowed_updates": '["message","edited_message"]',
            },
            timeout=timeout + 20,
        ) or []

    def send_message(self, chat_id: int, text: str, preview: bool = True,
                     parse_mode: str | None = "HTML") -> dict[str, Any]:
        params: dict[str, Any] = {
            "chat_id": chat_id,
            "text": text,
            "disable_web_page_preview": "false" if preview else "true",
        }
        if parse_mode:
            params["parse_mode"] = parse_mode
        return self.call("sendMessage", params)

    def send_typing(self, chat_id: int, action: str = "typing") -> None:
        try:
            self.call("sendChatAction", {"chat_id": chat_id, "action": action}, timeout=15)
        except TelegramError:
            pass  # индикатор набора — не критичная вещь

    def get_file(self, file_id: str) -> dict[str, Any]:
        return self.call("getFile", {"file_id": file_id}, timeout=30)

    def download(self, file_path: str, dest: Path, limit: int | None = None,
                 on_progress: Callable[[int, int], None] | None = None) -> int:
        if file_path.startswith("/"):
            # Локальный Bot API отдаёт абсолютный путь внутри своего контейнера.
            if not self.files_base:
                raise TelegramError(
                    "Локальный Bot API: задайте api_files_base (HTTP-доступ к папке с файлами)"
                )
            marker = "/var/lib/telegram-bot-api/"
            rel = file_path[len(marker):] if file_path.startswith(marker) else file_path.lstrip("/")
            url = f"{self.files_base}/{quote(rel, safe='/:')}"
        else:
            url = f"{self.api_base}/file/bot{self.token}/{file_path}"
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(dest.suffix + ".part")
        written = 0
        with self._session.get(url, stream=True, timeout=120) as resp:
            if resp.status_code != 200:
                raise TelegramError(f"Не удалось скачать файл (HTTP {resp.status_code})")
            total = int(resp.headers.get("Content-Length") or 0)
            with open(tmp, "wb") as fh:
                for chunk in resp.iter_content(chunk_size=128 * 1024):
                    if not chunk:
                        continue
                    written += len(chunk)
                    if limit and written > limit:
                        fh.close()
                        tmp.unlink(missing_ok=True)
                        raise TelegramError(
                            f"Файл больше лимита скачивания ({limit / 1024 / 1024:.0f} МБ)"
                        )
                    fh.write(chunk)
                    if on_progress:
                        on_progress(written, total)
        os.replace(tmp, dest)
        return written

    # ------------------------------------------------------------ отправка
    def send_upload(self, chat_id: int, path: Path, kind: str,
                    caption: str = "") -> dict[str, Any]:
        """Отправить файл, подобрав подходящий метод Bot API."""
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        field, method = _method_for(kind, path)
        base: dict[str, Any] = {"chat_id": chat_id}
        if caption:
            base["caption"] = caption
            base["parse_mode"] = "HTML"

        def attempt(field_name: str, method_name: str) -> dict[str, Any]:
            with open(path, "rb") as fh:
                files = {field_name: (path.name, fh, mime)}
                data = dict(base)
                if method_name in ("sendVideo", "sendAnimation"):
                    data["supports_streaming"] = "true"
                if method_name == "sendAudio":
                    data["title"] = path.stem[:64]
                return self.call(method_name, data, files=files, timeout=300)

        try:
            return attempt(field, method)
        except TelegramError as exc:
            low = exc.description.lower()
            retry_as_document = (
                method != "sendDocument"
                and exc.code in (400, 415)
                and any(word in low for word in ("wrong", "invalid", "unsupported", "webpage", "type"))
            )
            if not retry_as_document:
                raise
            log.warning("Не удалось отправить как %s, отправляю документом: %s", method, exc)
            return attempt("document", "sendDocument")


def _method_for(kind: str, path: Path) -> tuple[str, str]:
    ext = path.suffix.lower()
    if kind == "photo" or ext in {".jpg", ".jpeg", ".png", ".webp"}:
        return "photo", "sendPhoto"
    if kind == "animation" or ext == ".gif":
        return "animation", "sendAnimation"
    if kind == "video" or ext in {".mp4", ".mov", ".m4v", ".webm", ".mkv", ".avi"}:
        return "video", "sendVideo"
    if ext in {".ogg", ".oga", ".opus"}:
        return "voice", "sendVoice"
    if kind == "audio" or ext in {".mp3", ".m4a", ".aac", ".flac", ".wav"}:
        return "audio", "sendAudio"
    return "document", "sendDocument"
