"""Classify an action as read / write / destructive (plan 2.6 item 1)."""
from __future__ import annotations

import functools
import json
import re
from typing import Iterable

from . import config
from .policy import READ, WRITE, DESTRUCTIVE

READ_ACTIONS = {"read", "list_items", "read_table", "tree", "wait_ready", "get_text"}


@functools.lru_cache(maxsize=1)
def _lexicon() -> tuple[list[re.Pattern], list[str]]:
    data = json.loads((config.LIBRARY_DIR / "lexicon" / "destructive.json").read_text(encoding="utf-8"))
    word_res, substrings = [], []
    for lang, words in data["words"].items():
        for w in words:
            if lang in ("ja", "zh", "ko"):
                substrings.append(w)
            else:
                # whole words; apostrophes normalised (don't / don’t)
                word_res.append(re.compile(r"(?<!\w)" + re.escape(w.replace("’", "'")) + r"(?!\w)", re.I))
    return word_res, substrings


def destructive_hits(texts: Iterable[str]) -> list[str]:
    word_res, substrings = _lexicon()
    hits = []
    for t in texts:
        if not t:
            continue
        s = str(t).replace("’", "'").replace("&", "")      # "&Delete" mnemonics
        hits += [r.pattern for r in word_res if r.search(s)]
        hits += [w for w in substrings if w in s]
    return hits


def classify(action: str, base_kind: str | None = None, texts: Iterable[str] = ()) -> tuple[str, list[str]]:
    """Return (kind, reasons). `texts` = element name, menu path, dialog button, command line ..."""
    action = (action or "").lower()
    kind = base_kind or (READ if action in READ_ACTIONS else WRITE)
    if kind == READ:
        return READ, []
    hits = destructive_hits(texts)
    if hits:
        return DESTRUCTIVE, [f"destructive word matched: {h}" for h in hits[:3]]
    return kind, []
