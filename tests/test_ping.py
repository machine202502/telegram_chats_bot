"""Тест слэш-команды /ping."""

from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from i18n import tr  # noqa: E402
from webapp import WebApp  # noqa: E402


class PingCommandTest(unittest.TestCase):
    def setUp(self) -> None:
        os.environ.pop("ALLOWED_USER_IDS", None)
        self.temp = Path(tempfile.mkdtemp(prefix="ping-test-"))
        self.app = WebApp(
            {"bot_token": "123:TEST", "api_base": "http://127.0.0.1:9"},
            self.temp / "data",
            self.temp / "models",
        )
        self.app.store.upsert_chat(111, allowed=True, first_name="Алиса", username="alice")
        self.app.ensure_avatar_async = lambda _user_id: None
        self.sent: list[tuple[int, str]] = []

        def fake_send(chat_id, text, plain=False):
            self.sent.append((int(chat_id), text))
            message = self.app.store.upsert({
                "id": 900 + len(self.sent),
                "chat_id": int(chat_id),
                "direction": "out",
                "date": int(time.time()),
                "text": text,
                "kind": "text",
                "status": "ok",
            })
            return [message], None

        self.app.send_text = fake_send

    def tearDown(self) -> None:
        self.app.store.close()

    def update(self, text: str, chat_id: int = 111) -> None:
        self.app.handle_update({
            "message": {
                "message_id": 1,
                "date": int(time.time()),
                "chat": {"id": chat_id, "type": "private"},
                "from": {"id": chat_id, "first_name": "Алиса", "username": "alice"},
                "text": text,
            }
        })

    def test_ping_responds(self) -> None:
        self.update("/ping")
        self.assertEqual(self.sent, [(111, tr("backend.213"))])
        stored = self.app.store.get(1, 111)
        self.assertEqual(stored["text"], "/ping")

    def test_ping_with_bot_username(self) -> None:
        self.update("/ping@telegram_chats_bot")
        self.assertEqual(self.sent, [(111, tr("backend.213"))])

    def test_ping_from_blocked_chat_ignored(self) -> None:
        self.app.store.set_chat_allowed(111, False)
        self.update("/ping")
        self.assertEqual(self.sent, [])

    def test_regular_message_does_not_trigger_ping(self) -> None:
        self.update("просто сообщение")
        self.assertEqual(self.sent, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
