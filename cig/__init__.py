"""Control Interface Generator (CIG).

Lets AI agents operate desktop programs headlessly: detect what framework a program is built on, look up what that
framework exposes for automation (the capability library), generate named typed operations, and serve them over MCP.
"""
from pathlib import Path as _P

try:
    __version__ = (_P(__file__).resolve().parent.parent / "VERSION").read_text(encoding="utf-8").strip()
except OSError:
    __version__ = "unknown"
