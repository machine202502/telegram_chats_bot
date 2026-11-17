"""Точка входа Docker-first версии telegram_chats_bot."""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent


def load_env_file(path: Path) -> None:
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def main() -> int:
    load_env_file(BASE / ".env")
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        stream=sys.stdout,
    )
    token = (os.environ.get("BOT_TOKEN") or "").strip()
    if not token:
        print("BOT_TOKEN не задан. Создайте .env из .env.example и укажите токен BotFather.", file=sys.stderr)
        return 2

    data_dir = Path(os.environ.get("DATA_DIR", str(BASE / "data"))).resolve()
    models_dir = Path(os.environ.get("MODELS_DIR", str(BASE / "models"))).resolve()
    web_port = int(os.environ.get("WEB_PORT", "8000"))
    agent_raw = os.environ.get("AGENT_API_PORT", "8765").strip()
    agent_port = int(agent_raw) if agent_raw.isdigit() else None

    config = {
        "bot_token": token,
        "api_base": os.environ.get("TELEGRAM_API_BASE", "https://api.telegram.org"),
        "api_files_base": os.environ.get("TELEGRAM_FILES_BASE", ""),
        "max_upload_mb": 50,
    }

    from webapp import WebApp

    app = WebApp(config, data_dir, models_dir)
    app.run(web_port=web_port, agent_port=agent_port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
