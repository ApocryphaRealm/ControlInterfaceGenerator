"""System side-effect guards (2026-11-20: a test Vortex on its own data folder took over the nxm:// handler)."""
import subprocess

from cig import guards

SCRATCH = r"HKCU\Software\CIG-test-guard"


def test_vortex_side_effect_guard_is_known():
    assert r"HKCU\Software\Classes\nxm" in guards.keys_for(r"C:\Program Files\Vortex\Vortex.exe")
    assert guards.keys_for("notepad.exe") == []


def test_guard_roundtrip_on_a_scratch_key(monkeypatch):
    """take -> the program changes the key -> restore puts it back exactly (a scratch key, never a real one)."""
    subprocess.run(["reg", "add", SCRATCH, "/v", "x", "/d", "before", "/f"], capture_output=True)
    try:
        monkeypatch.setattr(guards, "keys_for", lambda exe: [SCRATCH])
        rec = guards.take("scratch.exe", "t1")
        subprocess.run(["reg", "add", SCRATCH, "/v", "x", "/d", "CHANGED", "/f"], capture_output=True)
        r = guards.restore("t1")
        assert rec and r["all_restored"]
        q = subprocess.run(["reg", "query", SCRATCH, "/v", "x"], capture_output=True, text=True).stdout
        assert "before" in q and "CHANGED" not in q
        assert "t1" not in guards.pending()
    finally:
        subprocess.run(["reg", "delete", SCRATCH, "/f"], capture_output=True)


def test_guard_removes_a_key_the_program_created(monkeypatch):
    subprocess.run(["reg", "delete", SCRATCH, "/f"], capture_output=True)
    monkeypatch.setattr(guards, "keys_for", lambda exe: [SCRATCH])
    guards.take("scratch.exe", "t2")
    subprocess.run(["reg", "add", SCRATCH, "/v", "x", "/d", "new", "/f"], capture_output=True)
    r = guards.restore("t2")
    assert r["all_restored"]
    assert subprocess.run(["reg", "query", SCRATCH], capture_output=True).returncode != 0
