"""The adapter interface. An adapter knows HOW to read and act on one kind of program; it never decides WHETHER to -
the engine runs the safety layer before calling it."""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Optional


@dataclass
class Target:
    key: str                     # stable key for caches: "<exe>|<product version>|<adapter>"
    exe: str
    pid: Optional[int] = None
    title: str = ""
    hwnd: Optional[int] = None
    elevated: bool = False
    adapter: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


class AdapterError(Exception):
    pass


class Adapter:
    name = "base"

    def resolve(self, app: str) -> Optional[Target]:
        """Return a Target for an app reference (pid, exe name, window title, 'fixture:<name>'), or None."""
        raise NotImplementedError

    def snapshot(self, target: Target, depth: int = 12) -> list[dict]:
        """The program's top-level windows as fixture-format nodes (library/schema/fixture.schema.json)."""
        raise NotImplementedError

    def execute(self, target: Target, locator: str, node: dict, action: str, args: dict) -> dict:
        """Perform one action on the element at `locator`. Returns {"detail": ...}. Raise AdapterError on failure."""
        raise NotImplementedError

    def read(self, target: Target, locator: str, node: dict) -> dict:
        """Read the element's current state (value, toggle, selection, text) freshly from the program."""
        raise NotImplementedError

    def files_written(self, target: Target, action: str, args: dict) -> list[str]:
        """Files this action is known to change (backed up first). Most UI actions: none known."""
        return []
