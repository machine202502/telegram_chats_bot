"""Наполняет тестовую базу демо-сообщениями (для проверки интерфейса).

Запуск:
    python tools/seed_demo.py --data-dir testdata --media-dir testmedia
"""

from __future__ import annotations

import argparse
import math
import os
import shutil
import struct
import sys
import time
import wave
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from store import Store  # noqa: E402

WALLPAPERS = Path("C:/Windows/Web/Wallpaper")


def find_wallpaper(index: int) -> Path | None:
    candidates = sorted(WALLPAPERS.rglob("*.jpg")) if WALLPAPERS.exists() else []
    return candidates[index % len(candidates)] if candidates else None


def make_tone(path: Path, seconds: float = 3.2, freq: float = 440.0) -> None:
    rate = 22050
    frames = int(rate * seconds)
    with wave.open(str(path), "wb") as fh:
        fh.setnchannels(1)
        fh.setsampwidth(2)
        fh.setframerate(rate)
        data = bytearray()
        for i in range(frames):
            env = min(1.0, i / 800) * min(1.0, (frames - i) / 2000)
            value = int(9000 * env * math.sin(2 * math.pi * freq * i / rate))
            data += struct.pack("<h", value)
        fh.writeframes(bytes(data))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", default="testdata")
    parser.add_argument("--media-dir", default="testmedia")
    parser.add_argument("--chat-id", type=int, default=6973735735)
    args = parser.parse_args()

    data_dir = (BASE / args.data_dir).resolve()
    media_dir = (BASE / args.media_dir).resolve()
    media_dir.mkdir(parents=True, exist_ok=True)
    db = data_dir / "messages.db"
    if db.exists():
        db.unlink()
    store = Store(db)

    now = int(time.time())
    chat = args.chat_id
    made: list[Path] = []

    photo1 = media_dir / "101-photo.jpg"
    photo2 = media_dir / "104-photo.jpg"
    if find_wallpaper(3):
        shutil.copy2(find_wallpaper(3), photo1)
        shutil.copy2(find_wallpaper(1), photo2)
        made += [photo1, photo2]

    audio = media_dir / "105-voice.wav"
    make_tone(audio)
    made.append(audio)

    video = media_dir / "106-video.mp4"
    candidates = [
        Path(os.environ.get("TEMP", "")) / "bbb.mp4",
        Path.home() / "AppData/Local/Temp/bbb.mp4",
    ]
    source = next((c for c in candidates if c.is_file()), None)
    if source is not None:
        shutil.copy2(source, video)
        made.append(video)

    doc = media_dir / "108-report.txt"
    doc.write_text(
        "Отчёт по переписке\n\n1. Проверить доставку файлов\n2. Проверить Markdown\n3. Проверить голосовые\n",
        encoding="utf-8",
    )
    made.append(doc)

    photo3 = media_dir / "110-photo.jpg"
    if find_wallpaper(5):
        shutil.copy2(find_wallpaper(5), photo3)
        made.append(photo3)

    messages = [
        {
            "id": 100,
            "direction": "in",
            "date": now - 86400 - 4000,
            "text": "Привет! Это демо-переписка, чтобы посмотреть оформление.\n\n"
                    "**Жирный**, *курсив*, ~~зачёркнутый~~, ||спойлер|| и `код`. "
                    "Ссылка: [telegram.org](https://telegram.org)",
            "kind": "text",
        },
        {
            "id": 101,
            "direction": "out",
            "date": now - 86400 - 3800,
            "text": "Отлично, проверяю картинки и файлы 📎",
            "kind": "text",
        },
        {
            "id": 102,
            "direction": "in",
            "date": now - 86400 - 3600,
            "text": "",
            "caption": "Скриншот с другого компьютера",
            "kind": "photo",
            "local_path": str(photo1) if photo1.exists() else None,
            "media": {"file_id": "demo1", "file_name": "screenshot.jpg", "file_size": photo1.stat().st_size if photo1.exists() else 0, "width": 1920, "height": 1080},
        },
        {
            "id": 103,
            "direction": "in",
            "date": now - 86400 - 3000,
            "text": "А вот длинный код, чтобы проверить блоки:",
            "kind": "text",
        },
        {
            "id": 104,
            "direction": "in",
            "date": now - 86400 - 2900,
            "text": "```python\ndef hello(name: str) -> str:\n    return f\"Привет, {name}!\"\n\nprint(hello(\"мир\"))\n```\n\n> Цитата для проверки\n> вторая строка\n\n- пункт списка\n- ещё пункт\n\n1. нумерованный\n2. тоже",
            "kind": "text",
        },
        {
            "id": 105,
            "direction": "out",
            "date": now - 7200,
            "text": "Голосовое сообщение:",
            "kind": "text",
        },
        {
            "id": 106,
            "direction": "in",
            "date": now - 7100,
            "text": "",
            "kind": "voice",
            "local_path": str(audio),
            "media": {"file_id": "demo2", "file_name": "voice.wav", "file_size": audio.stat().st_size, "duration": 3, "mime_type": "audio/wav"},
        },
        {
            "id": 107,
            "direction": "in",
            "date": now - 7000,
            "text": "",
            "caption": "Короткое видео",
            "kind": "video",
            "local_path": str(video) if video.exists() else None,
            "media": {"file_id": "demo3", "file_name": "video.mp4", "file_size": video.stat().st_size if video.exists() else 0, "duration": 10, "width": 1280, "height": 720, "mime_type": "video/mp4"},
        },
        {
            "id": 108,
            "direction": "in",
            "date": now - 6000,
            "text": "",
            "kind": "document",
            "local_path": str(doc),
            "media": {"file_id": "demo4", "file_name": "Отчёт по переписке.txt", "file_size": doc.stat().st_size, "mime_type": "text/plain"},
        },
        {
            "id": 109,
            "direction": "out",
            "date": now - 5000,
            "text": "Файл получил, спасибо! А вот картинка в ответ:",
            "kind": "text",
        },
        {
            "id": 110,
            "direction": "out",
            "date": now - 4900,
            "text": "",
            "caption": "Ответная картинка",
            "kind": "photo",
            "local_path": str(photo2) if photo2.exists() else None,
            "media": {"file_id": "demo5", "file_name": "photo.jpg", "file_size": photo2.stat().st_size if photo2.exists() else 0, "width": 1920, "height": 1080},
        },
        {
            "id": 111,
            "direction": "in",
            "date": now - 1200,
            "text": "Сообщение с ошибкой загрузки — эмулирую недоступный файл.",
            "kind": "text",
        },
        {
            "id": 112,
            "direction": "in",
            "date": now - 1100,
            "text": "",
            "kind": "document",
            "media": {"file_id": "demo6", "file_name": "video_2024.mp4", "file_size": 48 * 1024 * 1024, "mime_type": "video/mp4"},
            "error": "Файл 48.0 МБ — больше лимита Bot API (20 МБ), скачать нельзя",
        },
        {
            "id": 113,
            "direction": "out",
            "date": now - 600,
            "text": "Всё работает 👍",
            "kind": "text",
            "edited": 1,
        },
        {
            "id": 114,
            "direction": "in",
            "date": now - 300,
            "text": "Проверка **разметки** в последнем сообщении: `inline` и https://example.com/path?a=1&b=2",
            "kind": "text",
        },
    ]

    for item in messages:
        item.setdefault("chat_id", chat)
        item.setdefault("status", "ok")
        item.setdefault("error", None)
        item.setdefault("caption", "")
        item.setdefault("media", None)
        item.setdefault("local_path", None)
        item.setdefault("edited", 0)
        store.upsert(item)

    print(f"Добавлено {len(messages)} демо-сообщений в {db}")
    print("Файлы:", ", ".join(p.name for p in made))
    store.close()


if __name__ == "__main__":
    main()
