"""The safety layer (plan 2.6). Every action passes `decide()` before any adapter is called; the adapters never decide.

Order of checks, first refusal wins:
  1. deny lists (global and per app) - never overridable, not even by `confirm`
  2. reads are always allowed
  3. elevated target - needs `confirm`
  4. destructive - needs `confirm` (even while the person is away), and the first reply is a preview
  5. third-party apps (stricter rule, default taken 2026-11-20): any recent REAL input while the target window is the
     foreground window refuses, and `confirm` does not override it
  6. the person is active (real input within `idle_min`) or presence is unknown - needs `confirm`
  7. `keys` (synthetic keystrokes) - refused whenever the person is active, `confirm` or not
A `dry_run` passes the same checks as a real call except presence, then stops before acting.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Iterable, Optional

from . import config
from .presence import Presence

READ, WRITE, DESTRUCTIVE = "read", "write", "destructive"
KINDS = (READ, WRITE, DESTRUCTIVE)

DEFAULT_POLICY = {
    "idle_min": 5,
    "third_party_foreground_min": 30,
    "first_party_apps": ["modorganizer.exe"],
    "deny": {
        "actions": ["set_secret"],
        "apps": [],
        "window_title_patterns": [],
    },
    "apps": {},
}


def _lower_list(xs: Iterable[str]) -> list[str]:
    return [str(x).lower() for x in xs or []]


class Policy:
    def __init__(self, data: Optional[dict] = None):
        d = json.loads(json.dumps(DEFAULT_POLICY))
        if data:
            for k, v in data.items():
                if k == "deny" and isinstance(v, dict):
                    d["deny"].update(v)
                else:
                    d[k] = v
        self.data = d
        self.idle_min = float(d["idle_min"])
        self.third_party_foreground_min = float(d["third_party_foreground_min"])
        self.first_party = set(_lower_list(d["first_party_apps"]))
        deny = d["deny"]
        self.deny_actions = set(_lower_list(deny.get("actions")))
        self.deny_apps = set(_lower_list(deny.get("apps")))
        self.deny_titles = [re.compile(p, re.I) for p in deny.get("window_title_patterns") or []]
        self.apps = {k.lower(): v for k, v in (d.get("apps") or {}).items()}

    @classmethod
    def load(cls, path: Optional[Path] = None) -> "Policy":
        p = Path(path) if path else config.policy_file()
        if p.exists():
            return cls(json.loads(p.read_text(encoding="utf-8")))
        return cls()


@dataclass
class Request:
    app: str                       # exe name, e.g. "notepad.exe"
    action: str                    # rule action, e.g. "set_text", "invoke", "menu", "keys"
    kind: str                      # read | write | destructive (after classification)
    pid: Optional[int] = None
    window_title: str = ""
    element: str = ""              # human label of the target element (for the log and the preview)
    confirm: Optional[str] = None  # the person's own words, logged verbatim
    dry_run: bool = False
    elevated_target: bool = False


@dataclass
class Decision:
    allowed: bool
    status: str                    # "ok" | "dry_run" | "refused" | "confirm_required"
    reason: str = ""
    checks: list = field(default_factory=list)

    def as_dict(self) -> dict:
        return asdict(self)


def _refuse(reason: str, checks: list, status: str = "refused") -> Decision:
    return Decision(False, status, reason, checks)


def decide(req: Request, presence: Presence, policy: Policy) -> Decision:
    checks: list[str] = []
    app = (req.app or "").lower()
    action = (req.action or "").lower()
    if req.kind not in KINDS:
        return _refuse(f"unknown action kind {req.kind!r}", checks)

    # 1. deny lists
    app_rules = policy.apps.get(app, {})
    if action in policy.deny_actions or action in _lower_list(app_rules.get("deny", [])):
        return _refuse(f"action '{req.action}' is on the deny list (confirm cannot override)", checks)
    if app in policy.deny_apps:
        return _refuse(f"app '{req.app}' is on the deny list (confirm cannot override)", checks)
    for pat in policy.deny_titles:
        if req.window_title and pat.search(req.window_title):
            return _refuse(f"window title matches deny pattern /{pat.pattern}/ (confirm cannot override)", checks)
    checks.append("deny: clear")

    # 2. reads
    if req.kind == READ:
        checks.append("read: always allowed")
        return Decision(True, "ok", "", checks)

    confirmed = bool(req.confirm and req.confirm.strip())
    kind = req.kind
    if action in _lower_list(app_rules.get("confirm", [])) and kind == WRITE:
        kind = DESTRUCTIVE
        checks.append("app policy: confirm-first")

    # 3. elevated target
    if req.elevated_target and not confirmed:
        return _refuse("the target runs elevated; acting on it needs confirm", checks, "confirm_required")

    # 4. destructive
    if kind == DESTRUCTIVE and not confirmed:
        return _refuse("destructive action: needs confirm with the person's own words (preview returned)",
                       checks, "confirm_required")
    checks.append(f"kind: {kind}" + (" (confirmed)" if confirmed else ""))

    if req.dry_run:
        checks.append("dry run: stopping before the adapter")
        return Decision(True, "dry_run", "", checks)

    idle = presence.idle_min
    active = idle is None or idle < policy.idle_min

    # 5. third-party strict rule
    third_party = app not in policy.first_party
    if third_party and req.pid is not None and presence.foreground_pid == req.pid:
        if idle is None or idle < policy.third_party_foreground_min:
            return _refuse(
                f"the target window is in the foreground and the person's input was "
                f"{'unknown' if idle is None else f'{idle:.1f} min'} ago (third-party rule: "
                f"{policy.third_party_foreground_min:g} min; confirm cannot override)", checks)
    checks.append("third-party foreground rule: clear" if third_party else "first-party app")

    # 7. keys
    if action == "keys" and active:
        return _refuse("synthetic keys are refused while the person is active (confirm cannot override)", checks)

    # 6. presence
    if active and not confirmed:
        why = "presence unknown" if idle is None else f"real input {idle:.1f} min ago (< {policy.idle_min:g})"
        return _refuse(f"the person is using the machine: {why}; needs confirm", checks, "confirm_required")
    checks.append("presence: " + ("confirmed by the person" if active else f"idle {idle:.1f} min"))
    return Decision(True, "ok", "", checks)
