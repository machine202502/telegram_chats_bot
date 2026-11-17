"""Конвертация голосовых сообщений Telegram (OGG/Opus) в MP3."""

from __future__ import annotations

import logging
from pathlib import Path

log = logging.getLogger(__name__)


def convert_to_mp3(source: Path, dest: Path | None = None) -> Path | None:
    """Перекодировать аудиофайл в MP3. None, если конвертация недоступна."""
    try:
        import soundfile as sf
    except Exception as exc:  # pragma: no cover - зависит от окружения
        log.warning("soundfile недоступен, голосовое останется в исходном формате: %s", exc)
        return None

    target = dest or source.with_suffix(".mp3")
    try:
        data, samplerate = sf.read(str(source), dtype="float32", always_2d=False)
        sf.write(str(target), data, samplerate, format="MP3", subtype="MPEG_LAYER_III")
        if target.is_file() and target.stat().st_size > 0:
            return target
        log.warning("После конвертации получился пустой файл: %s", target)
        return None
    except Exception as exc:
        log.warning("Не удалось конвертировать %s в MP3: %s", source.name, exc)
        try:
            target.unlink(missing_ok=True)
        except OSError:
            pass
        return None


if __name__ == "__main__":  # маленькая проверка
    import sys

    if len(sys.argv) < 2:
        print("usage: python audio.py <file.ogg>")
        raise SystemExit(1)
    result = convert_to_mp3(Path(sys.argv[1]))
    print(result)
