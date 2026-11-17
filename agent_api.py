"""HTTP API для скриптов и других агентов.

Слушает отдельный порт (по умолчанию 8765) на всех интерфейсах — чтобы
скрипты в локальной сети могли отправлять сообщения от имени бота.
По умолчанию авторизации нет (как и просили); при необходимости можно задать
``agent_token`` в config.json.

Эндпоинты (JSON, CORS разрешён):

  GET  /                 — описание API и адреса
  GET  /status           — состояние бота и чата
  GET  /messages?limit=  — последние сообщения (чтобы читать ответы)
  POST /send             — {"text": "...", "parse": "md"|"plain"}
  POST /send_file        — multipart/form-data (file, caption) либо
                           JSON {"file_base64": "...", "file_name": "..."} либо
                           JSON {"path": "C:\\...", "caption": "..."} либо
                           тело запроса целиком (?name=..., &caption=...)
"""

from __future__ import annotations

from i18n import tr

import base64
import ipaddress
import json
import logging
import mimetypes
import os
import socket
import threading
import time
import uuid
from email import policy as email_policy
from email.parser import BytesParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urlparse

import requests

log = logging.getLogger(__name__)

MAX_BODY = 80 * 1024 * 1024  # с запасом под 50-МБ файлы


class AgentError(Exception):
    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


def _private_score(ip: str) -> int:
    parts = ip.split(".")
    if len(parts) != 4:
        return 0
    try:
        octets = [int(p) for p in parts]
    except ValueError:
        return 0
    first, second = octets[0], octets[1]
    if first == 192 and second == 168:
        return 5
    if first == 10:
        return 4
    if first == 172 and 16 <= second <= 31:
        return 3
    if first == 127 or first == 169 and second == 254:
        return 0
    if first == 198 and second == 18:  # тестовый диапазон, часто VPN
        return 0
    return 1


def lan_ips() -> list[str]:
    """Все IPv4-адреса машины, пригодные для доступа из локальной сети."""
    found: set[str] = set()
    try:
        found.update(socket.gethostbyname_ex(socket.gethostname())[2])
    except OSError:
        pass
    try:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            probe.connect(("8.8.8.8", 80))
            found.add(probe.getsockname()[0])
        finally:
            probe.close()
    except OSError:
        pass
    usable = []
    for ip in found:
        try:
            addr = ipaddress.ip_address(ip)
        except ValueError:
            continue
        if addr.is_loopback or not addr.is_private:
            continue
        if _private_score(ip) <= 0:
            continue
        usable.append(ip)
    usable.sort(key=lambda ip: (-_private_score(ip), ip))
    return usable


def lan_ip() -> str:
    """Основной адрес для ссылок (первый приватный)."""
    ips = lan_ips()
    return ips[0] if ips else "127.0.0.1"


class Handler(BaseHTTPRequestHandler):
    server_version = "TgDeskChat-API/1.0"
    protocol_version = "HTTP/1.1"

    @property
    def app(self):
        return self.server.app  # type: ignore[attr-defined]

    def log_message(self, fmt: str, *args: Any) -> None:
        log.info("API %s - %s", self.client_address[0], fmt % args)

    # ---------------------------------------------------------------- helpers
    def _json(self, payload: Any, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False, indent=None).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Token, X-Filename")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_media(self, msg_id: int) -> None:
        path = self.app.media_path(msg_id)
        if path is None or not path.is_file():
            raise AgentError(tr('backend.1'), 404)
        filename = path.name
        try:
            row = self.app.store.get_raw(msg_id)
            if row and row["media"]:
                filename = json.loads(row["media"]).get("file_name") or filename
        except Exception:
            pass
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        size = path.stat().st_size
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(size))
        self.send_header(
            "Content-Disposition",
            "attachment; filename*=UTF-8''" + quote(filename),
        )
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        with open(path, "rb") as handle:
            while True:
                chunk = handle.read(128 * 1024)
                if not chunk:
                    break
                self.wfile.write(chunk)

    def _check_token(self, query: dict[str, list[str]]) -> None:
        expected = str(self.app.config.get("agent_token") or "").strip()
        if expected:
            given = (query.get("token") or [""])[0] or self.headers.get("X-Token", "")
            if given != expected:
                raise AgentError(tr('backend.2'), 401)
        if self.app.config.get("agent_allow_private", True):
            try:
                client = ipaddress.ip_address(self.client_address[0])
            except ValueError:
                client = None
            if client is not None and not (client.is_private or client.is_loopback):
                raise AgentError(tr('backend.3'), 403)

    def _base_url(self) -> str:
        host = self.headers.get("Host") or f"{lan_ip()}:{self.server.server_address[1]}"
        return f"http://{host}"

    def _read_body(self) -> bytes:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return b""
        if length > MAX_BODY:
            raise AgentError(tr('backend.4'), 413)
        data = self.rfile.read(length)
        if len(data) != length:
            raise AgentError(tr('backend.5'), 400)
        return data

    def _read_json_or_form(self, body: bytes) -> dict[str, Any]:
        ctype = (self.headers.get("Content-Type") or "").lower()
        if "application/json" in ctype:
            try:
                data = json.loads(body.decode("utf-8"))
            except (UnicodeDecodeError, ValueError) as exc:
                raise AgentError(f"Некорректный JSON: {exc}") from exc
            if not isinstance(data, dict):
                raise AgentError(tr('backend.6'))
            return data
        if "application/x-www-form-urlencoded" in ctype:
            parsed = parse_qs(body.decode("utf-8", "replace"))
            return {key: values[0] for key, values in parsed.items() if values}
        if "multipart/form-data" in ctype:
            return parse_multipart(ctype, body)
        return {}

    def _save_temp(self, name: str, data: bytes) -> Path:
        safe = os.path.basename(name or "file")
        safe = "".join(ch if ch.isalnum() or ch in "._- ()[]" else "_" for ch in safe).strip(" .")
        safe = safe or "file"
        suffix = Path(safe).suffix[:16]
        tmp_dir = self.app.uploads_dir
        tmp_dir.mkdir(parents=True, exist_ok=True)
        tmp = tmp_dir / f"api-{int(time.time())}-{uuid.uuid4().hex[:6]}{suffix}"
        tmp.write_bytes(data)
        return tmp

    def _send_one_file(self, name: str, data: bytes, mime: str,
                       caption: str, chat_id=None) -> dict[str, Any]:
        if not data:
            raise AgentError(tr('backend.7'))
        tmp = self._save_temp(name, data)
        try:
            message, error = self.app.send_file(
                tmp, name, mime or "application/octet-stream", caption, chat_id=chat_id
            )
        finally:
            tmp.unlink(missing_ok=True)
        if error:
            raise AgentError(error, 502)
        return message

    # ------------------------------------------------------------- endpoints
    @staticmethod
    def _normalize(path: str) -> str:
        """Поддерживаем и /send, и /api/send."""
        if path == "/api":
            return "/"
        if path.startswith("/api/"):
            return path[4:]
        return path

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Token, X-Filename")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = self._normalize(unquote(parsed.path).rstrip("/") or "/")
        query = parse_qs(parsed.query)
        try:
            self._check_token(query)
            if path in ("/", "/help"):
                self._json(self._help())
            elif path == "/status":
                self._json({"ok": True, **self._status()})
            elif path in ("/users", "/users/list", "/user/list"):
                users = self.app.users()
                self._json({"ok": True, "users": users, "count": len(users)})
            elif path == "/messages":
                limit = min(max(int((query.get("limit") or ["20"])[0]), 1), 200)
                since = int((query.get("since_id") or ["0"])[0])
                chat_id = (query.get("chat_id") or [""])[0]
                messages = self.app.messages(
                    chat_id=int(chat_id) if str(chat_id).strip() else None,
                    limit=limit,
                    since_id=since,
                )
                self._json({"ok": True, "chat_id": int(chat_id) if str(chat_id).strip() else
                            self.app.chat_id, "messages": messages})
            elif path.startswith("/media/") or path.startswith("/file/"):
                try:
                    msg_id = int(path.rsplit("/", 1)[-1])
                except ValueError:
                    raise AgentError(tr('backend.8'), 400)
                self._send_media(msg_id)
            else:
                raise AgentError(tr('backend.9'), 404)
        except AgentError as exc:
            self._json({"ok": False, "error": exc.message}, exc.status)
        except Exception as exc:  # pragma: no cover
            log.exception("API GET %s", path)
            self._json({"ok": False, "error": f"Внутренняя ошибка: {exc}"}, 500)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = self._normalize(unquote(parsed.path).rstrip("/") or "/")
        query = parse_qs(parsed.query)
        try:
            self._check_token(query)
            body = self._read_body()
            if path in ("/send", "/send_message", "/message"):
                self._send_text(body)
            elif path in ("/send_file", "/file", "/send_photo", "/send_document", "/photo", "/document"):
                self._send_file(body, query)
            elif path in ("/users/add", "/user/add", "/users/create"):
                self._add_user(body)
            elif path in ("/users/block", "/user/block", "/users/remove", "/user/remove"):
                self._block_user(body)
            elif path in ("/users/unblock", "/user/unblock", "/users/allow", "/user/allow"):
                self._unblock_user(body)
            else:
                raise AgentError(tr('backend.9'), 404)
        except AgentError as exc:
            self._json({"ok": False, "error": exc.message}, exc.status)
        except Exception as exc:  # pragma: no cover
            log.exception("API POST %s", path)
            self._json({"ok": False, "error": f"Внутренняя ошибка: {exc}"}, 500)

    # ------------------------------------------------------------------ action
    def _add_user(self, body: bytes) -> None:
        data = self._read_json_or_form(body)
        user_id = data.get("user_id") or data.get("id") or data.get("chat_id")
        username = str(data.get("username") or "").strip() or None
        if not user_id and not username:
            raise AgentError(tr('backend.10'))
        if user_id not in (None, ""):
            try:
                user_id = int(user_id)
            except (TypeError, ValueError) as exc:
                raise AgentError(tr('backend.11')) from exc
        try:
            chat = self.app.add_user(user_id=user_id, username=username)
        except AgentError:
            raise
        except ValueError as exc:
            raise AgentError(str(exc), 404) from exc
        self._json({"ok": True, "user": chat})

    def _block_user(self, body: bytes) -> None:
        data = self._read_json_or_form(body)
        chat_id = data.get("chat_id") or data.get("user_id") or data.get("id")
        if not chat_id:
            raise AgentError(tr('backend.12'))
        try:
            chat = self.app.block_user(int(chat_id))
        except ValueError as exc:
            raise AgentError(str(exc), 400) from exc
        self._json({"ok": True, "user": chat})

    def _unblock_user(self, body: bytes) -> None:
        data = self._read_json_or_form(body)
        chat_id = data.get("chat_id") or data.get("user_id") or data.get("id")
        if not chat_id:
            raise AgentError(tr('backend.12'))
        try:
            chat = self.app.unblock_user(int(chat_id))
        except ValueError as exc:
            raise AgentError(str(exc), 400) from exc
        self._json({"ok": True, "user": chat})

    def _send_text(self, body: bytes) -> None:
        data = self._read_json_or_form(body)
        text = str(data.get("text") or data.get("message") or "").strip()
        if not text:
            raise AgentError(tr('backend.13'))
        mode = str(data.get("parse") or data.get("parse_mode") or "md").lower()
        plain = mode in ("plain", "text", "none")
        chat_id = data.get("chat_id") or data.get("user_id")
        messages, error = self.app.send_text(
            text, plain=plain,
            chat_id=int(chat_id) if chat_id not in (None, "") else None,
        )
        if error:
            raise AgentError(error, 502)
        self._json(
            {
                "ok": True,
                "messages": messages,
                "message_id": messages[-1]["id"] if messages else None,
                "chat_id": messages[-1]["chat_id"] if messages else (
                    int(chat_id) if chat_id not in (None, "") else self.app.chat_id
                ),
            }
        )

    def _send_file(self, body: bytes, query: dict[str, list[str]]) -> None:
        ctype = (self.headers.get("Content-Type") or "").lower()
        caption = (query.get("caption") or [""])[0]
        target_raw = (query.get("chat_id") or query.get("user_id") or [""])[0]
        messages: list[dict[str, Any]] = []

        if "multipart/form-data" in ctype:
            parsed = parse_multipart(ctype, body)
            fields = parsed.get("fields") or {}
            files = parsed.get("files") or []
            caption = str(fields.get("caption") or caption or "")
            target_raw = str(fields.get("chat_id") or fields.get("user_id") or target_raw or "")
            if not files:
                raise AgentError(tr('backend.14'))
            for filename, data, mime in files:
                messages.append(self._send_one_file(filename, data, mime, caption,
                                                     chat_id=self._chat_arg(target_raw)))
        elif "application/json" in ctype:
            data = self._read_json_or_form(body)
            caption = str(data.get("caption") or "")
            target_raw = str(data.get("chat_id") or data.get("user_id") or target_raw or "")
            chat_id = self._chat_arg(target_raw)
            if data.get("file_base64") or data.get("base64"):
                raw = data.get("file_base64") or data.get("base64")
                try:
                    blob = base64.b64decode(str(raw), validate=False)
                except (ValueError, TypeError) as exc:
                    raise AgentError(f"Некорректный base64: {exc}") from exc
                name = str(data.get("file_name") or data.get("name") or "file")
                mime = str(data.get("mime") or mimetypes.guess_type(name)[0] or "application/octet-stream")
                messages.append(self._send_one_file(name, blob, mime, caption, chat_id=chat_id))
            elif data.get("path"):
                source = Path(str(data["path"])).expanduser()
                if not source.is_file():
                    raise AgentError(tr('backend.15'), 404)
                blob = source.read_bytes()
                name = str(data.get("file_name") or source.name)
                mime = str(data.get("mime") or mimetypes.guess_type(name)[0] or "application/octet-stream")
                messages.append(self._send_one_file(name, blob, mime, caption, chat_id=chat_id))
            elif data.get("url"):
                url = str(data["url"])
                if not url.lower().startswith(("http://", "https://")):
                    raise AgentError(tr('backend.16'))
                try:
                    response = requests.get(url, timeout=60, stream=True)
                    response.raise_for_status()
                    length = int(response.headers.get("Content-Length") or 0)
                    if length > MAX_BODY:
                        raise AgentError(tr('backend.17'), 413)
                    blob = response.content
                except requests.RequestException as exc:
                    raise AgentError(f"Не удалось скачать файл: {exc}", 502) from exc
                name = str(data.get("file_name") or Path(urlparse(url).path).name or "file")
                mime = str(data.get("mime") or mimetypes.guess_type(name)[0] or "application/octet-stream")
                messages.append(self._send_one_file(name, blob, mime, caption, chat_id=chat_id))
            else:
                raise AgentError(tr('backend.18'))
        else:
            name = (query.get("name") or [""])[0] or self.headers.get("X-Filename") or "file"
            mime = (self.headers.get("Content-Type") or "").split(";")[0].strip()
            if not body:
                raise AgentError(tr('backend.19'))
            messages.append(self._send_one_file(name, body, mime or "application/octet-stream",
                                                caption, chat_id=self._chat_arg(target_raw)))

        self._json(
            {
                "ok": True,
                "message": messages[0] if messages else None,
                "messages": messages,
                "chat_id": messages[0]["chat_id"] if messages else self.app.chat_id,
            }
        )

    @staticmethod
    def _chat_arg(value) -> int | None:
        try:
            return int(value) if value not in (None, "") else None
        except (TypeError, ValueError):
            raise AgentError(tr('backend.20'))

    # ---------------------------------------------------------------- metadata
    def _status(self) -> dict[str, Any]:
        info = self.app.state()
        return {
            "bot": info.get("bot"),
            "chat_id": info.get("chat_id"),
            "chat_ready": info.get("chat_ready"),
            "connection": info.get("connection"),
            "error": info.get("error"),
            "limits": info.get("limits"),
            "agent": info.get("agent_api"),
        }

    def _help(self) -> dict[str, Any]:
        base = self._base_url()
        info = self.app.agent_info or {}
        port = info.get("port") or self.server.server_address[1]
        lan_urls = info.get("lan_urls") or []
        token_required = bool(str(self.app.config.get("agent_token") or "").strip())
        return {
            "ok": True,
            "service": "transfer-bot",
            "version": "1.0",
            "description": (
                "HTTP API Telegram-чата для внешних скриптов и агентов: список пользователей, "
                "добавление/блокировка, отправка текста и файлов выбранному пользователю, "
                "чтение входящих сообщений и скачивание файлов."
            ),
            "base_urls": {
                "local": info.get("url") or f"http://127.0.0.1:{port}",
                "lan": lan_urls,
                "port": port,
                "discovery_file": "data/agent_api.json",
            },
            "help": {
                "endpoint": f"{base}/api/help",
                "note": tr('backend.21'),
            },
            "auth": {
                "type": "token" if token_required else "none",
                "note": (
                    "Токен задан в config.json (agent_token). Передавайте его в заголовке "
                    "X-Token или параметром ?token=..."
                    if token_required
                    else tr('backend.22')
                ),
                "header": "X-Token" if token_required else None,
                "query": "?token=..." if token_required else None,
            },
            "response_format": {
                "success": {"ok": True, "message": "{...}", "messages": ["{...}"]},
                "error": {"ok": False, "error": tr('backend.23')},
            },
            "message_object": {
                "id": 123,
                "chat_id": 0,
                "dir": "out",
                "date": 1700000000,
                "text": tr('backend.24'),
                "caption": "",
                "kind": "text",
                "media": None,
                "local": True,
                "status": "ok",
                "error": None,
                "edited": False,
                "rev": 1,
            },
            "quickstart": [
                tr('backend.25'),
                tr('backend.26'),
                tr('backend.27'),
                tr('backend.28'),
                tr('backend.29'),
                tr('backend.30'),
                tr('backend.31'),
            ],
            "endpoints": [
                {
                    "method": "GET",
                    "path": "/api/help",
                    "summary": tr('backend.32'),
                },
                {
                    "method": "GET",
                    "path": "/api/status",
                    "summary": tr('backend.33'),
                    "response": {
                        "ok": True,
                        "bot": {"id": 0, "username": "bot", "name": tr('backend.34')},
                        "chat_id": 0,
                        "chat_ready": True,
                        "connection": "online",
                        "limits": {"download_mb": 19, "upload_mb": 50},
                    },
                },
                {
                    "method": "GET",
                    "path": "/api/users",
                    "summary": tr('backend.35'),
                    "response": {"ok": True, "count": 1, "users": ["{...}"]},
                },
                {
                    "method": "POST",
                    "path": "/api/users/add",
                    "summary": tr('backend.36'),
                    "body": {"user_id": 123, "username": "@name"},
                    "response": {"ok": True, "user": "{...}"},
                },
                {
                    "method": "POST",
                    "path": "/api/users/block",
                    "summary": tr('backend.37'),
                    "body": {"chat_id": 123},
                    "response": {"ok": True, "user": "{...}"},
                },
                {
                    "method": "POST",
                    "path": "/api/users/unblock",
                    "summary": tr('backend.38'),
                    "body": {"chat_id": 123},
                    "response": {"ok": True, "user": "{...}"},
                },
                {
                    "method": "GET",
                    "path": "/api/media/<message_id>",
                    "summary": tr('backend.39'),
                    "response": tr('backend.40'),
                },
                {
                    "method": "GET",
                    "path": "/api/messages?chat_id=123&limit=20&since_id=0",
                    "summary": tr('backend.41'),
                    "query": {
                        "chat_id": tr('backend.42'),
                        "limit": tr('backend.43'),
                        "since_id": tr('backend.44'),
                    },
                    "response": {"ok": True, "chat_id": 123, "messages": ["{...}"]},
                },
                {
                    "method": "POST",
                    "path": "/api/send",
                    "summary": tr('backend.45'),
                    "content_types": ["application/json", "application/x-www-form-urlencoded"],
                    "body": {
                        "text": tr('backend.46'),
                        "parse": tr('backend.47'),
                        "chat_id": tr('backend.42'),
                    },
                    "response": {
                        "ok": True,
                        "messages": ["{...}"],
                        "message_id": 0,
                        "chat_id": 0,
                    },
                },
                {
                    "method": "POST",
                    "path": "/api/send_file",
                    "summary": tr('backend.48'),
                    "content_types": ["multipart/form-data", "application/json", "application/octet-stream"],
                    "modes": {
                        "multipart": tr('backend.49'),
                        "raw_body": tr('backend.50'),
                        "json_base64": {"file_name": "photo.jpg", "file_base64": "…", "chat_id": 123, "caption": "…"},
                        "json_path": {"path": "C:\\\\temp\\\\photo.jpg", "chat_id": 123, "caption": "…"},
                        "json_url": {"url": "https://example.com/photo.jpg", "chat_id": 123, "caption": "…"},
                    },
                    "response": {"ok": True, "message": "{...}", "messages": ["{...}"]},
                    "notes": tr('backend.51'),
                },
            ],
            "limits": {
                "max_file_mb": int(self.app.config.get("max_upload_mb") or 50),
                "max_request_mb": 80,
                "max_text_chars": 4096,
                "receiver": tr('backend.52'),
            },
            "examples": {
                "curl_text": (
                    f"curl -X POST {base}/api/send -H \"Content-Type: application/json\" "
                    "-d '{\"text\":\"Привет от агента\"}'"
                ),
                "curl_file": (
                    f"curl -X POST {base}/api/send_file "
                    "-F \"file=@photo.jpg\" -F \"caption=Фото\""
                ),
                "python": (
                    "import requests\n"
                    f"requests.post('{base}/api/send', json={{'text': 'Привет'}}, timeout=30)\n"
                    f"requests.post('{base}/api/send_file', files={{'file': ('a.jpg', open('a.jpg','rb'))}}, "
                    "data={'caption': 'Фото'}, timeout=120)"
                ),
                "javascript": (
                    f"await fetch('{base}/api/send', {{method:'POST', headers:{{'Content-Type':'application/json'}}, "
                    "body: JSON.stringify({text:'Привет'})})"
                ),
            },
            "notes": [
                tr('backend.53'),
                tr('backend.54'),
                tr('backend.55'),
                tr('backend.56'),
                tr('backend.57'),
            ],
            "status": self._status(),
        }


def parse_multipart(content_type: str, body: bytes) -> dict[str, Any]:
    header = (
        b"Content-Type: " + content_type.encode("latin-1", "replace") +
        b"\r\nMIME-Version: 1.0\r\n\r\n"
    )
    message = BytesParser(policy=email_policy.default).parsebytes(header + body)
    fields: dict[str, str] = {}
    files: list[tuple[str, bytes, str]] = []
    if not message.is_multipart():
        return {"fields": fields, "files": files}
    for part in message.iter_parts():
        name = part.get_param("name", header="content-disposition")
        filename = part.get_filename()
        payload = part.get_payload(decode=True) or b""
        if filename:
            mime = part.get_content_type() or "application/octet-stream"
            files.append((os.path.basename(filename), payload, mime))
        elif name:
            charset = part.get_content_charset() or "utf-8"
            try:
                fields[name] = payload.decode(charset, "replace")
            except LookupError:
                fields[name] = payload.decode("utf-8", "replace")
    return {"fields": fields, "files": files}


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address: tuple[str, int], app: Any) -> None:
        self.app = app
        super().__init__(address, Handler)


def create_agent_server(app: Any, host: str = "0.0.0.0", port: int = 8765) -> tuple[Server, dict[str, Any]]:
    last_error: OSError | None = None
    server: Server | None = None
    for candidate in [port, *range(port + 1, port + 11)]:
        try:
            server = Server((host, candidate), app)
            break
        except OSError as exc:
            last_error = exc
            continue
    if server is None:
        try:
            server = Server((host, 0), app)
        except OSError:
            raise last_error or OSError(tr('backend.58'))
    actual_port = server.server_address[1]
    ips = lan_ips()
    urls = [f"http://{ip}:{actual_port}" for ip in ips]
    info = {
        "host": host,
        "port": actual_port,
        "url": f"http://127.0.0.1:{actual_port}",
        "lan_url": urls[0] if urls else f"http://{lan_ip()}:{actual_port}",
        "lan_urls": urls,
        "local_ip": ips[0] if ips else lan_ip(),
        "help_url": f"http://127.0.0.1:{actual_port}/api/help",
        "help_lan_url": f"{urls[0]}/api/help" if urls else None,
    }
    thread = threading.Thread(target=server.serve_forever, name="agent-api", daemon=True)
    thread.start()
    log.info(tr('backend.59'), info["url"], ", ".join(urls) or info["lan_url"])
    return server, info
