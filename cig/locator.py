"""Stable element identity across runs (plan 2.5, "Stable element identity").

A locator is a path of segments from the top-level window down:
    Window[aid=MainWindow]/MenuBar[name="Application"][0]/MenuItem[name="File"][0]
A segment uses the AutomationId when the element has one, else its Name plus n = its index among same-type siblings
with that same name. The id shown to the agent is a short hash of the locator. A fingerprint (control type, patterns,
rectangle relative to the window, parent chain names) is kept beside it for a second-chance match.
"""
from __future__ import annotations

import hashlib
import re
from typing import Iterable, Optional


def _q(s: str) -> str:
    return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"') + '"'


def segment(node: dict, siblings: Iterable[dict]) -> str:
    ct = node.get("control_type") or "Custom"
    aid = node.get("automation_id") or ""
    if _stable_aid(node):                                # numeric ids are often runtime handles: not stable
        return f"{ct}[aid={_q(aid)}]"
    if ct in CONTAINERS:
        # A container's name can be live text (the Win32 file dialog's Pane is named after whatever is typed in its
        # File name box, 2026-11-20): position among same-type siblings is steadier than a name that changes.
        n = 0
        for s in siblings:
            if s is node:
                break
            if (s.get("control_type") or "Custom") == ct and not _stable_aid(s):
                n += 1
        return f"{ct}[#{n}]"
    name = node.get("name") or ""
    n = 0
    for s in siblings:
        if s is node:
            break
        if (s.get("control_type") or "Custom") == ct and (s.get("name") or "") == name:
            n += 1
    return f"{ct}[name={_q(name)}][{n}]"


CONTAINERS = {"Pane", "Group", "Custom"}


def _stable_aid(node: dict) -> bool:
    aid = node.get("automation_id") or ""
    return bool(aid) and not re.fullmatch(r"\d+", aid)


def element_id(locator: str) -> str:
    return hashlib.sha1(locator.encode("utf-8")).hexdigest()[:8]


def fingerprint(node: dict, parents: list[str], window_rect: Optional[list] = None) -> dict:
    r = node.get("rect") or [0, 0, 0, 0]
    wr = window_rect or [0, 0, 0, 0]
    return {
        "control_type": node.get("control_type"),
        "patterns": sorted(node.get("patterns") or []),
        "rel_rect": [r[0] - wr[0], r[1] - wr[1], r[2] - wr[0], r[3] - wr[1]],
        "parents": parents[-4:],
        "name": node.get("name") or "",
    }


def fingerprint_score(a: dict, b: dict) -> float:
    """0..1 similarity of two fingerprints. Control type must agree or the score is 0."""
    if a.get("control_type") != b.get("control_type"):
        return 0.0
    score = 0.3
    if a.get("patterns") == b.get("patterns"):
        score += 0.2
    if a.get("parents") == b.get("parents"):
        score += 0.2
    if a.get("name") and a.get("name") == b.get("name"):
        score += 0.2
    ra, rb = a.get("rel_rect") or [0] * 4, b.get("rel_rect") or [0] * 4
    if all(abs(x - y) <= 8 for x, y in zip(ra, rb)):
        score += 0.1
    return round(score, 2)


MATCH_THRESHOLD = 0.8   # fingerprint match needed to re-resolve when the exact locator is gone


def walk(windows: list[dict]):
    """Yield (node, locator, parents_names, window_node) for every node of a snapshot, depth first."""
    def rec(node, sibs, prefix, parents, win):
        seg = segment(node, sibs)
        loc = f"{prefix}/{seg}" if prefix else seg
        yield node, loc, parents, win
        kids = node.get("children") or []
        for k in kids:
            yield from rec(k, kids, loc, parents + [node.get("name") or node.get("control_type") or ""], win)
    for w in windows:
        yield from rec(w, windows, "", [], w)
