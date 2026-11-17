"""Одноразовый извлекатель русских UI-строк в i18n/ru.json.

Скрипт не входит в runtime: он переписывает index.html и app.js, заменяя
текстовые узлы/строковые литералы на ключи, а значения складывает в JSON.
"""

from __future__ import annotations

import html
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HTML = ROOT / "webui" / "index.html"
JS = ROOT / "webui" / "app.js"
OUT_JSON = ROOT / "webui" / "i18n" / "ru.json"
OUT_JS = ROOT / "webui" / "i18n" / "ru.js"
CYR = re.compile(r"[А-Яа-яЁё]")
_keys: dict[str, str] = {}
_counter = 0


def key_for(value: str) -> str:
    global _counter
    value = html.unescape(value).strip()
    for key, existing in _keys.items():
        if existing == value:
            return key
    _counter += 1
    key = f"auto.{_counter}"
    _keys[key] = value
    return key


def add_attr(tag: str, name: str, key: str) -> str:
    if f"data-i18n-{name}=" in tag:
        return tag
    return tag[:-1] + f' data-i18n-{name}="{key}">'


def extract_index(text: str) -> str:
    tokens = re.split(r"(<[^>]+>)", text)
    out: list[str] = []
    in_script = False
    in_style = False
    for token in tokens:
        if not token:
            continue
        low = token.lower()
        if low.startswith("<script"):
            in_script = True
            out.append(token)
            continue
        if low.startswith("</script"):
            in_script = False
            out.append(token)
            continue
        if low.startswith("<style"):
            in_style = True
            out.append(token)
            continue
        if low.startswith("</style"):
            in_style = False
            out.append(token)
            continue
        if in_script or in_style or token.startswith("<"):
            if token.startswith("<") and not in_script and not in_style:
                # локализуем placeholder/title/aria-label
                for attr in ("placeholder", "title", "aria-label"):
                    match = re.search(
                        rf'\b{re.escape(attr)}="([^"]*[А-Яа-яЁё][^"]*)"', token
                    )
                    if match:
                        key = key_for(match.group(1))
                        token = token.replace(match.group(0), f'{attr}=""', 1)
                        token = add_attr(token, attr, key)
            out.append(token)
            continue
        if CYR.search(token):
            key = key_for(token)
            # добавляем data-i18n в предыдущий открывающий тег
            for idx in range(len(out) - 1, -1, -1):
                candidate = out[idx]
                if candidate.startswith("<") and not candidate.startswith("</"):
                    if candidate.endswith(">") and not candidate.endswith("/>"):
                        out[idx] = candidate[:-1] + f' data-i18n="{key}">'
                    break
            # текст удаляем: его подставит i18n.js
            continue
        out.append(token)
    return "".join(out)


def extract_js(source: str) -> str:
    out: list[str] = []
    i = 0
    n = len(source)
    while i < n:
        ch = source[i]
        if source.startswith("//", i):
            end = source.find("\n", i)
            if end == -1:
                out.append(source[i:])
                break
            out.append(source[i:end + 1])
            i = end + 1
            continue
        if source.startswith("/*", i):
            end = source.find("*/", i + 2)
            if end == -1:
                out.append(source[i:])
                break
            out.append(source[i:end + 2])
            i = end + 2
            continue
        if ch == "/":
            # Регулярное выражение может содержать кавычки — его нельзя
            # принимать за строку. Определяем контекст по предыдущему токену.
            before = source[:i].rstrip()
            prev = before[-1:] if before else ""
            word = re.search(r"([A-Za-z_$][\w$]*)$", before)
            is_regex = prev in "=(:,![&|?{};" or (
                word is not None and word.group(1) in {
                    "return", "case", "typeof", "delete", "void", "new",
                    "in", "of", "yield", "await",
                }
            )
            if is_regex:
                j = i + 1
                in_class = False
                while j < n:
                    if source[j] == "\\":
                        j += 2
                        continue
                    if source[j] == "[":
                        in_class = True
                    elif source[j] == "]":
                        in_class = False
                    elif source[j] == "/" and not in_class:
                        j += 1
                        break
                    j += 1
                out.append(source[i:j])
                i = j
                continue
        if ch in ("'", '"'):
            quote = ch
            j = i + 1
            value = []
            while j < n:
                if source[j] == "\\" and j + 1 < n:
                    value.append(source[j:j + 2])
                    j += 2
                    continue
                if source[j] == quote:
                    break
                value.append(source[j])
                j += 1
            raw = "".join(value)
            if j < n and source[j] == quote and CYR.search(raw):
                try:
                    decoded = json.loads('"' + raw.replace('"', '\\"') + '"')
                except Exception:
                    decoded = raw
                key = key_for(decoded)
                out.append(f"t('{key}')")
                i = j + 1
                continue
            out.append(source[i:j + 1])
            i = j + 1
            continue
        if ch == "`":
            # шаблонные строки не трогаем: в них бывают выражения ${...}
            j = i + 1
            while j < n:
                if source[j] == "\\":
                    j += 2
                    continue
                if source[j] == "`":
                    j += 1
                    break
                j += 1
            out.append(source[i:j])
            i = j
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def main() -> None:
    HTML.write_text(extract_index(HTML.read_text(encoding="utf-8")), encoding="utf-8")
    JS.write_text(extract_js(JS.read_text(encoding="utf-8")), encoding="utf-8")
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    data = dict(sorted(_keys.items(), key=lambda item: int(item[0].split(".")[1])))
    OUT_JSON.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    OUT_JS.write_text(
        "window.__I18N__ = " + json.dumps(data, ensure_ascii=False) + ";\n",
        encoding="utf-8",
    )
    print(f"keys: {len(data)}")


if __name__ == "__main__":
    main()
