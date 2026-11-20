"""A recorded program: serves a fixture snapshot as if it were live, and applies actions to it in memory.
Used by the tests (the whole server path - rules, locators, safety layer, log - with no program running)."""
from __future__ import annotations

import copy
import os
from pathlib import Path
from typing import Optional

from .. import config, fixtures, locator as loc_mod
from .base import Adapter, AdapterError, Target


def fixtures_dir() -> Path:
    return Path(os.environ.get("CIG_FIXTURES") or (config.REPO / "tests" / "fixtures"))


class FixtureAdapter(Adapter):
    name = "fixture"

    def __init__(self):
        self.state: dict[str, dict] = {}
        self.events: list[dict] = []

    def resolve(self, app: str) -> Optional[Target]:
        if not app.startswith("fixture:"):
            return None
        name = app.split(":", 1)[1]
        p = fixtures_dir() / f"{name}.json"
        if name not in self.state:
            if not p.exists():
                return None
            self.state[name] = fixtures.load(p)
        a = self.state[name]["app"]
        return Target(key=f"{a['exe']}|{a.get('version', '')}|fixture", exe=a["exe"], pid=a.get("pid"),
                      title=(self.state[name]["windows"][0].get("name", "") if self.state[name]["windows"] else ""),
                      elevated=bool(a.get("elevated")), adapter=self.name)

    def _data(self, target: Target) -> dict:
        for d in self.state.values():
            if d["app"]["exe"] == target.exe:
                return d
        raise AdapterError("fixture not loaded")

    def snapshot(self, target: Target, depth: int = 12) -> list[dict]:
        return copy.deepcopy(self._data(target)["windows"])

    def _find(self, target: Target, locator: str) -> tuple[dict, list]:
        windows = self._data(target)["windows"]
        for node, loc, _p, win in loc_mod.walk(windows):
            if loc == locator:
                return node, windows
        raise AdapterError(f"element gone: {locator}")

    def execute(self, target: Target, locator: str, node: dict, action: str, args: dict) -> dict:
        live, windows = self._find(target, locator)
        self.events.append({"action": action, "locator": locator, "args": args})
        if action == "set_text":
            live["value"] = str(args["text"])
        elif action == "set_checked":
            live["toggle_state"] = "On" if args["checked"] else "Off"
        elif action == "select":
            live["selected"] = True
        elif action == "choose":
            live["value"] = str(args["option"])
        elif action == "set_number":
            live.setdefault("range", {})["value"] = args["value"]
        elif action == "expand":
            live["expand_state"] = "Expanded" if args.get("expanded", True) else "Collapsed"
        elif action in ("close_window", "answer_dialog"):
            windows.remove(live)
        elif action in ("invoke", "menu", "keys"):
            live["invoked"] = int(live.get("invoked", 0)) + 1
        else:
            raise AdapterError(f"fixture adapter cannot {action}")
        return {"detail": f"fixture {action}"}

    def read(self, target: Target, locator: str, node: dict) -> dict:
        try:
            live, _ = self._find(target, locator)
        except AdapterError:
            return {"exists": False}
        keys = ("name", "value", "toggle_state", "selected", "expand_state", "range", "enabled", "invoked")
        return {"exists": True, **{k: live[k] for k in keys if k in live}}
