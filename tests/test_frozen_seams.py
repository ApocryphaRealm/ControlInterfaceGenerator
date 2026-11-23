"""In cig.exe (frozen) the safety readings and the policy file cannot be replaced through the environment an MCP client
sets: the test seams are honoured only when CIG runs from source."""
from cig import config, presence


def test_seams_work_from_source(monkeypatch):
    monkeypatch.setattr(config, "FROZEN", False)
    monkeypatch.setenv("CIG_SYSTEM_IDLE_MIN", "999")
    monkeypatch.setenv("CIG_FOREGROUND_EXE", "x.exe")
    assert presence.system_idle_minutes() == 999.0
    assert presence.exe_of(None) == "x.exe"


def test_seams_ignored_when_frozen(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "FROZEN", True)
    for k, v in {"CIG_SYSTEM_IDLE_MIN": "999", "CIG_FOREGROUND_PID": "none", "CIG_FOREGROUND_EXE": "x.exe",
                 "CIG_NOW": "1", "CIG_POLICY": str(tmp_path / "loose.json")}.items():
        monkeypatch.setenv(k, v)
    assert config.seam("CIG_SYSTEM_IDLE_MIN") is None
    assert presence.system_idle_minutes() != 999.0
    assert presence.now() > 1
    assert presence.exe_of(None) != "x.exe"
    assert config.policy_file().name == "policy.json" and config.policy_file().parent.name == "config"


def test_no_watcher_file_or_resolver_when_frozen(monkeypatch, tmp_path):
    w = tmp_path / "w.json"
    w.write_text('{"watcher_alive_epoch": 9e9, "last_real_input_epoch": 1}', encoding="utf-8")
    monkeypatch.setattr(config, "FROZEN", True)
    monkeypatch.setenv("CIG_OWNER_REAL_INPUT_FILE", str(w))
    monkeypatch.setenv("OWNER_REAL_INPUT_FILE", str(w))
    assert config.owner_input_file() == ""
    assert presence.read().source in ("system", "unknown")
