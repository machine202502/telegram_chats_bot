"""Отправить сообщение от имени бота через локальный API приложения.

Примеры:
    python tools/send.py "Привет! Это напоминание"
    python tools/send.py "Отчёт готов" --file report.pdf
    python tools/send.py --file photo.jpg --caption "Скриншот"
    python tools/send.py "Текст" --host 192.168.1.10 --port 8765
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import sys
from pathlib import Path

import requests

BASE = Path(__file__).resolve().parent.parent


def discover_base(host: str | None, port: int | None) -> str:
    if host:
        return f"http://{host}:{port or 8765}"
    info_path = BASE / "data" / "agent_api.json"
    if info_path.is_file():
        try:
            info = json.loads(info_path.read_text(encoding="utf-8"))
            return f"http://127.0.0.1:{info.get('port') or port or 8765}"
        except (OSError, ValueError):
            pass
    return f"http://127.0.0.1:{port or 8765}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Отправить сообщение через API Telegram-чата")
    parser.add_argument("text", nargs="?", default="", help="текст сообщения (markdown)")
    parser.add_argument("--file", "-f", action="append", default=[], help="файл для отправки (можно несколько)")
    parser.add_argument("--caption", "-c", default="", help="подпись к файлу")
    parser.add_argument("--host", default=None, help="хост API")
    parser.add_argument("--port", type=int, default=None, help="порт API")
    parser.add_argument("--plain", action="store_true", help="отправить текст без markdown")
    parser.add_argument("--quiet", "-q", action="store_true", help="не печатать ответ")
    args = parser.parse_args()

    base = discover_base(args.host, args.port)

    if not args.file:
        if not args.text.strip():
            parser.error("нужен текст или --file")
        response = requests.post(
            base + "/send",
            json={"text": args.text, "parse": "plain" if args.plain else "md"},
            timeout=60,
        )
    else:
        for index, file_name in enumerate(args.file):
            path = Path(file_name).expanduser()
            if not path.is_file():
                print(f"Файл не найден: {path}", file=sys.stderr)
                return 2
            mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            caption = args.caption if index == 0 else ""
            with path.open("rb") as handle:
                response = requests.post(
                    base + "/send_file",
                    files={"file": (path.name, handle, mime)},
                    data={"caption": caption},
                    timeout=300,
                )
            if not response.ok:
                break

    if not args.quiet:
        print(response.status_code, response.text)
    return 0 if response.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
