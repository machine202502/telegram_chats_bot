"""Извлекает русские строковые литералы Python в i18n/ru.json."""

from __future__ import annotations

import ast
import io
import json
import re
import tokenize
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FILES = [
    "agent_api.py", "webapp.py", "web_server.py", "tgclient.py",
    "profiles.py", "linkpreview.py", "audio.py", "tgmessages.py",
    "asr_engine.py",
]
LOCALE = ROOT / "webui" / "i18n" / "ru.json"
CYR = re.compile(r"[А-Яа-яЁё]")
keys: dict[str, str] = {}
counter = 0


def key_for(value: str) -> str:
    global counter
    for key, existing in keys.items():
        if existing == value:
            return key
    counter += 1
    key = f"backend.{counter}"
    keys[key] = value
    return key


def docstring_positions(source: str) -> set[tuple[int, int]]:
    result: set[tuple[int, int]] = set()
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return result
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                value = body[0].value
                if isinstance(value.value, str):
                    result.add((value.lineno, value.col_offset))
    return result


def process(path: Path) -> None:
    source = path.read_text(encoding="utf-8")
    lines = source.splitlines(keepends=True)
    offsets: list[int] = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line))
    docs = docstring_positions(source)
    tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    significant = {tokenize.NAME, tokenize.NUMBER, tokenize.STRING, tokenize.OP}
    significant |= {getattr(tokenize, name) for name in ("FSTRING_START", "FSTRING_MIDDLE", "FSTRING_END") if hasattr(tokenize, name)}
    replacements: list[tuple[int, int, str]] = []
    for idx, token in enumerate(tokens):
        if token.type != tokenize.STRING:
            continue
        match = re.match(r"([rRuUbBfF]*)('''|\"\"\"|'|\")", token.string)
        if not match:
            continue
        prefix = match.group(1).lower()
        if "f" in prefix or "b" in prefix:
            continue
        if (token.start[0], token.start[1]) in docs:
            continue
        try:
            value = ast.literal_eval(token.string)
        except (ValueError, SyntaxError):
            continue
        if not isinstance(value, str) or not CYR.search(value):
            continue
        # Соседние строковые литералы Python склеивает; t() между ними
        # сломал бы синтаксис, поэтому такие литералы не трогаем.
        prev = next((tokens[j] for j in range(idx - 1, -1, -1) if tokens[j].type in significant), None)
        nxt = next((tokens[j] for j in range(idx + 1, len(tokens)) if tokens[j].type in significant), None)
        stringish = {tokenize.STRING}
        stringish |= {getattr(tokenize, name) for name in ("FSTRING_START", "FSTRING_MIDDLE", "FSTRING_END") if hasattr(tokenize, name)}
        if prev and prev.type in stringish:
            continue
        if nxt and nxt.type in stringish:
            continue
        start = offsets[token.start[0] - 1] + token.start[1]
        end = offsets[token.end[0] - 1] + token.end[1]
        key = key_for(value)
        replacement = f"tr('{key}')"
        replacements.append((start, end, replacement))

    if not replacements:
        return
    for start, end, replacement in sorted(replacements, reverse=True):
        source = source[:start] + replacement + source[end:]

    if "from i18n import tr" not in source:
        if "from __future__ import annotations" in source:
            source = source.replace(
                "from __future__ import annotations",
                "from __future__ import annotations\n\nfrom i18n import tr",
                1,
            )
        else:
            source = "from i18n import tr\n" + source
    path.write_text(source, encoding="utf-8")
    print(path.name, len(replacements))


def main() -> None:
    for name in FILES:
        path = ROOT / name
        if path.is_file():
            process(path)
    data = json.loads(LOCALE.read_text(encoding="utf-8"))
    data.update(keys)
    LOCALE.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("backend keys", len(keys))


if __name__ == "__main__":
    main()
