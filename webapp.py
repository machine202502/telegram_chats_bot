"""Ядро мультичатового Telegram-приложения (Docker-first, без GUI-обвязки)."""

from __future__ import annotations

from i18n import tr

import hashlib
import json
import logging
import mimetypes
import os
import queue
import threading
import time
import uuid
from pathlib import Path
from typing import Any

import requests

import audio
import md2tg
import profiles
import tgmessages
from store import Store
from tgclient import Telegram, TelegramError

log = logging.getLogger(__name__)

KIND_LABELS = {
    "photo": tr('backend.60'),
    "video": tr('backend.61'),
    "animation": "GIF",
    "video_note": tr('backend.62'),
    "voice": tr('backend.63'),
    "audio": tr('backend.64'),
    "sticker": tr('backend.65'),
    "document": tr('backend.66'),
    "location": tr('backend.67'),
    "contact": tr('backend.68'),
}

LOCAL_STORAGE_MARKER = "/var/lib/telegram-bot-api/"


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on", tr('backend.69')}


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _outgoing_kind(path: Path, mime: str) -> str:
    ext = path.suffix.lower()
    if ext in {".jpg", ".jpeg", ".png", ".webp"} or mime in {"image/jpeg", "image/png", "image/webp"}:
        return "photo"
    if ext == ".gif" or mime == "image/gif":
        return "animation"
    if ext in {".mp4", ".mov", ".m4v", ".webm", ".mkv", ".avi"} or mime.startswith("video/"):
        return "video"
    if ext in {".ogg", ".oga", ".opus"}:
        return "voice"
    if ext in {".mp3", ".m4a", ".aac", ".flac", ".wav"} or mime.startswith("audio/"):
        return "audio"
    return "document"


def _safe_filename(name: str, limit: int = 80) -> str:
    import re

    clean = re.sub(r"[^\w.\- ()\[\]]+", "_", os.path.basename(name or "file"), flags=re.UNICODE)
    return (clean.strip(" .") or "file")[:limit]


class WebApp:
    def __init__(self, config: dict[str, Any], data_dir: Path, models_dir: Path) -> None:
        self.config = config
        self.data_dir = data_dir
        self.models_dir = models_dir
        self.media_dir = data_dir / "media"
        self.avatars_dir = data_dir / "avatars"
        self.uploads_dir = data_dir / "uploads"
        for directory in (self.data_dir, self.models_dir, self.media_dir,
                          self.avatars_dir, self.uploads_dir):
            directory.mkdir(parents=True, exist_ok=True)

        self.store = Store(data_dir / "messages.db")
        self.tg = Telegram(
            str(config["bot_token"]),
            str(config.get("api_base") or "https://api.telegram.org"),
            str(config.get("api_files_base") or ""),
        )

        previous_base = self.store.meta_get("api_base")
        if previous_base and previous_base != self.tg.api_base:
            self.store.meta_set("offset", "0")
            log.warning(tr('backend.70'),
                        previous_base, self.tg.api_base)
        self.store.meta_set("api_base", self.tg.api_base)

        self.local_api = "api.telegram.org" not in self.tg.api_base
        default_download = 1900 if self.local_api else 19
        default_upload = 1900 if self.local_api else 50
        self.download_limit = _env_int("DOWNLOAD_LIMIT_MB", default_download) * 1024 * 1024
        self.upload_limit = _env_int("UPLOAD_LIMIT_MB", default_upload) * 1024 * 1024
        self.config["max_upload_mb"] = max(1, self.upload_limit // 1024 // 1024)

        self.bot_info: dict[str, Any] | None = None
        self.connection = "connecting"
        self.last_error: str | None = None
        self.chat_ready = False

        self._stop = threading.Event()
        self._downloads: queue.Queue[dict[str, Any] | None] = queue.Queue()
        self._transcribe: queue.Queue[int | None] = queue.Queue()
        self._transcribe_ids: set[int] = set()
        self._locks_guard = threading.Lock()
        self._avatar_locks: dict[int, threading.Lock] = {}
        self._asr = None
        self._asr_lock = threading.Lock()
        self._agent_server = None
        self._agent_info: dict[str, Any] = {}
        self._poll_thread: threading.Thread | None = None
        self._download_thread: threading.Thread | None = None
        self._transcribe_thread: threading.Thread | None = None

        self._init_settings()
        self._bootstrap_allowed()
        try:
            self.store.backfill_chat_last()
        except Exception:
            log.exception(tr('backend.71'))

    # ------------------------------------------------------------- настройки
    def _init_settings(self) -> None:
        defaults = {
            "theme": os.environ.get("THEME", "dark"),
            "asr_enabled": "1" if _env_bool("ASR_ENABLED", True) else "0",
            "auto_transcribe": "1" if _env_bool("AUTO_TRANSCRIBE", True) else "0",
            "asr_model": os.environ.get("ASR_MODEL", "gigaam-v3-rnnt-punct"),
            "auto_approve": "1" if _env_bool("AUTO_APPROVE", False) else "0",
        }
        for key, value in defaults.items():
            if self.store.meta_get("setting:" + key) is None:
                self.store.meta_set("setting:" + key, value)

    def settings(self) -> dict[str, Any]:
        def flag(key: str, default: bool = False) -> bool:
            value = self.store.meta_get("setting:" + key)
            return default if value is None else value == "1"

        theme = self.store.meta_get("setting:theme", "dark")
        return {
            "theme": "light" if theme == "light" else "dark",
            "asr_enabled": flag("asr_enabled", True),
            "auto_transcribe": flag("auto_transcribe", True),
            "auto_approve": flag("auto_approve", False),
            "asr_model": self.store.meta_get("setting:asr_model", "gigaam-v3-rnnt-punct") or "",
            "api_base": self.tg.api_base,
            "local_api": self.local_api,
            "limits": {
                "download_mb": round(self.download_limit / 1024 / 1024, 1),
                "upload_mb": round(self.upload_limit / 1024 / 1024),
            },
        }

    def update_settings(self, data: dict[str, Any]) -> dict[str, Any]:
        if "theme" in data:
            self.store.meta_set("setting:theme", "light" if str(data["theme"]) == "light" else "dark")
        for key in ("asr_enabled", "auto_transcribe", "auto_approve"):
            if key in data:
                self.store.meta_set("setting:" + key, "1" if data[key] else "0")
        if "asr_model" in data:
            model = str(data["asr_model"] or "")
            self.store.meta_set("setting:asr_model", model)
            engine = self.asr_engine()
            if engine is not None and hasattr(engine, "unload"):
                try:
                    engine.unload()
                except Exception:
                    pass
        if data.get("asr_enabled") is False and self._asr is not None:
            try:
                self._asr.unload()
            except Exception:
                pass
            self._asr = None
        return self.settings()

    # ------------------------------------------------------------------- ASR
    def asr_engine(self):
        if not self.settings()["asr_enabled"]:
            return None
        with self._asr_lock:
            if self._asr is None:
                try:
                    import asr_engine as module

                    cls = getattr(module, "AsrEngine", None) or getattr(module, "AsrManager")
                    self._asr = cls(self.models_dir)
                except Exception as exc:
                    log.exception(tr('backend.72'), exc)
                    return None
            return self._asr

    def asr_models(self) -> dict[str, Any]:
        engine = self.asr_engine()
        if engine is None:
            return {"enabled": False, "models": [], "error": tr('backend.73')}
        try:
            models = engine.list_models()
        except Exception as exc:
            return {"enabled": True, "models": [], "error": str(exc)}
        return {"enabled": True, "models": models, "selected": self.settings()["asr_model"]}

    def download_model(self, model_id: str) -> None:
        engine = self.asr_engine()
        if engine is None:
            raise ValueError(tr('backend.73'))
        engine.download(model_id)

    # --------------------------------------------------------------- запуск
    def run(self, web_port: int, agent_port: int | None = None) -> None:
        self._download_thread = threading.Thread(target=self._download_worker, name="downloads", daemon=True)
        self._download_thread.start()
        self._transcribe_thread = threading.Thread(target=self._transcribe_worker, name="transcribe", daemon=True)
        self._transcribe_thread.start()
        self._poll_thread = threading.Thread(target=self._poll_loop, name="telegram", daemon=True)
        self._poll_thread.start()

        from web_server import create_servers

        create_servers(self, web_port, agent_port)
        log.info(tr('backend.74'), web_port)
        if agent_port:
            log.info(tr('backend.75'), agent_port)
        try:
            while not self._stop.is_set():
                time.sleep(0.5)
        except KeyboardInterrupt:
            pass
        finally:
            self._stop.set()
            self._downloads.put(None)
            self._transcribe.put(None)

    def stop(self) -> None:
        self._stop.set()

    # -------------------------------------------------------------- состояние
    def default_chat_id(self) -> int | None:
        chats = self.store.list_chats(allowed_only=True)
        return int(chats[0]["id"]) if chats else None

    def state(self) -> dict[str, Any]:
        asr = self.asr_models()
        return {
            "bot": self.bot_info,
            "connection": self.connection,
            "error": self.last_error,
            "api_base": self.tg.api_base,
            "local_api": self.local_api,
            "limits": {
                "download_mb": round(self.download_limit / 1024 / 1024, 1),
                "upload_mb": round(self.upload_limit / 1024 / 1024),
            },
            "chats": len(self.store.list_chats(allowed_only=True)),
            "asr": {
                "enabled": asr.get("enabled", False),
                "selected": asr.get("selected", ""),
                "error": asr.get("error"),
            },
            "agent_api": {"enabled": bool(self._agent_server), **self._agent_info},
        }

    # --------------------------------------------------------------- Telegram
    def _load_me(self) -> None:
        try:
            me = self.tg.get_me()
            self.bot_info = {
                "id": me.get("id"),
                "username": me.get("username"),
                "name": me.get("first_name") or me.get("username"),
            }
            self.chat_ready = True
            log.info(tr('backend.76'), me.get("username"))
        except TelegramError as exc:
            self.last_error = exc.human()
            log.warning("getMe: %s", exc)

    def _poll_loop(self) -> None:
        offset = int(self.store.meta_get("offset", "0") or 0)
        delay = 1.0
        if self.bot_info is None:
            self._load_me()
        while not self._stop.is_set():
            try:
                updates = self.tg.get_updates(offset, timeout=25)
                self.connection = "online"
                self.last_error = None
                for update in updates:
                    offset = int(update["update_id"]) + 1
                    try:
                        self.handle_update(update)
                    except Exception:
                        log.exception(tr('backend.77'))
                    self.store.meta_set("offset", offset)
                delay = 1.0
            except TelegramError as exc:
                self.connection = "offline"
                self.last_error = exc.human()
                log.warning("Telegram: %s", exc)
                self._stop.wait(delay)
                delay = min(delay * 2, 30)
            except requests.RequestException as exc:
                self.connection = "offline"
                self.last_error = tr('backend.78')
                log.warning(tr('backend.79'), exc)
                self._stop.wait(delay)
                delay = min(delay * 2, 30)

    def handle_update(self, update: dict[str, Any]) -> None:
        edited = "edited_message" in update
        message = update.get("message") or update.get("edited_message")
        if not message:
            return
        chat = message.get("chat") or {}
        if chat.get("type") != "private":
            return
        chat_id = int(chat.get("id") or 0)
        sender = message.get("from") or {}
        user_id = int(sender.get("id") or chat_id or 0)
        if not chat_id or not user_id:
            return

        text = message.get("text") or ""
        start_seen = text.strip().lower().startswith("/start")
        self.store.upsert_known_user(
            user_id,
            username=sender.get("username"),
            first_name=sender.get("first_name"),
            last_name=sender.get("last_name"),
            last_seen=int(message.get("date") or time.time()),
            start_seen=start_seen,
        )
        existing = self.store.get_chat(chat_id)
        self.store.upsert_chat(
            chat_id,
            title=chat.get("title"),
            username=chat.get("username") or sender.get("username"),
            first_name=chat.get("first_name") or sender.get("first_name"),
            last_name=chat.get("last_name") or sender.get("last_name"),
        )

        allowed = bool(existing and existing.get("allowed"))
        if start_seen and not allowed and self.settings()["auto_approve"]:
            self.store.set_chat_allowed(chat_id, True)
            allowed = True
            log.info(tr('backend.80'), user_id)
            threading.Thread(target=self.ensure_avatar, args=(user_id,), daemon=True).start()

        if not allowed:
            return

        record = tgmessages.normalize(message)
        if not record:
            return
        record["chat_id"] = chat_id
        if edited:
            stored = self.store.get(record["id"], chat_id)
            if stored:
                self.store.patch(record["id"], chat_id, text=record["text"],
                                 caption=record["caption"], edited=1)
                return
        record["edited"] = 0
        record = self.store.upsert(record)
        preview = (record.get("text") or record.get("caption")
                   or KIND_LABELS.get(record.get("kind"), tr('backend.81')))
        self.store.update_chat_last(chat_id, record["date"], preview)
        self.ensure_avatar_async(user_id)
        self.maybe_auto_transcribe(record)
        self.notify(record)

    def notify(self, record: dict[str, Any]) -> None:
        # В web-версии уведомления только внутри интерфейса; здесь заглушка.
        return

    # ------------------------------------------------------------- пользователи
    def _bootstrap_allowed(self) -> None:
        raw = os.environ.get("ALLOWED_USER_IDS", "").strip()
        if not raw:
            return
        for chunk in raw.split(","):
            chunk = chunk.strip()
            if not chunk.lstrip("-").isdigit():
                continue
            chat_id = int(chunk)
            self.store.upsert_chat(chat_id, allowed=True)
            threading.Thread(target=self.sync_chat_info, args=(chat_id,), daemon=True).start()

    def sync_chat_info(self, chat_id: int) -> dict[str, Any] | None:
        try:
            info = profiles.chat_payload(self.tg.call("getChat", {"chat_id": chat_id}, timeout=20))
        except TelegramError:
            return self.store.get_chat(chat_id)
        self.store.upsert_chat(
            chat_id,
            title=info.get("title"),
            username=info.get("username"),
            first_name=info.get("first_name"),
            last_name=info.get("last_name"),
        )
        self.ensure_avatar(chat_id)
        return self.store.get_chat(chat_id)

    def add_chat(self, user_id: int | None = None, username: str | None = None) -> dict[str, Any]:
        query = str(user_id) if user_id else (username or "")
        info = profiles.resolve_chat(self.tg, query, self.store.list_known_users())
        chat_id = int(info["id"])
        self.store.upsert_chat(
            chat_id,
            title=info.get("title"),
            username=info.get("username"),
            first_name=info.get("first_name"),
            last_name=info.get("last_name"),
            allowed=True,
        )
        self.store.upsert_known_user(
            chat_id,
            username=info.get("username"),
            first_name=info.get("first_name"),
            last_name=info.get("last_name"),
            last_seen=int(time.time()),
        )
        threading.Thread(target=self.ensure_avatar, args=(chat_id,), daemon=True).start()
        return self.store.get_chat(chat_id) or {}

    def remove_chat(self, chat_id: int) -> None:
        self.store.set_chat_allowed(chat_id, False)

    def delete_chat(self, chat_id: int) -> None:
        self.store.delete_chat(chat_id)

    def known_users(self, query: str = "") -> list[dict[str, Any]]:
        users = self.store.list_known_users(query)
        for user in users:
            chat = self.store.get_chat(user["id"])
            user["allowed"] = bool(chat and chat.get("allowed"))
        return users

    # ------------------------------------------------------------------ аватары
    def avatar_file(self, user_id: int) -> Path | None:
        path = self.avatars_dir / f"{int(user_id)}.jpg"
        if path.is_file() and path.stat().st_size > 0:
            return path
        return self.ensure_avatar(user_id)

    def ensure_avatar_async(self, user_id: int) -> None:
        threading.Thread(target=self.ensure_avatar, args=(user_id,), daemon=True).start()

    def ensure_avatar(self, user_id: int) -> Path | None:
        path = self.avatars_dir / f"{int(user_id)}.jpg"
        if path.is_file() and path.stat().st_size > 0:
            return path
        with self._locks_guard:
            lock = self._avatar_locks.setdefault(int(user_id), threading.Lock())
        if not lock.acquire(blocking=False):
            return path if path.is_file() else None
        try:
            result = profiles.download_avatar(self.tg, int(user_id), self.avatars_dir)
            if result:
                self.store.set_chat_photo(int(user_id), str(result))
            return result
        finally:
            lock.release()

    # ------------------------------------------------------------------ медиа
    def ensure_media(self, msg_id: int) -> bool:
        row = self.store.get_raw(msg_id)
        if row is None:
            return False
        if row["local_path"] and Path(row["local_path"]).is_file():
            return True
        if row["local_path"]:
            # Путь остался от старой версии/удалённого файла — сбрасываем его,
            # чтобы UI не показывал вечно сломанную картинку.
            self.store.patch(msg_id, int(row["chat_id"]), local_path=None, error=None)
        if not row["media"]:
            return False
        try:
            media = json.loads(row["media"])
        except (TypeError, ValueError):
            return False
        file_id = media.get("file_id")
        if not file_id:
            self.store.patch(msg_id, int(row["chat_id"]), error=tr('backend.82'))
            return False
        self._downloads.put({
            "msg_id": int(msg_id),
            "chat_id": int(row["chat_id"]),
            "file_id": file_id,
            "kind": row["kind"],
            "size": int(media.get("file_size") or 0),
            "name": _safe_filename(media.get("file_name") or ""),
        })
        return True

    def retry_media(self, msg_id: int) -> dict[str, Any] | None:
        row = self.store.get_raw(msg_id)
        if row is None:
            return None
        if row["local_path"] and Path(row["local_path"]).is_file():
            return self.store.get(msg_id, int(row["chat_id"]))
        self.store.patch(msg_id, int(row["chat_id"]), error=None, status="ok")
        self.ensure_media(msg_id)
        return self.store.get(msg_id, int(row["chat_id"]))

    def media_path(self, msg_id: int) -> Path | None:
        row = self.store.get_raw(msg_id)
        if row is None or not row["local_path"]:
            return None
        path = Path(row["local_path"])
        return path if path.is_file() else None

    def _download_worker(self) -> None:
        while not self._stop.is_set():
            job = self._downloads.get()
            if job is None:
                break
            try:
                self._download_one(job)
            except Exception:
                log.exception(tr('backend.83'))

    def _download_one(self, job: dict[str, Any]) -> None:
        msg_id = int(job["msg_id"])
        chat_id = int(job.get("chat_id") or 0)
        row = self.store.get_raw(msg_id)
        if row is None:
            return
        if row["local_path"] and Path(row["local_path"]).is_file():
            return
        if row["local_path"]:
            self.store.patch(msg_id, chat_id, local_path=None)
        log.info(tr('backend.84'), msg_id, job.get("kind"), job.get("size"))
        try:
            info = self.tg.get_file(job["file_id"])
        except TelegramError as exc:
            log.warning("getFile %s: %s", msg_id, exc.human())
            self.store.patch(msg_id, chat_id, error=exc.human())
            return
        path = info.get("file_path") or ""
        size = int(info.get("file_size") or job.get("size") or 0)
        if size and size > self.download_limit:
            self.store.patch(
                msg_id, chat_id,
                error=f"Файл {size / 1024 / 1024:.1f} МБ больше лимита "
                      f"{self.download_limit / 1024 / 1024:.0f} МБ",
            )
            return
        ext = Path(path).suffix.lower() or Path(job.get("name") or "").suffix.lower()
        digest = hashlib.md5(str(job["file_id"]).encode("utf-8")).hexdigest()[:8]
        stem = Path(job.get("name") or str(msg_id)).stem[:40] or str(msg_id)
        dest = self.media_dir / f"{msg_id}-{stem}-{digest}{ext[:10]}"
        try:
            self.tg.download(path, dest, limit=self.download_limit)
        except (TelegramError, OSError) as exc:
            log.warning("download %s: %s", msg_id, exc)
            self.store.patch(msg_id, chat_id, error=str(exc))
            return

        if job.get("kind") == "voice" and ext not in {".mp3"}:
            converted = audio.convert_to_mp3(dest)
            if converted is not None and converted != dest:
                try:
                    dest.unlink(missing_ok=True)
                except OSError:
                    pass
                dest = converted
                media = json.loads(row["media"]) if row["media"] else {}
                media["file_name"] = dest.name
                media["mime_type"] = "audio/mpeg"
                self.store.patch(msg_id, chat_id, media=media)

        self.store.patch(msg_id, chat_id, local_path=str(dest), error=None)
        log.info(tr('backend.85'), msg_id, dest.name)
        self.store.update_chat_last(chat_id, int(row["date"]),
                                    KIND_LABELS.get(row["kind"], tr('backend.86')))
        updated = self.store.get_raw(msg_id)
        if updated and self.settings()["auto_transcribe"] and updated["direction"] == "in" \
                and updated["kind"] in ("voice", "audio") and not updated["transcript"]:
            self.enqueue_transcription(msg_id)

    # ------------------------------------------------------------- расшифровка
    def maybe_auto_transcribe(self, record: dict[str, Any]) -> None:
        if not self.settings()["asr_enabled"] or not self.settings()["auto_transcribe"]:
            return
        if record.get("direction") != "in" or record.get("kind") not in ("voice", "audio"):
            return
        msg_id = int(record["id"])
        row = self.store.get_raw(msg_id)
        if row is None or row["transcript"]:
            return
        if row["local_path"] and Path(row["local_path"]).is_file():
            self.enqueue_transcription(msg_id)
        else:
            self.ensure_media(msg_id)

    def enqueue_transcription(self, msg_id: int) -> dict[str, Any] | None:
        if not self.settings()["asr_enabled"]:
            return None
        row = self.store.get_raw(msg_id)
        if row is None:
            return None
        chat_id = int(row["chat_id"])
        if row["kind"] not in ("voice", "audio"):
            return self.store.get(msg_id, chat_id)
        if row["transcript"]:
            if row["transcript_state"] != "done":
                self.store.patch(msg_id, chat_id, transcript_state="done", transcript_error=None)
            return self.store.get(msg_id, chat_id)
        if not row["local_path"] or not Path(row["local_path"]).is_file():
            return self.store.get(msg_id, chat_id)
        with self._locks_guard:
            if msg_id in self._transcribe_ids:
                return self.store.get(msg_id, chat_id)
            self._transcribe_ids.add(msg_id)
        self.store.patch(msg_id, chat_id, transcript_state="queued", transcript_error=None)
        self._transcribe.put(msg_id)
        return self.store.get(msg_id, chat_id)

    def _transcribe_worker(self) -> None:
        while not self._stop.is_set():
            msg_id = self._transcribe.get()
            if msg_id is None:
                break
            try:
                self._run_transcription(msg_id)
            except Exception as exc:
                log.exception(tr('backend.87'))
                row = self.store.get_raw(msg_id)
                if row:
                    self.store.patch(msg_id, int(row["chat_id"]), transcript_state="error",
                                     transcript_error=str(exc))
            finally:
                with self._locks_guard:
                    self._transcribe_ids.discard(msg_id)

    def _run_transcription(self, msg_id: int) -> None:
        row = self.store.get_raw(msg_id)
        if row is None:
            return
        chat_id = int(row["chat_id"])
        path = self.media_path(msg_id)
        if path is None:
            self.store.patch(msg_id, chat_id, transcript_state="error",
                             transcript_error=tr('backend.88'))
            return
        engine = self.asr_engine()
        if engine is None:
            self.store.patch(msg_id, chat_id, transcript_state="error",
                             transcript_error=tr('backend.89'))
            return
        self.store.patch(msg_id, chat_id, transcript_state="running", transcript_error=None)
        model = self.settings()["asr_model"] or None
        try:
            text = engine.transcribe(path, model)
        except Exception as exc:
            self.store.patch(msg_id, chat_id, transcript_state="error", transcript_error=str(exc))
            return
        finally:
            try:
                if hasattr(engine, "unload"):
                    engine.unload()
            except Exception:
                pass
        if not text:
            self.store.patch(msg_id, chat_id, transcript_state="error",
                             transcript_error=tr('backend.90'))
            return
        self.store.patch(msg_id, chat_id, transcript=text, transcript_state="done",
                         transcript_error=None)

    # ---------------------------------------------------------------- отправка
    def send_text(self, chat_id: int, text: str, plain: bool = False) -> tuple[list[dict[str, Any]], str | None]:
        chunks = [text[i:i + 3800] for i in range(0, len(text), 3800)] if plain else md2tg.split_markdown(text)
        sent: list[dict[str, Any]] = []
        for chunk in chunks:
            payload = chunk if plain else md2tg.md_to_tg_html(chunk)
            if not payload.strip():
                continue
            try:
                result = self.tg.send_message(chat_id, payload, parse_mode=None if plain else "HTML")
            except TelegramError as exc:
                return sent, exc.human()
            record = self.store.upsert({
                "id": int(result["message_id"]),
                "chat_id": chat_id,
                "direction": "out",
                "date": int(result.get("date") or time.time()),
                "text": chunk,
                "caption": "",
                "kind": "text",
                "media": None,
                "status": "ok",
                "error": None,
                "edited": 0,
            })
            sent.append(record)
            self.store.update_chat_last(chat_id, record["date"], chunk)
        return sent, None

    def send_file(self, chat_id: int, tmp_path: Path, name: str, mime: str,
                  caption: str) -> tuple[dict[str, Any] | None, str | None]:
        safe = _safe_filename(name or tmp_path.name)
        dest = self.media_dir / f"out-{int(time.time())}-{uuid.uuid4().hex[:6]}-{safe}"
        try:
            os.replace(tmp_path, dest)
        except OSError:
            dest = tmp_path
        caption_html = md2tg.md_to_tg_html(caption[:900]) if caption else ""
        kind = _outgoing_kind(dest, mime)
        try:
            result = self.tg.send_upload(chat_id, dest, kind, caption_html)
        except TelegramError as exc:
            return None, exc.human()

        actual = "document"
        media: dict[str, Any] = {"file_name": safe, "file_size": dest.stat().st_size, "mime_type": mime}
        for candidate in ("photo", "video", "animation", "voice", "audio", "document"):
            payload = result.get(candidate)
            if not payload:
                continue
            actual = candidate
            if isinstance(payload, list):
                payload = payload[-1]
            for key in ("file_id", "width", "height", "duration", "performer", "title",
                        "file_name", "mime_type"):
                if payload.get(key) is not None:
                    media[key] = payload[key]
            break
        media["file_name"] = safe
        if mime.startswith("image/"):
            media["is_image"] = True
        record = self.store.upsert({
            "id": int(result["message_id"]),
            "chat_id": chat_id,
            "direction": "out",
            "date": int(result.get("date") or time.time()),
            "text": "",
            "caption": caption,
            "kind": actual,
            "media": media,
            "local_path": str(dest),
            "status": "ok",
            "error": None,
            "edited": 0,
        })
        self.store.update_chat_last(chat_id, record["date"], caption or f"[{KIND_LABELS.get(actual, tr('backend.66'))}]")
        return record, None
