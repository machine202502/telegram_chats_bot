"""Flask-сервер веб-интерфейса и JSON API (Docker-first)."""

from __future__ import annotations

from i18n import tr

import logging
import mimetypes
import os
import threading
from pathlib import Path
from typing import Any

from flask import Flask, jsonify, request, send_file, send_from_directory
from werkzeug.exceptions import HTTPException

from PIL import Image, ImageDraw

import agent_api
import linkpreview
from webapp import KIND_LABELS, WebApp

log = logging.getLogger(__name__)
BASE = Path(__file__).resolve().parent
WEBUI = BASE / "webui"


class ApiError(Exception):
    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


def _chat_json(app: WebApp, chat: dict[str, Any]) -> dict[str, Any]:
    chat_id = int(chat["id"])
    avatar = f"/api/avatar/{chat_id}"
    path = app.avatars_dir / f"{chat_id}.jpg"
    if path.is_file():
        avatar += f"?v={int(path.stat().st_mtime)}"
    return {
        "id": chat_id,
        "title": chat.get("title") or chat.get("name") or str(chat_id),
        "name": chat.get("name") or chat.get("title") or str(chat_id),
        "username": chat.get("username"),
        "avatar_url": avatar,
        "last_date": chat.get("last_date"),
        "last_text": chat.get("last_text") or "",
        "unread": 0,
        "allowed": bool(chat.get("allowed")),
    }


def _user_json(app: WebApp, user: dict[str, Any]) -> dict[str, Any]:
    user_id = int(user["id"])
    avatar = f"/api/avatar/{user_id}"
    path = app.avatars_dir / f"{user_id}.jpg"
    if path.is_file():
        avatar += f"?v={int(path.stat().st_mtime)}"
    return {
        "id": user_id,
        "name": user.get("name") or str(user_id),
        "username": user.get("username"),
        "avatar_url": avatar,
        "allowed": bool(user.get("allowed")),
        "last_seen": user.get("last_seen"),
        "start_seen": bool(user.get("start_seen")),
    }


def _require_chat(app: WebApp, chat_id: int) -> dict[str, Any]:
    chat = app.store.get_chat(chat_id)
    if not chat or not chat.get("allowed"):
        raise ApiError(tr('backend.91'), 403)
    return chat


def _fallback_avatar(app: WebApp, user_id: int) -> Path | None:
    """Красивая заглушка с инициалами, если Telegram не отдал фото."""
    path = app.avatars_dir / f"{int(user_id)}-fallback.png"
    if path.is_file():
        return path
    chat = app.store.get_chat(user_id) or {}
    user = app.store.get_known_user(user_id) or {}
    name = chat.get("name") or user.get("name") or str(user_id)
    parts = [part for part in name.replace("@", " ").split() if part]
    initials = "".join(part[0].upper() for part in parts[:2]) or "?"
    colors = [
        ((58, 158, 214), (20, 92, 140)),
        ((96, 170, 120), (30, 110, 74)),
        ((196, 132, 90), (140, 72, 40)),
        ((150, 120, 200), (90, 60, 150)),
        ((210, 120, 150), (150, 50, 90)),
    ]
    top, bottom = colors[int(user_id) % len(colors)]
    size = 256
    img = Image.new("RGB", (size, size), top)
    draw = ImageDraw.Draw(img)
    for y in range(size):
        t = y / (size - 1)
        draw.line([(0, y), (size, y)],
                  fill=tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3)))
    try:
        from PIL import ImageFont

        font_path = Path("C:/Windows/Fonts/segoeuib.ttf")
        font = ImageFont.truetype(str(font_path), 104) if font_path.is_file() else ImageFont.load_default(size=104)
    except Exception:
        font = None
    if font is not None:
        box = draw.textbbox((0, 0), initials, font=font)
        draw.text(((size - (box[2] - box[0])) / 2 - box[0],
                   (size - (box[3] - box[1])) / 2 - box[1]),
                  initials, font=font, fill=(255, 255, 255))
    img.save(path, "PNG")
    return path


def create_flask(app: WebApp) -> Flask:
    flask_app = Flask(
        __name__,
        static_folder=str(WEBUI),
        static_url_path="/static",
    )
    flask_app.config["MAX_CONTENT_LENGTH"] = app.upload_limit + 16 * 1024 * 1024
    flask_app.json.ensure_ascii = False

    @flask_app.errorhandler(ApiError)
    def _api_error(exc: ApiError):
        return jsonify({"ok": False, "error": exc.message}), exc.status

    @flask_app.errorhandler(Exception)
    def _any_error(exc: Exception):
        if isinstance(exc, HTTPException):
            return jsonify({"ok": False, "error": exc.description}), exc.code
        log.exception(tr('backend.92'))
        return jsonify({"ok": False, "error": str(exc)}), 500

    @flask_app.get("/")
    def index():
        return send_from_directory(WEBUI, "index.html")

    @flask_app.get("/favicon.ico")
    def favicon():
        icon = WEBUI / "icon.png"
        if icon.is_file():
            return send_file(icon, mimetype="image/png")
        return ("", 404)

    @flask_app.get("/<path:filename>")
    def root_asset(filename: str):
        """Статика рядом с index.html (style.css, app.js, темы, иконки)."""
        candidate = (WEBUI / filename).resolve()
        if not str(candidate).startswith(str(WEBUI.resolve())) or not candidate.is_file():
            return ("", 404)
        return send_from_directory(WEBUI, filename, max_age=0)

    @flask_app.get("/api/health")
    def health():
        return jsonify({"ok": True, "service": "telegram_chats_bot"})

    @flask_app.get("/api/bootstrap")
    def bootstrap():
        chats = [_chat_json(app, c) for c in app.store.list_chats(allowed_only=True)]
        return jsonify({
            "ok": True,
            "settings": app.settings(),
            "chats": chats,
            "state": app.state(),
        })

    @flask_app.get("/api/state")
    def state():
        return jsonify({"ok": True, **app.state()})

    @flask_app.get("/api/settings")
    def get_settings():
        return jsonify({"ok": True, "settings": app.settings()})

    @flask_app.post("/api/settings")
    def post_settings():
        data = request.get_json(silent=True) or {}
        return jsonify({"ok": True, "settings": app.update_settings(data)})

    @flask_app.get("/api/chats")
    def chats():
        items = [_chat_json(app, c) for c in app.store.list_chats(allowed_only=True)]
        return jsonify({"ok": True, "chats": items})

    @flask_app.post("/api/chats/add")
    def add_chat():
        data = request.get_json(silent=True) or {}
        user_id = data.get("user_id")
        username = (data.get("username") or "").strip() or None
        if user_id not in (None, ""):
            try:
                user_id = int(user_id)
            except (TypeError, ValueError):
                raise ApiError(tr('backend.93'))
        if not user_id and not username:
            raise ApiError(tr('backend.94'))
        try:
            chat = app.add_chat(user_id=user_id, username=username)
        except ValueError as exc:
            raise ApiError(str(exc), 404)
        except Exception as exc:
            log.exception("add_chat")
            raise ApiError(tr('backend.205', error=exc), 502)
        if not chat:
            raise ApiError(tr('backend.95'), 502)
        return jsonify({"ok": True, "chat": _chat_json(app, chat)})

    @flask_app.post("/api/chats/remove")
    def remove_chat():
        data = request.get_json(silent=True) or {}
        chat_id = int(data.get("chat_id") or 0)
        if not chat_id:
            raise ApiError(tr('backend.96'))
        app.remove_chat(chat_id)
        return jsonify({"ok": True})

    @flask_app.post("/api/chats/delete")
    def delete_chat():
        data = request.get_json(silent=True) or {}
        chat_id = int(data.get("chat_id") or 0)
        if not chat_id:
            raise ApiError(tr('backend.96'))
        app.delete_chat(chat_id)
        return jsonify({"ok": True})

    @flask_app.get("/api/known_users")
    def known_users():
        query = request.args.get("q", "")
        users = [_user_json(app, u) for u in app.known_users(query)]
        return jsonify({"ok": True, "users": users})

    @flask_app.get("/api/messages")
    def messages():
        chat_id = int(request.args.get("chat_id") or 0)
        if not chat_id:
            raise ApiError(tr('backend.96'))
        _require_chat(app, chat_id)
        rev = int(request.args.get("rev") or 0)
        before_id = int(request.args.get("before_id") or 0)
        if before_id:
            rows = app.store.before_for_chat(chat_id, before_id, limit=40)
            has_older = bool(rows) and app.store.has_before_chat(chat_id, rows[0]["id"])
        elif rev > 0:
            rows = app.store.after_for_chat(chat_id, rev, limit=500)
            has_older = False
        else:
            rows = app.store.recent_for_chat(chat_id, limit=40)
            has_older = bool(rows) and app.store.has_before_chat(chat_id, rows[0]["id"])
        return jsonify({
            "ok": True,
            "messages": rows,
            "rev": app.store.current_rev(),
            "has_older": has_older,
        })

    @flask_app.post("/api/send")
    def send():
        data = request.get_json(silent=True) or {}
        chat_id = int(data.get("chat_id") or 0)
        text = str(data.get("text") or "")
        if not chat_id:
            raise ApiError(tr('backend.96'))
        _require_chat(app, chat_id)
        if not text.strip():
            raise ApiError(tr('backend.97'))
        messages, error = app.send_text(chat_id, text)
        if error:
            raise ApiError(error, 502)
        return jsonify({"ok": True, "messages": messages})

    @flask_app.post("/api/upload")
    def upload():
        chat_id = int(request.args.get("chat_id") or request.form.get("chat_id") or 0)
        if not chat_id:
            raise ApiError(tr('backend.96'))
        _require_chat(app, chat_id)
        files = request.files.getlist("file")
        if not files:
            raise ApiError(tr('backend.98'))
        caption = request.form.get("caption") or ""
        messages = []
        for index, item in enumerate(files):
            if not item or not item.filename:
                continue
            name = os.path.basename(item.filename)
            tmp = app.uploads_dir / f"up-{os.getpid()}-{threading.get_ident()}-{index}-{name}"
            item.save(tmp)
            try:
                message, error = app.send_file(
                    chat_id, tmp, name, item.mimetype or "application/octet-stream",
                    caption if index == 0 else "",
                )
            finally:
                tmp.unlink(missing_ok=True)
            if error:
                raise ApiError(error, 502)
            if message:
                messages.append(message)
        return jsonify({"ok": True, "messages": messages})

    @flask_app.post("/api/ensure_media")
    def ensure_media():
        data = request.get_json(silent=True) or {}
        msg_id = int(data.get("id") or 0)
        if not msg_id:
            raise ApiError(tr('backend.99'))
        row = app.store.get_raw(msg_id)
        if row is None:
            raise ApiError(tr('backend.100'), 404)
        _require_chat(app, int(row["chat_id"]))
        ok = app.ensure_media(msg_id)
        return jsonify({"ok": ok, "queued": bool(ok)})

    @flask_app.post("/api/transcribe")
    def transcribe():
        data = request.get_json(silent=True) or {}
        msg_id = int(data.get("id") or 0)
        if not msg_id:
            raise ApiError(tr('backend.99'))
        row = app.store.get_raw(msg_id)
        if row is None:
            raise ApiError(tr('backend.100'), 404)
        _require_chat(app, int(row["chat_id"]))
        message = app.enqueue_transcription(msg_id)
        if message is None:
            raise ApiError(tr('backend.89'), 400)
        return jsonify({"ok": True, "message": message})

    @flask_app.post("/api/retry_media")
    def retry_media():
        data = request.get_json(silent=True) or {}
        msg_id = int(data.get("id") or 0)
        if not msg_id:
            raise ApiError(tr('backend.99'))
        row = app.store.get_raw(msg_id)
        if row is None:
            raise ApiError(tr('backend.100'), 404)
        _require_chat(app, int(row["chat_id"]))
        message = app.retry_media(msg_id)
        return jsonify({"ok": True, "message": message})

    @flask_app.get("/api/asr/models")
    def asr_models():
        data = app.asr_models()
        return jsonify({"ok": True, **data, "selected": app.settings()["asr_model"]})

    @flask_app.get("/api/asr/status")
    def asr_status():
        data = app.asr_models()
        return jsonify({"ok": True, **data, "selected": app.settings()["asr_model"]})

    @flask_app.post("/api/asr/download")
    def asr_download():
        data = request.get_json(silent=True) or {}
        model = str(data.get("model") or "").strip()
        if not model:
            raise ApiError(tr('backend.101'))
        try:
            app.download_model(model)
        except Exception as exc:
            raise ApiError(str(exc), 400)
        return jsonify({"ok": True})

    @flask_app.get("/api/link_preview")
    def link_preview():
        url = (request.args.get("url") or "").strip()
        if not url:
            raise ApiError(tr('backend.102'))
        try:
            preview = linkpreview.fetch_preview(url)
        except linkpreview.PreviewError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 200
        except Exception as exc:
            log.info("link_preview %s: %s", url, exc)
            return jsonify({"ok": False, "error": tr('backend.103')}), 200
        return jsonify({"ok": True, "preview": preview})

    @flask_app.get("/api/avatar/<int:user_id>")
    def avatar(user_id: int):
        path = app.avatar_file(user_id)
        if path is None or not path.is_file():
            path = _fallback_avatar(app, user_id)
        if path is None or not path.is_file():
            return ("", 404)
        return send_file(path, mimetype="image/png" if path.suffix == ".png" else "image/jpeg",
                         conditional=True, max_age=300)

    @flask_app.get("/media/<int:msg_id>")
    def media(msg_id: int):
        row = app.store.get_raw(msg_id)
        if row is None:
            raise ApiError(tr('backend.104'), 404)
        path = app.media_path(msg_id)
        if path is None:
            raise ApiError(tr('backend.105'), 404)
        as_attachment = request.args.get("download") == "1"
        name = path.name
        try:
            media_json = __import__("json").loads(row["media"]) if row["media"] else {}
            name = media_json.get("file_name") or name
        except Exception:
            pass
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        return send_file(
            path,
            mimetype=mime,
            as_attachment=as_attachment,
            download_name=name,
            conditional=True,
            max_age=0,
        )

    @flask_app.post("/api/open_url")
    def open_url():
        # В контейнере нет браузера — ссылки открывает сам клиент.
        return jsonify({"ok": True})

    return flask_app


def _adapt_agent_app(app: WebApp):
    """Минимальный адаптер под старый agent_api (один чат по умолчанию)."""

    class AgentFacade:
        def __init__(self, source: WebApp) -> None:
            self._source = source
            self.store = source.store
            self.config = source.config
            self.uploads_dir = source.uploads_dir
            self.agent_info: dict[str, Any] = {}

        @property
        def chat_id(self) -> int:
            return self._source.default_chat_id() or 0

        def _chat(self, chat_id=None) -> int:
            cid = int(chat_id) if chat_id not in (None, "") else self.chat_id
            chat = self.store.get_chat(cid) if cid else None
            if not chat or not chat.get("allowed"):
                raise agent_api.AgentError(
                    tr('backend.106'), 404
                )
            return cid

        def state(self) -> dict[str, Any]:
            data = self._source.state()
            data["agent_api"] = self.agent_info
            return data

        def send_text(self, text: str, plain: bool = False, chat_id=None):
            try:
                cid = self._chat(chat_id)
            except agent_api.AgentError as exc:
                return [], exc.message
            return self._source.send_text(cid, text, plain=plain)

        def send_file(self, tmp_path: Path, name: str, mime: str, caption: str,
                      chat_id=None):
            try:
                cid = self._chat(chat_id)
            except agent_api.AgentError as exc:
                return None, exc.message
            return self._source.send_file(cid, tmp_path, name, mime, caption)

        def users(self) -> list[dict[str, Any]]:
            result: dict[int, dict[str, Any]] = {}
            for chat in self.store.list_chats(allowed_only=False):
                result[int(chat["id"])] = {
                    "id": int(chat["id"]),
                    "chat_id": int(chat["id"]),
                    "name": chat.get("name") or str(chat["id"]),
                    "username": chat.get("username"),
                    "allowed": bool(chat.get("allowed")),
                    "last_seen": chat.get("last_date"),
                }
            for user in self.store.list_known_users():
                uid = int(user["id"])
                item = result.setdefault(uid, {
                    "id": uid,
                    "chat_id": uid,
                    "name": user.get("name") or str(uid),
                    "username": user.get("username"),
                    "allowed": False,
                    "last_seen": user.get("last_seen"),
                })
                item["name"] = item.get("name") or user.get("name")
                item["username"] = item.get("username") or user.get("username")
                item["last_seen"] = item.get("last_seen") or user.get("last_seen")
            return sorted(result.values(), key=lambda item: bool(item.get("allowed")), reverse=True)

        def add_user(self, user_id=None, username=None) -> dict[str, Any]:
            try:
                return self._source.add_chat(user_id=user_id, username=username)
            except ValueError as exc:
                raise agent_api.AgentError(str(exc), 404) from exc

        def block_user(self, chat_id=None) -> dict[str, Any]:
            cid = self._chat(chat_id)
            self._source.remove_chat(cid)
            return self.store.get_chat(cid) or {"id": cid, "allowed": False}

        def unblock_user(self, chat_id=None) -> dict[str, Any]:
            cid = int(chat_id) if chat_id not in (None, "") else self.chat_id
            if not cid:
                raise agent_api.AgentError(tr('backend.96'), 400)
            self.store.set_chat_allowed(cid, True)
            return self.store.get_chat(cid) or {"id": cid, "allowed": True}

        def messages(self, chat_id=None, limit: int = 50, since_id: int = 0):
            cid = self._chat(chat_id) if chat_id else self.chat_id
            if not cid:
                return []
            if since_id:
                return self.store.after_for_chat(cid, int(since_id), limit=limit)
            return self.store.recent_for_chat(cid, limit=limit)

        def ensure_media(self, msg_id: int) -> bool:
            return self._source.ensure_media(msg_id)

        def enqueue_transcription(self, msg_id: int):
            return self._source.enqueue_transcription(msg_id)

        def media_path(self, msg_id: int):
            return self._source.media_path(msg_id)

    return AgentFacade(app)


def create_servers(app: WebApp, web_port: int, agent_port: int | None = None) -> None:
    from waitress import serve

    flask_app = create_flask(app)

    if agent_port:
        try:
            facade = _adapt_agent_app(app)
            server, info = agent_api.create_agent_server(facade, "0.0.0.0", int(agent_port))
            facade.agent_info = info
            app._agent_server = server
            app._agent_info = info
        except Exception:
            log.exception(tr('backend.107'))

    thread = threading.Thread(
        target=lambda: serve(flask_app, host="0.0.0.0", port=int(web_port), threads=16),
        name="web",
        daemon=True,
    )
    thread.start()
