"""cig - the command line (plan section 5): the MCP server and a few read-only helpers.

  cig serve                 run the MCP server on stdio (what Claude Code / Claude Desktop start)
  cig detect <target>       framework + version + ranked adapters for a running program (pid, exe name, title)
  cig apps                  programs with windows CIG can see, with a quick framework guess
  cig tree <app> [depth]    the element tree CIG would act on (read-only)
  cig log [n]               the last n entries of CIG's action log
  cig version               version and where CIG keeps its data
Everything except 'serve' only reads; the safety layer applies inside the server.
"""
from __future__ import annotations

import json
import sys


def _print(obj) -> None:
    sys.stdout.write(json.dumps(obj, indent=1, ensure_ascii=False, default=str) + "\n")


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    cmd = args[0] if args else "help"
    if cmd == "serve":
        from .server import main as serve
        serve()
        return 0
    if cmd == "detect" and len(args) >= 2:
        from .detect import detect
        _print(detect(args[1]))
        return 0
    if cmd == "apps":
        from .detect import list_apps
        _print(list_apps())
        return 0
    if cmd == "tree" and len(args) >= 2:
        from .server import engine
        _print(engine().tree(args[1], int(args[2]) if len(args) > 2 else 12))
        return 0
    if cmd == "log":
        from . import actionlog
        _print(actionlog.tail(int(args[1]) if len(args) > 1 else 20))
        return 0
    if cmd == "version":
        from . import __version__, config
        _print({"cig": __version__, "library": str(config.LIBRARY_DIR), "data": str(config.home()),
                "frozen": bool(getattr(sys, "frozen", False))})
        return 0
    sys.stdout.write(__doc__ or "")
    return 0 if cmd in ("help", "-h", "--help") else 2


if __name__ == "__main__":
    sys.exit(main())
