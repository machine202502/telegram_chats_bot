"""Серверная локализация. Сейчас поддерживается только русский язык."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
LOCALE = (os.environ.get("APP_LANG") or "ru").strip().lower()[:2] or "ru"
LOCALE_FILE = ROOT / "webui" / "i18n" / f"{LOCALE}.json"

_data: dict[str, Any] = {}
try:
    _data = json.loads(LOCALE_FILE.read_text(encoding="utf-8"))
except (OSError, ValueError):
    _data = {}


def tr(key: str, **params: Any) -> str:
    template = _data.get(key, key)
    if not isinstance(template, str):
        return str(template)
    if params:
        for name, value in params.items():
            template = template.replace("{" + name + "}", str(value))
    return template


t = tr
