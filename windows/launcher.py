"""Нативное окно-обёртка для Docker-приложения telegram_chats_bot.

Запускает контейнеры (если нужно), открывает web-view с http://localhost:8000
и живёт в системном трее. Закрытие окна скрывает его в трей, а не завершает
приложение. Сам бот продолжает работать в Docker.
"""

from __future__ import annotations

import ctypes
import logging
import os
import subprocess
import sys
import threading
import time
import urllib.request
from ctypes import wintypes
from pathlib import Path

from PIL import Image
ROOT = Path(__file__).resolve().parent.parent
ICON_ICO = ROOT / "webui" / "icon.ico"
ICON_PNG = ROOT / "webui" / "icon.png"
URL = os.environ.get("TCB_URL", "http://127.0.0.1:8000")
TITLE = "telegram_chats_bot"
LOG = ROOT / "windows" / "launcher.log"

logging.basicConfig(
    filename=str(LOG),
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    encoding="utf-8",
)
log = logging.getLogger("launcher")

user32 = ctypes.windll.user32
shell32 = ctypes.windll.shell32
WM_SETICON = 0x0080
ICON_BIG = 1
ICON_SMALL = 0
IMAGE_ICON = 1
LR_LOADFROMFILE = 0x0010


def health(timeout: float = 2.0) -> bool:
    try:
        with urllib.request.urlopen(URL + "/api/health", timeout=timeout) as response:
            return response.status == 200
    except Exception:
        return False


def env_uses_local_bot_api() -> bool:
    env_file = ROOT / ".env"
    if not env_file.is_file():
        return False
    try:
        text = env_file.read_text(encoding="utf-8")
    except OSError:
        return False
    for line in text.splitlines():
        if line.strip().startswith("TELEGRAM_API_BASE="):
            return "telegram-bot-api" in line
    return False


def ensure_stack() -> None:
    if health(1.0):
        return
    command = ["docker", "compose"]
    if env_uses_local_bot_api():
        command += ["--profile", "local-bot-api"]
    command += ["up", "-d"]
    try:
        subprocess.run(command, cwd=str(ROOT), check=False, timeout=180,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.TimeoutExpired):
        pass
    deadline = time.time() + 90
    while time.time() < deadline:
        if health(1.0):
            return
        time.sleep(1.5)


def find_window() -> int:
    result: list[int] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def callback(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if not length:
            return True
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buffer, length + 1)
        # Только наше окно. Не трогаем браузеры с похожим заголовком.
        if buffer.value.strip() == TITLE:
            result.append(int(hwnd))
            return False
        return True

    user32.EnumWindows(callback, 0)
    return result[0] if result else 0


def set_window_icon() -> None:
    if not ICON_ICO.is_file():
        return
    hicon = user32.LoadImageW(None, str(ICON_ICO), IMAGE_ICON, 256, 256, LR_LOADFROMFILE)
    if not hicon:
        return
    hwnd = find_window()
    if hwnd:
        user32.SendMessageW(hwnd, WM_SETICON, ICON_BIG, hicon)
        user32.SendMessageW(hwnd, WM_SETICON, ICON_SMALL, hicon)
        log.info("Иконка окна установлена (hwnd=%s)", hwnd)


class TrayApp:
    def __init__(self, webview) -> None:
        self.webview = webview
        self.window = None
        self.tray = None
        self.tray_ready = False
        self.quitting = False
        self._hidden = False

    def attach(self, window) -> None:
        self.window = window
        window.events.closing += self.on_closing

    def show(self, *_args) -> None:
        if not self.window:
            return
        try:
            self.window.show()
            self.window.restore()
        except Exception:
            pass
        self._hidden = False
        hwnd = find_window()
        if hwnd:
            user32.ShowWindow(hwnd, 9)  # SW_RESTORE
            user32.SetForegroundWindow(hwnd)

    def hide(self, *_args) -> None:
        if not self.window:
            return
        try:
            self.window.hide()
        except Exception:
            pass
        self._hidden = True

    def on_closing(self) -> bool:
        if self.quitting:
            return True
        if not self.tray_ready:
            # Если трей почему-то не поднялся, не прячем окно безвозвратно.
            try:
                self.window.minimize()
            except Exception:
                pass
            return False
        self.hide()
        return False

    def quit(self, *_args) -> None:
        self.quitting = True
        if self.tray:
            try:
                self.tray.stop()
            except Exception:
                pass
        try:
            self.window.destroy()
        except Exception:
            pass

    def run_tray(self) -> None:
        try:
            import pystray
            from pystray import Menu, MenuItem

            image = Image.open(ICON_PNG) if ICON_PNG.is_file() else Image.new("RGBA", (64, 64), (51, 144, 236, 255))
            menu = Menu(
                MenuItem("Открыть", self.show, default=True),
                MenuItem("Свернуть в трей", self.hide),
                MenuItem("Выход", self.quit),
            )
            self.tray = pystray.Icon(TITLE, image, TITLE, menu)
            self.tray.run_detached()
            self.tray_ready = True
            log.info("Трей запущен")
        except Exception as exc:
            log.exception("Не удалось запустить трей: %s", exc)


def main() -> int:
    try:
        shell32.SetCurrentProcessExplicitAppUserModelID("telegram_chats_bot")
    except Exception:
        pass

    ensure_stack()

    if not health(3.0):
        ctypes.windll.user32.MessageBoxW(
            None,
            "Не удалось запустить telegram_chats_bot.\n"
            "Проверьте, что Docker Desktop запущен, и выполните:\n\n"
            "docker compose --profile local-bot-api up -d",
            "telegram_chats_bot",
            0x10,
        )
        return 1

    import webview

    class Bridge:
        """JS -> Python: сохранение файла через нативный диалог WebView2."""

        def save_media(self, msg_id, suggested_name=""):
            try:
                numeric = int(str(msg_id))
            except (TypeError, ValueError):
                return {"ok": False, "error": "Неверный id файла"}
            name = Path(str(suggested_name or f"telegram-{numeric}")).name
            window = webview.windows[0] if webview.windows else None
            if window is None:
                return {"ok": False, "error": "Окно не готово"}
            try:
                selected = window.create_file_dialog(
                    webview.SAVE_DIALOG,
                    save_filename=name,
                    file_types=("Все файлы (*.*)",),
                )
            except Exception as exc:
                # Если нативный диалог недоступен из потока API — сохраняем
                # в Загрузки, чтобы кнопка «Скачать» всё равно работала.
                log.exception("Диалог сохранения: %s", exc)
                downloads = Path.home() / "Downloads"
                downloads.mkdir(parents=True, exist_ok=True)
                target = downloads / name
                if target.exists():
                    target = downloads / (target.stem + "-" + str(int(time.time())) + target.suffix)
                try:
                    urllib.request.urlretrieve(f"{URL}/media/{numeric}?download=1", target)
                except Exception as download_exc:
                    log.exception("Скачивание в Загрузки")
                    return {"ok": False, "error": f"Не удалось скачать файл: {download_exc}"}
                return {"ok": True, "path": str(target)}
            if not selected:
                return {"ok": False, "cancelled": True}
            target = selected[0] if isinstance(selected, (list, tuple)) else str(selected)
            try:
                urllib.request.urlretrieve(
                    f"{URL}/media/{numeric}?download=1",
                    target,
                )
            except Exception as exc:
                log.exception("Скачивание файла")
                return {"ok": False, "error": f"Не удалось скачать файл: {exc}"}
            return {"ok": True, "path": target}

    tray = TrayApp(webview)
    window = webview.create_window(
        TITLE,
        URL,
        width=1220,
        height=840,
        min_size=(900, 600),
        text_select=True,
        js_api=Bridge(),
    )
    tray.attach(window)

    def after_start() -> None:
        time.sleep(0.8)
        set_window_icon()
        tray.run_tray()
        try:
            bridge_ok = window.evaluate_js(
                "!!(window.pywebview && window.pywebview.api && window.pywebview.api.save_media)"
            )
            log.info("Мост сохранения файлов: %s", bridge_ok)
        except Exception as exc:
            log.exception("Проверка моста: %s", exc)
        # pywebview иногда пересоздаёт HWND после старта — повторяем иконку.
        for _ in range(4):
            time.sleep(0.7)
            set_window_icon()

    webview.start(after_start, private_mode=False, storage_path=str(ROOT / "data" / "webview"))
    tray.quitting = True
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
