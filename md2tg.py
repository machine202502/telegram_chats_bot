"""Markdown -> Telegram HTML.

Telegram принимает разметку в parse_mode=HTML, но набор тегов ограничен:
<b>, <i>, <u>, <s>, <code>, <pre>, <a>, <blockquote>, <tg-spoiler>.
Здесь простой, но аккуратный конвертер «человеческого» markdown в этот набор
плюс разбиение длинных сообщений на части по лимиту 4096 символов.
"""

from __future__ import annotations

import html
import re

MAX_PART = 2800  # исходных символов на одно сообщение (с запасом под теги)

_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
_FENCE = re.compile(r"^```([^\s`]*)\s*$")
_LINK = re.compile(r"\[([^\]\n]+)\]\(([^)\s]+)\)")
_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_HR = re.compile(r"^\s{0,3}([-*_])(?:\s*\1){2,}\s*$")
_UL = re.compile(r"^(\s*)[-*+]\s+(.*)$")
_OL = re.compile(r"^(\s*)(\d{1,9})[.)]\s+(.*)$")
_BOLD = re.compile(r"\*\*(?=\S)(.+?)(?<=\S)\*\*")
_BOLD_U = re.compile(r"(?<![\w])__(?=\S)(.+?)(?<=\S)__(?![\w])")
_ITALIC = re.compile(r"(?<![\w*])\*(?=[^\s*])([^*\n]+?)(?<=[^\s*])\*(?![\w*])")
_ITALIC_U = re.compile(r"(?<![\w_])_(?=[^\s_])([^_\n]+?)(?<=[^\s_])_(?![\w_])")
_STRIKE = re.compile(r"~~(?=\S)(.+?)(?<=\S)~~")
_SPOILER = re.compile(r"\|\|(?=\S)(.+?)(?<=\S)\|\|")
_AUTOLINK = re.compile(r"(?<![\w\"'>=/])((?:https?://|www\.)[^\s<>\"']+)")


def _esc(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


class _Stash:
    """Прячет готовые фрагменты HTML от дальнейшей обработки."""

    def __init__(self) -> None:
        self.items: list[str] = []

    def put(self, value: str) -> str:
        self.items.append(value)
        return f"\x00{len(self.items) - 1}\x00"

    def restore(self, text: str) -> str:
        def repl(match: re.Match[str]) -> str:
            return self.items[int(match.group(1))]

        return re.sub(r"\x00(\d+)\x00", repl, text)


def _inline(text: str) -> str:
    text = _BOLD.sub(r"<b>\1</b>", text)
    text = _BOLD_U.sub(r"<b>\1</b>", text)
    text = _ITALIC.sub(r"<i>\1</i>", text)
    text = _ITALIC_U.sub(r"<i>\1</i>", text)
    text = _STRIKE.sub(r"<s>\1</s>", text)
    text = _SPOILER.sub(r"<tg-spoiler>\1</tg-spoiler>", text)

    def link(match: re.Match[str]) -> str:
        title, url = match.group(1), match.group(2)
        return f'<a href="{url}">{title}</a>'

    text = _LINK.sub(link, text)

    def autolink(match: re.Match[str]) -> str:
        url = match.group(1)
        href = url if not url.startswith("www.") else "https://" + url
        return f'<a href="{href}">{url}</a>'

    return _AUTOLINK.sub(autolink, text)


def md_to_tg_html(markdown: str) -> str:
    """Сконвертировать markdown-фрагмент (без разбиения) в Telegram HTML."""
    src = _CTRL.sub("", markdown.replace("\r\n", "\n").replace("\r", "\n"))
    stash = _Stash()

    # 1. блоки кода
    out_lines: list[str] = []
    lines = src.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]
        m = _FENCE.match(line.strip())
        if m:
            lang = m.group(1).strip()
            body: list[str] = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                body.append(lines[i])
                i += 1
            i += 1  # закрывающий ```
            code = _esc("\n".join(body))
            cls = f' class="language-{_esc(lang)}"' if lang else ""
            out_lines.append(stash.put(f"<pre><code{cls}>{code}</code></pre>"))
            continue
        out_lines.append(line)
        i += 1

    text = _esc("\n".join(out_lines))

    # 2. инлайн-код
    text = re.sub(r"`([^`\n]+)`", lambda m: stash.put(f"<code>{m.group(1)}</code>"), text)

    # 3. строчные блоки: заголовки, цитаты, списки, разделители
    result: list[str] = []
    quote_buf: list[str] = []

    def flush_quote() -> None:
        if quote_buf:
            result.append("<blockquote>" + "\n".join(quote_buf) + "</blockquote>")
            quote_buf.clear()

    for line in text.split("\n"):
        stripped = line.strip()
        if stripped.startswith("&gt;"):
            body = stripped[4:]
            quote_buf.append(body[1:] if body.startswith(" ") else body)
            continue
        flush_quote()

        if _HR.match(stripped):
            result.append("──────────")
            continue
        m = _HEADING.match(stripped)
        if m:
            result.append(f"<b>{m.group(2)}</b>")
            continue
        m = _UL.match(line)
        if m:
            indent = "   " * (len(m.group(1).expandtabs(4)) // 4)
            result.append(f"{indent}• {m.group(2)}")
            continue
        m = _OL.match(line)
        if m:
            indent = "   " * (len(m.group(1).expandtabs(4)) // 4)
            result.append(f"{indent}{m.group(2)}. {m.group(3)}")
            continue
        result.append(line)
    flush_quote()

    text = "\n".join(result)

    # 4. инлайн-разметка и автоссылки
    text = _inline(text)

    return stash.restore(text).strip()


def split_markdown(markdown: str, limit: int = MAX_PART) -> list[str]:
    """Разбить markdown на куски, не ломая блоки кода."""
    src = markdown.replace("\r\n", "\n").replace("\r", "\n").strip()
    if len(src) <= limit:
        return [src] if src else []

    parts: list[str] = []
    buf: list[str] = []
    buf_len = 0
    fence: str | None = None

    def flush() -> None:
        nonlocal buf, buf_len
        chunk = "\n".join(buf).strip()
        if fence:
            chunk += "\n```"
        if chunk:
            parts.append(chunk)
        buf = [fence] if fence else []  # переоткрываем код в следующей части
        buf_len = len(fence) + 1 if fence else 0

    for line in src.split("\n"):
        m = _FENCE.match(line.strip())
        if m:
            fence = None if fence else line.strip()
        if buf_len + len(line) + 1 > limit and buf:
            flush()
        buf.append(line)
        buf_len += len(line) + 1

    flush()
    # подстраховка: слишком длинные строки режем жёстко
    out: list[str] = []
    for part in parts:
        if len(part) <= 4096:
            out.append(part)
            continue
        for start in range(0, len(part), 3800):
            out.append(part[start : start + 3800])
    return [p for p in out if p.strip()]


def md_to_tg_parts(markdown: str) -> list[str]:
    return [part for part in (md_to_tg_html(chunk) for chunk in split_markdown(markdown)) if part]


if __name__ == "__main__":  # маленький self-test
    sample = """# Заголовок
**жирный**, *курсив*, ~~зачёркнутый~~, ||спойлер|| и `код`.

> цитата
> вторая строка

- пункт
1. первый

```python
print("<hello>")
```

Ссылка: [Telegram](https://telegram.org) и https://example.com
"""
    for part in md_to_tg_parts(sample):
        print(part)
        print("-" * 40)
