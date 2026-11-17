"""Интеграционный тест внешнего HTTP API.

Проверяет все операции, которые нужны внешним агентам:
- список пользователей;
- добавление и блокировка/разблокировка;
- отправка текста и файла выбранному пользователю;
- чтение сообщений пользователя;
- скачивание полученного файла.

Тест поднимает настоящий agent_api на свободном порту, но подменяет
Telegram-отправку, чтобы не трогать реального бота.
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import agent_api  # noqa: E402
from store import Store  # noqa: E402
from web_server import _adapt_agent_app  # noqa: E402
from webapp import WebApp  # noqa: E402


class AgentApiTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = Path(tempfile.mkdtemp(prefix="agent-api-test-"))
        os.environ.pop("ALLOWED_USER_IDS", None)
        self.app = WebApp(
            {"bot_token": "123:TEST", "api_base": "http://127.0.0.1:9"},
            self.temp / "data",
            self.temp / "models",
        )
        self.store = self.app.store
        self.store.upsert_chat(111, allowed=True, first_name="Алиса", username="alice")
        self.store.upsert_chat(222, allowed=False, first_name="Боб", username="bob")
        self.store.upsert_known_user(222, username="bob", first_name="Боб", last_seen=1700000000)
        self.store.upsert_known_user(333, username="carol", first_name="Кэрол", last_seen=1700000001)

        self.sent_text: list[tuple[int, str]] = []
        self.sent_files: list[tuple[int, str]] = []

        def fake_send_text(chat_id, text, plain=False):
            self.sent_text.append((int(chat_id), text))
            message = self.store.upsert({
                "id": 900 + len(self.sent_text),
                "chat_id": int(chat_id),
                "direction": "out",
                "date": int(time.time()),
                "text": text,
                "kind": "text",
                "status": "ok",
            })
            return [message], None

        def fake_send_file(chat_id, tmp_path, name, mime, caption):
            self.sent_files.append((int(chat_id), name))
            message = self.store.upsert({
                "id": 950 + len(self.sent_files),
                "chat_id": int(chat_id),
                "direction": "out",
                "date": int(time.time()),
                "caption": caption,
                "kind": "document",
                "media": {"file_name": name, "mime_type": mime},
                "local_path": str(tmp_path),
                "status": "ok",
            })
            return message, None

        def fake_add_chat(user_id=None, username=None):
            cid = int(user_id or 333)
            chat = self.store.upsert_chat(
                cid, allowed=True, first_name=username or f"User {cid}", username=username
            )
            return chat

        self.app.send_text = fake_send_text
        self.app.send_file = fake_send_file
        self.app.add_chat = fake_add_chat
        self.facade = _adapt_agent_app(self.app)
        self.server, self.info = agent_api.create_agent_server(self.facade, "127.0.0.1", 0)
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.store.close()

    def test_help_lists_user_management_and_media(self) -> None:
        data = requests.get(self.base + "/api/help", timeout=5).json()
        self.assertTrue(data["ok"])
        paths = {item["path"] for item in data["endpoints"]}
        self.assertIn("/api/users", paths)
        self.assertIn("/api/users/add", paths)
        self.assertIn("/api/users/block", paths)
        self.assertIn("/api/media/<message_id>", paths)

    def test_users_add_block_unblock(self) -> None:
        data = requests.get(self.base + "/api/users", timeout=5).json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["users"][0]["chat_id"], 111)
        self.assertTrue(any(u["chat_id"] == 333 for u in data["users"]))

        added = requests.post(
            self.base + "/api/users/add", json={"user_id": 444}, timeout=5
        ).json()
        self.assertTrue(added["ok"])
        self.assertTrue(added["user"]["allowed"])
        self.assertTrue(self.store.get_chat(444)["allowed"])

        blocked = requests.post(
            self.base + "/api/users/block", json={"chat_id": 111}, timeout=5
        ).json()
        self.assertTrue(blocked["ok"])
        self.assertFalse(self.store.get_chat(111)["allowed"])

        listed = requests.get(self.base + "/api/users", timeout=5).json()["users"]
        self.assertFalse(next(u for u in listed if u["chat_id"] == 111)["allowed"])

        unblocked = requests.post(
            self.base + "/api/users/unblock", json={"chat_id": 111}, timeout=5
        ).json()
        self.assertTrue(unblocked["ok"])
        self.assertTrue(self.store.get_chat(111)["allowed"])

    def test_send_text_to_selected_user(self) -> None:
        result = requests.post(
            self.base + "/api/send",
            json={"chat_id": 111, "text": "Привет, Алиса"},
            timeout=5,
        ).json()
        self.assertTrue(result["ok"])
        self.assertEqual(self.sent_text[-1], (111, "Привет, Алиса"))
        self.assertEqual(result["chat_id"], 111)

        missing = requests.post(
            self.base + "/api/send",
            json={"chat_id": 999999, "text": "нет чата"},
            timeout=5,
        )
        self.assertEqual(missing.status_code, 502)
        self.assertFalse(missing.json()["ok"])

    def test_send_file_to_selected_user(self) -> None:
        response = requests.post(
            self.base + "/api/send_file",
            params={"chat_id": 111, "caption": "документ"},
            files={"file": ("report.txt", b"hello", "text/plain")},
            timeout=10,
        ).json()
        self.assertTrue(response["ok"])
        self.assertEqual(self.sent_files[-1], (111, "report.txt"))
        self.assertEqual(response["chat_id"], 111)

    def test_messages_and_media_download(self) -> None:
        media_file = self.app.media_dir / "incoming.txt"
        media_file.write_bytes(b"incoming-file")
        self.store.upsert({
            "id": 1,
            "chat_id": 111,
            "direction": "in",
            "date": int(time.time()),
            "text": "файл",
            "kind": "document",
            "media": {"file_name": "incoming.txt", "mime_type": "text/plain"},
            "local_path": str(media_file),
            "status": "ok",
        })
        messages = requests.get(
            self.base + "/api/messages", params={"chat_id": 111}, timeout=5
        ).json()
        self.assertTrue(messages["ok"])
        self.assertEqual(messages["chat_id"], 111)
        self.assertTrue(any(m["id"] == 1 for m in messages["messages"]))

        response = requests.get(self.base + "/api/media/1", timeout=5)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"incoming-file")
        self.assertIn("incoming.txt", response.headers.get("Content-Disposition", ""))


if __name__ == "__main__":
    unittest.main(verbosity=2)
