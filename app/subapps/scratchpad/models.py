from __future__ import annotations

import re
from datetime import datetime
from functools import lru_cache

_LIST_RE = re.compile(
    r"^(?P<indent>\s*)"
    r"(?:"
    r"(?P<bullet>[-*+])\ (?P<check>\[[ xX]\]\ )?"
    r"|(?P<num>\d+)\.\ "
    r")"
    r"(?P<rest>.*)$"
)

# #tag: must start at a word boundary, contain at least one letter, and consist
# of letters/digits/underscore/dash. Avoids matching '#' headings (followed by
# space) and '#1' purely-numeric anchors.
_TAG_RE = re.compile(r"(?<![\w/&])#([A-Za-z][\w\-]*)")


@lru_cache(maxsize=512)
def extract_tags(body: str) -> frozenset[str]:
    """Return lowercased tags found outside of fenced code blocks and URLs.

    Cached by body: a list refresh asks for every note's tags several times
    (row text, tag filter, tag-bar counts)."""
    tags: set[str] = set()
    in_fence = False
    for line in body.splitlines():
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        stripped = re.sub(r"https?://\S+", "", line)
        for m in _TAG_RE.finditer(stripped):
            tags.add(m.group(1).lower())
    return frozenset(tags)


def format_modified(ts: float) -> str:
    try:
        dt = datetime.fromtimestamp(ts)
    except Exception:
        return ""
    now = datetime.now()
    if dt.date() == now.date():
        return dt.strftime("%H:%M")
    if (now - dt).days < 7:
        return dt.strftime("%a %H:%M")
    return dt.strftime("%Y-%m-%d")


def smart_title(body: str) -> str:
    for line in body.splitlines():
        stripped = line.strip().lstrip("#").strip()
        if stripped:
            return stripped[:60]
    return "Untitled"
