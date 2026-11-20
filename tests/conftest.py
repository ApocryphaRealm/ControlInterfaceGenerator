import json
import os
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

NOW = 1_800_000_000.0


@pytest.fixture(autouse=True)
def seams(tmp_path, monkeypatch):
    """Every test runs against its own home, its own presence file and a fixed clock - never the real machine."""
    monkeypatch.setenv("CIG_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CIG_FIXTURES", str(REPO / "tests" / "fixtures"))
    monkeypatch.setenv("CIG_OWNER_REAL_INPUT_FILE", str(tmp_path / "owner-real-input.json"))
    monkeypatch.setenv("CIG_NOW", str(NOW))
    monkeypatch.setenv("CIG_FOREGROUND_PID", "none")
    monkeypatch.setenv("CIG_SYSTEM_IDLE_MIN", "none")
    monkeypatch.setenv("CIG_POLICY", str(REPO / "config" / "policy.json"))
    yield tmp_path


def set_idle(tmp_path, minutes, watcher_alive=True):
    data = {"last_real_input_epoch": NOW - minutes * 60,
            "watcher_alive_epoch": NOW - (30 if watcher_alive else 3600)}
    (tmp_path / "owner-real-input.json").write_text(json.dumps(data), encoding="utf-8")


@pytest.fixture
def idle(seams):
    return lambda minutes, watcher_alive=True: set_idle(seams, minutes, watcher_alive)
