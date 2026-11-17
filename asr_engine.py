"""Автономное распознавание речи на sherpa-onnx — без Voice Button и без UI.

Модуль сам скачивает модели, хранит прогресс в памяти и умеет расшифровывать
аудиофайлы (WAV/MP3/OGG/FLAC). Всё состояние — внутри :class:`AsrEngine`;
никаких HTTP-серверов, Flask и обращений к сторонним сервисам (кроме
скачивания моделей с Hugging Face).

Пример::

    from pathlib import Path
    from asr_engine import AsrEngine

    engine = AsrEngine(Path("models"))
    engine.download("gigaam-v3-rnnt-punct")
    engine.wait_for_download("gigaam-v3-rnnt-punct")
    print(engine.transcribe(Path("voice.mp3")))

Публичный API:

* :class:`AsrError` — единственное исключение модуля, текст на русском.
* :class:`ModelSpec`, :data:`MODEL_REGISTRY`, :func:`register_model` — реестр.
* :class:`AsrEngine`:

  - ``download(model_id, force=False)`` — фоновая загрузка;
  - ``wait_for_download(model_id, timeout=None)`` — ожидание;
  - ``download_and_wait(model_id, timeout=None)``;
  - ``model_status(model_id)`` / ``list_models()``;
  - ``transcribe(audio_path, model_id=None) -> str``;
  - ``preload(model_id=None) -> str`` — загрузить модель без распознавания;
  - ``unload(model_id=None)`` — выгрузить из RAM + ``gc.collect()``;
  - ``is_loaded`` (bool), ``loaded_models`` (list[str]),
    ``is_model_loaded(model_id)``.

По умолчанию распознаватель выгружается после каждого ``transcribe()``.
Создайте ``AsrEngine(models_dir, auto_unload=False)``, если нужен постоянный
кэш в памяти.

Требования: ``sherpa-onnx``, ``soundfile``, ``numpy``, ``requests``.
"""

from __future__ import annotations

import gc
import logging
import os
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import quote

import numpy as np

log = logging.getLogger(__name__)

__all__ = [
    "AsrError",
    "AsrEngine",
    "ModelSpec",
    "MODEL_REGISTRY",
    "SAMPLE_RATE",
    "register_model",
]

SAMPLE_RATE = 16_000
MIN_RMS = 1e-4
CHUNK_SECONDS = 25.0
MIN_TAIL_SECONDS = 0.2

_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AsrEngine/1.0"
_CONNECT_TIMEOUT = 30.0
_READ_TIMEOUT = 120.0
_ATTEMPTS = 3
_CHUNK_BYTES = 1024 * 1024

#: Допустимые типы движков sherpa-onnx.
ENGINES = ("transducer", "nemo_ctc", "whisper")

_HF = "https://huggingface.co/csukuangfj/"


class AsrError(Exception):
    """Понятная пользователю ошибка распознавания/загрузки модели."""


@dataclass(frozen=True)
class ModelSpec:
    """Описание одной модели в реестре.

    Реестр намеренно декларативный: чтобы добавить модель, достаточно создать
    ``ModelSpec`` и вызвать :func:`register_model`. Поле ``options`` — запас
    для параметров конкретного движка (например, ``model_type`` или язык
    Whisper), чтобы не менять код при добавлении новых моделей.
    """

    id: str
    title: str
    language: str
    size_mb: int
    engine: str
    base_url: str
    files: tuple[str, ...]
    feature_dim: int = 64
    num_threads: int = 2
    options: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.engine not in ENGINES:
            raise ValueError(
                f"Неизвестный тип движка {self.engine!r}; "
                f"допустимо: {', '.join(ENGINES)}"
            )
        if not self.files:
            raise ValueError("У модели должен быть хотя бы один файл")
        object.__setattr__(self, "files", tuple(self.files))
        object.__setattr__(self, "options", dict(self.options))

    def url(self, filename: str) -> str:
        return self.base_url.rstrip("/") + "/" + quote(filename)


#: Реестр моделей: id -> ModelSpec. Порядок важен: первая скачанная модель
#: используется по умолчанию.
MODEL_REGISTRY: dict[str, ModelSpec] = {}


def register_model(spec: ModelSpec, *, replace: bool = True) -> ModelSpec:
    """Добавить (или заменить) модель в реестре. Возвращает ``spec``."""

    if not isinstance(spec, ModelSpec):
        raise TypeError("Ожидается ModelSpec")
    if spec.id in MODEL_REGISTRY and not replace:
        raise ValueError(f"Модель {spec.id!r} уже зарегистрирована")
    MODEL_REGISTRY[spec.id] = spec
    return spec


register_model(
    ModelSpec(
        id="gigaam-v3-rnnt-punct",
        title="GigaAM v3 RNN-T с пунктуацией",
        language="ru",
        size_mb=225,
        engine="transducer",
        base_url=_HF
        + "sherpa-onnx-nemo-transducer-punct-giga-am-v3-russian-2025-12-16"
        "/resolve/main/",
        files=("tokens.txt", "encoder.int8.onnx", "decoder.onnx", "joiner.onnx"),
        feature_dim=64,
        # NeMo-трансдьюсер (GigaAM) требует отдельную реализацию sherpa-onnx:
        # обычный "transducer" ищет vocab_size в метаданных decoder.onnx.
        options={"model_type": "nemo_transducer"},
    )
)

register_model(
    ModelSpec(
        id="gigaam-v3-ctc-punct",
        title="GigaAM v3 CTC с пунктуацией",
        language="ru",
        size_mb=225,
        engine="nemo_ctc",
        base_url=_HF
        + "sherpa-onnx-nemo-ctc-punct-giga-am-v3-russian-2025-12-16"
        "/resolve/main/",
        files=("tokens.txt", "model.int8.onnx"),
        feature_dim=64,
    )
)

register_model(
    ModelSpec(
        id="gigaam-v2-ctc",
        title="GigaAM v2 CTC",
        language="ru",
        size_mb=225,
        engine="nemo_ctc",
        base_url=_HF
        + "sherpa-onnx-nemo-ctc-giga-am-v2-russian-2025-04-19"
        "/resolve/main/",
        files=("tokens.txt", "model.int8.onnx"),
        feature_dim=64,
    )
)

register_model(
    ModelSpec(
        id="whisper-base",
        title="Whisper base (ONNX)",
        language="multi",
        size_mb=160,
        engine="whisper",
        base_url=_HF + "sherpa-onnx-whisper-base/resolve/main/",
        files=(
            "base-tokens.txt",
            "base-encoder.int8.onnx",
            "base-decoder.int8.onnx",
        ),
        options={"whisper_language": "ru"},
    )
)


def _import_sherpa_onnx():
    try:
        import sherpa_onnx  # noqa: PLC0415 — тяжёлый импорт только по требованию
    except ImportError as exc:  # pragma: no cover - зависит от окружения
        raise AsrError(
            "Не установлен sherpa-onnx. Установите: pip install sherpa-onnx"
        ) from exc
    return sherpa_onnx


def _clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


@dataclass
class _DownloadState:
    """Изменяемое состояние загрузки одной модели (защищено lock'ом)."""

    downloading: bool = False
    downloaded_bytes: int = 0
    total_bytes: int = 0
    completed_files: int = 0
    progress: float = 0.0
    error: str | None = None
    finished_at: float | None = None


class AsrEngine:
    """Скачивание моделей и распознавание речи одним объектом.

    Args:
        models_dir: каталог для моделей; создаётся при конструировании.

    Объект потокобезопасен: загрузки идут в фоновых потоках, распознаватель
    кэшируется по id модели, одновременные расшифровки сериализуются
    per-model lock'ом (sherpa-onnx не гарантирует конкурентный decode).

    По умолчанию (``auto_unload=True``) распознаватель выгружается сразу после
    каждого :meth:`transcribe` и вызывается ``gc.collect()`` — модель не
    занимает RAM, когда не используется. Чтобы держать модель в памяти
    (быстрые серии вызовов), создайте движок с ``auto_unload=False``.
    """

    def __init__(self, models_dir: Path, *, auto_unload: bool = True):
        self.models_dir = Path(models_dir).expanduser().resolve()
        try:
            self.models_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise AsrError(
                f"Не удалось создать каталог моделей {self.models_dir}: {exc}"
            ) from exc
        if not self.models_dir.is_dir():
            raise AsrError(f"Каталог моделей не является каталогом: {self.models_dir}")

        self._auto_unload = bool(auto_unload)
        self._lock = threading.RLock()
        self._recognizer_lock = threading.Lock()
        self._recognizers: dict[str, Any] = {}
        self._decode_locks: dict[str, threading.Lock] = {}
        self._states: dict[str, _DownloadState] = {
            model_id: _DownloadState() for model_id in MODEL_REGISTRY
        }
        self._active_download: str | None = None

    # ------------------------------------------------------------------ реестр

    @staticmethod
    def _spec(model_id: str) -> ModelSpec:
        try:
            return MODEL_REGISTRY[model_id]
        except KeyError:
            raise AsrError(f"Неизвестная модель: {model_id}") from None

    def _state(self, model_id: str) -> _DownloadState:
        """Состояние модели; создаётся лениво для поздно добавленных моделей."""

        with self._lock:
            state = self._states.get(model_id)
            if state is None:
                state = _DownloadState()
                self._states[model_id] = state
            return state

    def model_status(self, model_id: str) -> dict[str, Any]:
        """Состояние модели: id, title, language, size_mb, downloaded,
        downloading, progress (0..100), error, path."""

        spec = self._spec(model_id)
        with self._lock:
            state = self._states.setdefault(model_id, _DownloadState())
            downloading = state.downloading
            error = state.error
            progress = state.progress

        downloaded = self._files_present(spec)
        if downloaded and not downloading:
            progress = 100.0
        elif not downloaded:
            progress = min(progress, 99.0)

        return {
            "id": spec.id,
            "title": spec.title,
            "language": spec.language,
            "size_mb": spec.size_mb,
            "downloaded": downloaded,
            "downloading": downloading,
            "progress": round(max(0.0, min(100.0, float(progress))), 1),
            "error": error,
            "path": str(self._model_dir(model_id)),
        }

    def list_models(self) -> list[dict[str, Any]]:
        """Список состояний всех моделей реестра (в порядке регистрации)."""

        return [self.model_status(model_id) for model_id in list(MODEL_REGISTRY)]

    # --------------------------------------------------------------- загрузка

    def download(self, model_id: str, *, force: bool = False) -> None:
        """Запустить фоновую загрузку модели и сразу вернуть управление.

        Повторный вызов для уже скачиваемой модели ничего не делает. Если в
        этот момент качается другая модель — поднимается :class:`AsrError`
        (одновременные загрузки не поддерживаются, чтобы не делить канал).
        ``force=True`` перекачивает файлы заново (полезно для повреждённых).
        """

        spec = self._spec(model_id)
        state = self._state(model_id)
        with self._lock:
            if state.downloading:
                return
            if not force and self._files_present(spec):
                state.progress = 100.0
                state.downloaded_bytes = self._dir_size(self._model_dir(model_id))
                state.total_bytes = state.downloaded_bytes
                state.error = None
                state.finished_at = time.time()
                return
            if self._active_download is not None and self._active_download != model_id:
                other = MODEL_REGISTRY[self._active_download].title
                raise AsrError(
                    f"Уже идёт загрузка модели «{other}». "
                    "Дождитесь её окончания и запустите эту снова."
                )

            state.downloading = True
            state.error = None
            state.progress = 0.0
            state.downloaded_bytes = 0
            state.total_bytes = 0
            state.completed_files = 0
            state.finished_at = None
            self._active_download = model_id

        thread = threading.Thread(
            target=self._download_worker,
            args=(model_id, force),
            name=f"asr-download-{model_id}",
            daemon=True,
        )
        try:
            thread.start()
        except RuntimeError as exc:
            with self._lock:
                state.downloading = False
                state.error = f"Не удалось запустить поток загрузки: {exc}"
                self._active_download = None
            raise AsrError(state.error) from exc

    def wait_for_download(
        self, model_id: str, timeout: float | None = None
    ) -> dict[str, Any]:
        """Дождаться окончания загрузки и вернуть ``model_status``.

        Бросает :class:`AsrError`, если загрузка закончилась ошибкой, не
        скачала модель или не уложилась в ``timeout`` секунд.
        """

        self._spec(model_id)
        deadline = None if timeout is None else time.monotonic() + max(0.0, timeout)
        while True:
            status = self.model_status(model_id)
            if not status["downloading"]:
                if status["error"]:
                    raise AsrError(status["error"])
                if not status["downloaded"]:
                    raise AsrError("Модель не скачана")
                return status
            if deadline is not None and time.monotonic() >= deadline:
                raise AsrError(
                    f"Не дождались загрузки модели «{status['title']}» "
                    f"за {timeout:.0f} с (прогресс {status['progress']:.0f}%)"
                )
            time.sleep(0.5)

    def download_and_wait(
        self, model_id: str, timeout: float | None = None
    ) -> dict[str, Any]:
        """``download`` + ``wait_for_download`` одним вызовом."""

        self.download(model_id)
        return self.wait_for_download(model_id, timeout=timeout)

    def _download_worker(self, model_id: str, force: bool) -> None:
        spec = MODEL_REGISTRY[model_id]
        state = self._state(model_id)
        target_dir = self._model_dir(model_id)
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
            log.info("Скачивание модели %s в %s", model_id, target_dir)
            sizes = self._probe_sizes(spec)
            known_total = sum(size for size in sizes.values() if size)
            all_known = all(sizes.get(name) for name in spec.files)
            self._report(state, 0, known_total, 0, len(spec.files))

            done_bytes = 0
            completed = 0
            for filename in spec.files:
                dest = target_dir / filename
                expected = sizes.get(filename)
                if not force and dest.is_file() and dest.stat().st_size > 0:
                    if expected is None or dest.stat().st_size == expected:
                        done_bytes += dest.stat().st_size
                        completed += 1
                        self._report(
                            state, done_bytes, known_total, completed, len(spec.files)
                        )
                        continue

                self._download_file(
                    spec.url(filename),
                    dest,
                    expected,
                    base_done=done_bytes,
                    total=known_total,
                    total_files=len(spec.files),
                    completed=completed,
                    state=state,
                )
                done_bytes += dest.stat().st_size
                completed += 1
                self._report(
                    state, done_bytes, known_total, completed, len(spec.files)
                )

            missing = [
                name
                for name in spec.files
                if not (target_dir / name).is_file()
                or (target_dir / name).stat().st_size <= 0
            ]
            if missing:
                raise AsrError(
                    "После загрузки не хватает файлов: " + ", ".join(missing)
                )
            if all_known:
                bad = []
                for name in spec.files:
                    expected_size = sizes.get(name)
                    if (
                        expected_size is not None
                        and (target_dir / name).stat().st_size != expected_size
                    ):
                        bad.append(name)
                if bad:
                    raise AsrError(
                        "Размер скачанных файлов не совпал с сервером: "
                        + ", ".join(bad)
                    )

            with self._lock:
                state.downloaded_bytes = done_bytes
                state.total_bytes = max(known_total, done_bytes)
                state.progress = 100.0
                state.error = None
                state.finished_at = time.time()
            self._drop_recognizer(model_id)
            log.info("Модель %s скачана (%d байт)", model_id, done_bytes)
        except Exception as exc:  # noqa: BLE001 — ошибку показываем пользователю
            message = str(exc).strip() or exc.__class__.__name__
            if not isinstance(exc, AsrError):
                message = f"Ошибка загрузки: {message}"
            log.exception("Не удалось скачать модель %s", model_id)
            with self._lock:
                state.error = message
                state.progress = min(state.progress, 99.0)
        finally:
            with self._lock:
                state.downloading = False
                if self._active_download == model_id:
                    self._active_download = None

    def _download_file(
        self,
        url: str,
        dest: Path,
        expected_size: int | None,
        *,
        base_done: int,
        total: int,
        total_files: int,
        completed: int,
        state: _DownloadState,
    ) -> None:
        part = dest.with_name(dest.name + ".part")
        last_error: Exception | None = None

        for attempt in range(1, _ATTEMPTS + 1):
            try:
                self._download_file_once(
                    url,
                    dest,
                    part,
                    expected_size,
                    base_done=base_done,
                    total=total,
                    total_files=total_files,
                    completed=completed,
                    state=state,
                )
                return
            except AsrError:
                raise
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                response = getattr(exc, "response", None)
                status = getattr(response, "status_code", None)
                retryable = not (
                    status is not None
                    and 400 <= status < 500
                    and status not in (408, 429)
                )
                log.warning(
                    "Скачивание %s: попытка %d/%d не удалась: %s",
                    dest.name,
                    attempt,
                    _ATTEMPTS,
                    exc,
                )
                if not retryable or attempt >= _ATTEMPTS:
                    break
                time.sleep(1.5 * attempt)

        raise AsrError(f"Не удалось скачать файл «{dest.name}»: {last_error}")

    def _download_file_once(
        self,
        url: str,
        dest: Path,
        part: Path,
        expected_size: int | None,
        *,
        base_done: int,
        total: int,
        total_files: int,
        completed: int,
        state: _DownloadState,
    ) -> None:
        import requests  # noqa: PLC0415

        resume = part.stat().st_size if part.is_file() else 0
        if expected_size is not None and resume > expected_size:
            part.unlink(missing_ok=True)
            resume = 0
        if expected_size is not None and resume == expected_size:
            os.replace(part, dest)
            return

        headers = {
            "User-Agent": _USER_AGENT,
            "Accept-Encoding": "identity",
        }
        if resume:
            headers["Range"] = f"bytes={resume}-"

        response = requests.get(
            url,
            headers=headers,
            stream=True,
            allow_redirects=True,
            timeout=(_CONNECT_TIMEOUT, _READ_TIMEOUT),
        )
        with response:
            if response.status_code == 416 and resume:
                # .part уже содержит весь файл — сервер подтверждает это.
                if expected_size is None or resume == expected_size:
                    os.replace(part, dest)
                    return
                part.unlink(missing_ok=True)
                raise AsrError(
                    f"Сервер отверг докачку «{dest.name}» (HTTP 416); "
                    "повторю загрузку с нуля"
                )

            if response.status_code == 206 and resume:
                content_range = response.headers.get("Content-Range", "")
                if not content_range.startswith(f"bytes {resume}-"):
                    log.warning(
                        "Сервер вернул неверный Content-Range %r, качаю заново",
                        content_range,
                    )
                    resume = 0
                    mode = "wb"
                else:
                    mode = "ab"
            elif response.status_code == 200:
                mode = "wb"
                resume = 0
            else:
                response.raise_for_status()
                raise AsrError(
                    f"Сервер ответил HTTP {response.status_code} на «{dest.name}»"
                )

            content_type = response.headers.get("Content-Type", "").lower()
            if "text/html" in content_type:
                raise AsrError(
                    f"Сервер вернул HTML вместо файла «{dest.name}» "
                    "(возможно, изменился адрес модели)"
                )

            written = resume
            with open(part, mode) as handle:
                for block in response.iter_content(chunk_size=_CHUNK_BYTES):
                    if not block:
                        continue
                    handle.write(block)
                    written += len(block)
                    self._report(
                        state,
                        base_done + written,
                        total,
                        completed,
                        total_files,
                    )

        if expected_size is not None and written != expected_size:
            raise AsrError(
                f"Файл «{dest.name}» скачан не полностью: "
                f"{written} из {expected_size} байт"
            )
        os.replace(part, dest)

    def _probe_sizes(self, spec: ModelSpec) -> dict[str, int | None]:
        """HEAD-запросы: размеры файлов на сервере (для прогресса)."""

        import requests  # noqa: PLC0415

        sizes: dict[str, int | None] = {}
        for filename in spec.files:
            size: int | None = None
            try:
                response = requests.head(
                    spec.url(filename),
                    headers={
                        "User-Agent": _USER_AGENT,
                        "Accept-Encoding": "identity",
                    },
                    allow_redirects=True,
                    timeout=(_CONNECT_TIMEOUT, 30.0),
                )
                if response.status_code == 404:
                    raise AsrError(
                        f"Файл «{filename}» не найден на сервере (HTTP 404)"
                    )
                if response.ok:
                    length = response.headers.get("Content-Length")
                    if length and length.isdigit():
                        size = int(length)
                else:
                    log.warning(
                        "HEAD %s: HTTP %d, размер неизвестен",
                        filename,
                        response.status_code,
                    )
            except AsrError:
                raise
            except Exception as exc:  # noqa: BLE001
                log.warning("HEAD %s не удался: %s", filename, exc)
            sizes[filename] = size
        return sizes

    def _report(
        self,
        state: _DownloadState,
        done: int,
        total: int,
        completed: int,
        total_files: int,
    ) -> None:
        with self._lock:
            state.downloaded_bytes = max(0, int(done))
            if total > 0:
                state.total_bytes = int(total)
            state.completed_files = int(completed)
            if total > 0:
                percent = 100.0 * state.downloaded_bytes / total
            elif total_files > 0:
                percent = 100.0 * completed / total_files
            else:
                percent = 0.0
            state.progress = max(0.0, min(99.0, percent))

    # -------------------------------------------------------------- служебное

    def _model_dir(self, model_id: str) -> Path:
        return self.models_dir / model_id

    @staticmethod
    def _dir_size(path: Path) -> int:
        try:
            return sum(
                item.stat().st_size for item in path.iterdir() if item.is_file()
            )
        except OSError:
            return 0

    def _files_present(self, spec: ModelSpec) -> bool:
        directory = self._model_dir(spec.id)
        for filename in spec.files:
            path = directory / filename
            try:
                if not path.is_file() or path.stat().st_size <= 0:
                    return False
            except OSError:
                return False
        return True

    def _drop_recognizer(self, model_id: str) -> None:
        with self._recognizer_lock:
            self._recognizers.pop(model_id, None)
            self._decode_locks.pop(model_id, None)

    def unload(self, model_id: str | None = None) -> None:
        """Выгрузить распознаватель из памяти и собрать мусор.

        ``model_id=None`` — выгрузить все загруженные модели. Файлы моделей на
        диске не трогаются: следующий :meth:`transcribe` или :meth:`preload`
        загрузит их заново.
        """

        with self._recognizer_lock:
            if model_id is None:
                self._recognizers.clear()
                self._decode_locks.clear()
            else:
                self._recognizers.pop(model_id, None)
                self._decode_locks.pop(model_id, None)
        gc.collect()
        # На Linux glibc часто оставляет арены после нативных моделей ONNX.
        # Возвращаем освободившуюся память ОС, чтобы движок действительно «затухал».
        try:
            import ctypes

            ctypes.CDLL("libc.so.6").malloc_trim(0)
        except Exception:
            pass

    @property
    def is_loaded(self) -> bool:
        """True, если хотя бы один распознаватель сейчас в памяти."""

        with self._recognizer_lock:
            return bool(self._recognizers)

    @property
    def auto_unload(self) -> bool:
        """True, если recognizer выгружается после каждого ``transcribe()``."""

        return self._auto_unload

    @property
    def loaded_models(self) -> list[str]:
        """id моделей, чьи распознаватели сейчас закэшированы."""

        with self._recognizer_lock:
            return list(self._recognizers)

    def is_model_loaded(self, model_id: str) -> bool:
        """True, если распознаватель конкретной модели сейчас в памяти."""

        self._spec(model_id)
        with self._recognizer_lock:
            return model_id in self._recognizers

    def preload(self, model_id: str | None = None) -> str:
        """Загрузить распознаватель в память, не расшифровывая аудио.

        Возвращает id фактически выбранной модели. Полезно, чтобы прогреть
        модель или измерить занимаемую RAM. ``auto_unload`` здесь не срабатывает:
        модель остаётся до явного :meth:`unload`.
        """

        spec = self._resolve_model(model_id)
        self._get_recognizer(spec)
        return spec.id

    # ------------------------------------------------------------ распознавание

    def _get_recognizer(self, spec: ModelSpec):
        with self._recognizer_lock:
            recognizer = self._recognizers.get(spec.id)
            if recognizer is None:
                recognizer = self._create_recognizer(spec)
                self._recognizers[spec.id] = recognizer
                self._decode_locks[spec.id] = threading.Lock()
            return recognizer, self._decode_locks[spec.id]

    def _create_recognizer(self, spec: ModelSpec):
        sherpa_onnx = _import_sherpa_onnx()
        directory = self._model_dir(spec.id)
        path = lambda name: str(directory / name)  # noqa: E731
        provider = str(spec.options.get("provider", "cpu"))
        try:
            if spec.engine == "transducer":
                return sherpa_onnx.OfflineRecognizer.from_transducer(
                    encoder=path("encoder.int8.onnx"),
                    decoder=path("decoder.onnx"),
                    joiner=path("joiner.onnx"),
                    tokens=path("tokens.txt"),
                    num_threads=spec.num_threads,
                    sample_rate=SAMPLE_RATE,
                    feature_dim=spec.feature_dim,
                    decoding_method="greedy_search",
                    model_type=str(spec.options.get("model_type", "transducer")),
                    provider=provider,
                )
            if spec.engine == "nemo_ctc":
                return sherpa_onnx.OfflineRecognizer.from_nemo_ctc(
                    model=path("model.int8.onnx"),
                    tokens=path("tokens.txt"),
                    num_threads=spec.num_threads,
                    sample_rate=SAMPLE_RATE,
                    feature_dim=spec.feature_dim,
                    decoding_method="greedy_search",
                    provider=provider,
                )
            if spec.engine == "whisper":
                return sherpa_onnx.OfflineRecognizer.from_whisper(
                    encoder=path("base-encoder.int8.onnx"),
                    decoder=path("base-decoder.int8.onnx"),
                    tokens=path("base-tokens.txt"),
                    language=str(spec.options.get("whisper_language", "ru")),
                    task="transcribe",
                    num_threads=spec.num_threads,
                    decoding_method="greedy_search",
                    provider=provider,
                )
        except AsrError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise AsrError(
                f"Не удалось загрузить модель «{spec.title}»: {exc}"
            ) from exc
        raise AsrError(f"Неизвестный тип движка: {spec.engine}")

    def _resolve_model(self, model_id: str | None) -> ModelSpec:
        if model_id is not None:
            spec = self._spec(model_id)
            if self._files_present(spec):
                return spec
            with self._lock:
                state = self._states.get(spec.id)
                downloading = bool(state and state.downloading)
                error = state.error if state else None
            if downloading:
                log.warning(
                    "Модель %s ещё скачивается, ищу уже готовую", spec.id
                )
            elif error:
                log.warning("Модель %s не скачана (%s), ищу готовую", spec.id, error)
            else:
                log.warning("Модель %s не скачана, ищу готовую", spec.id)

        for candidate in list(MODEL_REGISTRY.values()):
            if self._files_present(candidate):
                return candidate

        if model_id is not None:
            spec = MODEL_REGISTRY[model_id]
            with self._lock:
                state = self._states.get(model_id)
                if state is not None and state.downloading:
                    raise AsrError(
                        f"Модель «{spec.title}» ещё скачивается — "
                        "дождитесь окончания загрузки"
                    )
            raise AsrError(f"Модель не скачана: «{spec.title}»")
        raise AsrError("Модель не скачана")

    def transcribe(self, audio_path: Path, model_id: str | None = None) -> str:
        """Расшифровать аудиофайл. Синхронный вызов, возвращает текст.

        Если ``model_id`` не задан (или эта модель ещё не скачана), берётся
        первая скачанная модель из реестра. Пустое/тихое аудио даёт ``""``.

        Raises:
            AsrError: файл не найден/не читается, модель не скачана,
                sherpa-onnx не смог загрузить модель.
        """

        path = Path(audio_path)
        if not path.is_file():
            raise AsrError(f"Аудиофайл не найден: {path}")

        spec = self._resolve_model(model_id)

        # Сначала читаем аудио: если файл битый или тихий, тяжёлую модель
        # даже не загружаем.
        audio = self._load_audio(path)
        if audio.size == 0:
            raise AsrError(f"Аудиофайл пустой: {path}")
        if self._rms(audio) < MIN_RMS:
            log.info("Аудио %s тише порога, возвращаю пустой текст", path)
            return ""

        chunks = self._split(audio)
        recognizer, decode_lock = self._get_recognizer(spec)
        pieces: list[str] = []
        try:
            with decode_lock:
                pieces = self._decode_chunks(recognizer, chunks, spec.title)
        finally:
            if self._auto_unload:
                # Убираем локальную ссылку, иначе gc.collect() не освободит
                # нативный recognizer до выхода из функции.
                recognizer = None  # type: ignore[assignment]
                decode_lock = None  # type: ignore[assignment]
                self.unload(spec.id)

        return _clean_text(" ".join(pieces))

    def _decode_chunks(
        self, recognizer, chunks: list[np.ndarray], title: str
    ) -> list[str]:
        """Декодировать куски одним recognizer'ом; локальные ссылки не утекают."""

        pieces: list[str] = []
        for index, chunk in enumerate(chunks):
            if chunk.size == 0 or self._rms(chunk) < MIN_RMS:
                continue
            try:
                stream = recognizer.create_stream()
                stream.accept_waveform(SAMPLE_RATE, chunk)
                recognizer.decode_stream(stream)
                text = _clean_text(stream.result.text)
            except Exception as exc:  # noqa: BLE001
                raise AsrError(
                    f"Ошибка распознавания (модель «{title}», "
                    f"фрагмент {index + 1}/{len(chunks)}): {exc}"
                ) from exc
            if text:
                pieces.append(text)
        return pieces

    @staticmethod
    def _rms(audio: np.ndarray) -> float:
        if audio.size == 0:
            return 0.0
        return float(np.sqrt(np.mean(np.square(audio, dtype=np.float64))))

    @staticmethod
    def _split(audio: np.ndarray) -> list[np.ndarray]:
        chunk_samples = max(1, int(CHUNK_SECONDS * SAMPLE_RATE))
        chunks = [
            audio[start : start + chunk_samples]
            for start in range(0, audio.size, chunk_samples)
        ]
        if (
            len(chunks) > 1
            and chunks[-1].size < MIN_TAIL_SECONDS * SAMPLE_RATE
        ):
            chunks[-2] = np.concatenate((chunks[-2], chunks[-1]))
            chunks.pop()
        return chunks

    @staticmethod
    def _load_audio(path: Path) -> np.ndarray:
        """Прочитать WAV/MP3/OGG/FLAC, свести в mono 16 кГц float32."""

        try:
            import soundfile as sf  # noqa: PLC0415
        except ImportError as exc:  # pragma: no cover
            raise AsrError(
                "Не установлен soundfile. Установите: pip install soundfile"
            ) from exc

        try:
            data, rate = sf.read(str(path), dtype="float32", always_2d=True)
        except Exception as exc:  # noqa: BLE001
            raise AsrError(
                f"Не удалось прочитать аудиофайл «{path.name}»: {exc}. "
                "Поддерживаются WAV/MP3/OGG/FLAC. MP4 и другие видеофайлы "
                "нужно предварительно извлечь в аудио (например, через ffmpeg)."
            ) from exc

        if data.size == 0:
            return np.zeros(0, dtype=np.float32)
        if rate <= 0:
            raise AsrError(f"Некорректная частота дискретизации: {rate}")

        if data.shape[1] > 1:
            mono = data.mean(axis=1, dtype=np.float32)
        else:
            mono = data[:, 0].astype(np.float32, copy=False)

        if rate != SAMPLE_RATE and mono.size > 1:
            new_length = max(1, int(round(mono.size * SAMPLE_RATE / float(rate))))
            source = np.arange(mono.size, dtype=np.float64)
            target = np.linspace(0.0, mono.size - 1.0, num=new_length)
            mono = np.interp(target, source, mono).astype(np.float32)

        mono = np.nan_to_num(mono, nan=0.0, posinf=0.0, neginf=0.0)
        return np.clip(mono, -1.0, 1.0).astype(np.float32, copy=False)
