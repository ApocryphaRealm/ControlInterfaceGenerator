"""Where CIG keeps things. Every location can be overridden by an environment variable (the test seams)."""
import functools
import os
import subprocess
import sys
from pathlib import Path

# Frozen into cig.exe (PyInstaller), the bundled library and config sit in the unpack folder (sys._MEIPASS), and the
# runtime data (logs, cache, backups) goes to %LOCALAPPDATA%/CIG - never into a temporary unpack folder.
FROZEN = bool(getattr(sys, "frozen", False))
REPO = Path(getattr(sys, "_MEIPASS", "")) if FROZEN else Path(__file__).resolve().parent.parent
LIBRARY_DIR = REPO / "library"
RESOLVER = Path(r"D:\Claude output\.MD\resolvers\resolve.py")

# Last-known locations, used only when the project resolver cannot be asked (rule 70: ask by role first).
_FALLBACK = {
    "owner-real-input": r"D:\Claude output\.MD\logs\owner-real-input.json",
}


@functools.lru_cache(maxsize=None)
def resolve_role(role: str) -> str:
    """Ask the project resolver for a role's path; fall back to the last-known path."""
    if RESOLVER.exists():
        try:
            out = subprocess.run(["py", "-3", str(RESOLVER), "find", role], capture_output=True, text=True,
                                 timeout=15, stdin=subprocess.DEVNULL)
            line = (out.stdout or "").strip().splitlines()
            if out.returncode == 0 and line and not line[0].startswith("NO SUCH ROLE"):
                return line[0].strip()
        except (OSError, subprocess.SubprocessError):
            pass
    return _FALLBACK.get(role, "")


def home() -> Path:
    """Runtime data (logs, cache, backups). Not in git."""
    default = (Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "CIG") if FROZEN else (REPO / "var")
    p = Path(os.environ.get("CIG_HOME") or default)
    p.mkdir(parents=True, exist_ok=True)
    return p


def log_file() -> Path:
    d = home() / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d / "actions.jsonl"


def cache_dir() -> Path:
    d = home() / "cache" / "apps"
    d.mkdir(parents=True, exist_ok=True)
    return d


def policy_file() -> Path:
    return Path(os.environ.get("CIG_POLICY") or (REPO / "config" / "policy.json"))


def owner_input_file() -> str:
    return (os.environ.get("CIG_OWNER_REAL_INPUT_FILE") or os.environ.get("OWNER_REAL_INPUT_FILE")
            or resolve_role("owner-real-input"))
