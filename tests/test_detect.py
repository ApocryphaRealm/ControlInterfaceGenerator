"""Detector scoring on recorded evidence (no live process), the library's own validity, and the hold-screen rule."""
import json

import jsonschema
import pytest

from cig import config, detect, presence
from cig.policy import Policy, Request, decide, WRITE


def lib_schema():
    return json.loads((config.LIBRARY_DIR / "schema" / "framework.schema.json").read_text(encoding="utf-8"))


def test_every_library_entry_validates():
    s = lib_schema()
    files = sorted((config.LIBRARY_DIR / "frameworks").glob("*.json"))
    assert len(files) >= 15
    for p in files:
        jsonschema.validate(json.loads(p.read_text(encoding="utf-8")), s)


def test_control_type_baseline_covers_the_rules():
    ct = json.loads((config.LIBRARY_DIR / "uia" / "control-types.json").read_text(encoding="utf-8"))["control_types"]
    rules = json.loads((config.LIBRARY_DIR / "rules" / "uia.json").read_text(encoding="utf-8"))["rules"]
    for r in rules:
        for t in r["when"].get("control_type", []):
            assert t in ct, f"rule {r['id']} names a control type the spec does not have: {t}"
    assert "Toggle" in ct["RadioButton"]["not_supported"]


@pytest.mark.parametrize("v,cond,ok", [("3.1.7.0", ">=3", True), ("2.9.2603.18001", ">=3", False),
                                       ("2.9.2603.18001", "<3", True), ("6.7.1.0", ">=6.7", True), (None, ">=3", False)])
def test_version_ok(v, cond, ok):
    assert detect.version_ok(v, cond) is ok


def ev(**kw):
    base = {"exe": "", "modules": [], "window_classes": [], "files_beside": [], "exe_strings": {}, "pe_subsystem": "gui",
            "uia": {"framework_ids": {}}}
    base.update(kw)
    return base


def test_rank_qt6_from_mo2_evidence():
    r = detect.rank(ev(modules=[r"C:\MO2\Qt6Core.dll"], window_classes=["Qt671QWindowIcon"],
                       uia={"framework_ids": {"Qt": 11}, "score": 0.82}))
    assert r["framework"] == "qt6" and r["adapters"][0]["name"] == "uia"


def test_rank_electron_beats_chromium_and_win32():
    r = detect.rank(ev(window_classes=["Chrome_WidgetWin_1", "Chrome_RenderWidgetHostHWND"],
                       files_beside=["resources/app.asar"], exe_strings={"x": "Electron/44.10.2"}))
    assert r["framework"] == "electron" and r["framework_version"] == "44.10.2"
    assert r["adapters"][0]["name"] == "cdp"
    assert next(x for x in r["ranked"] if x["framework"] == "chromium")["generic"] is True


def test_rank_console_and_winforms():
    assert detect.rank(ev(pe_subsystem="console", window_classes=["ConsoleWindowClass"]))["framework"] == "console"
    assert detect.rank(ev(window_classes=["WindowsForms10.Window.8.app.0.141b42a_r6_ad1"]))["framework"] == "winforms"


def test_rank_unknown():
    assert detect.rank(ev())["framework"] == "unknown"


def test_hold_screen_refuses_writes_but_not_reads(idle, monkeypatch):
    idle(120)
    monkeypatch.setenv("CIG_FOREGROUND_PID", "777")
    monkeypatch.setenv("CIG_FOREGROUND_EXE", "SkyrimSE.exe")
    p, pol = presence.read(), Policy.load()
    d = decide(Request(app="notepad.exe", action="launch", kind=WRITE, confirm="yes"), p, pol)
    assert not d.allowed and "holds the screen" in d.reason
    assert decide(Request(app="notepad.exe", action="get_text", kind="read"), p, pol).allowed


def test_rank_delphi_vcl_from_window_class_or_exe_strings():
    assert detect.rank(ev(window_classes=["TfrmMain", "TButton"]))["framework"] == "delphi-vcl"
    assert detect.rank(ev(exe_strings={"a": "Embarcadero", "b": "TApplication"}))["framework"] == "delphi-vcl"


def test_rank_delphi_fmx():
    assert detect.rank(ev(window_classes=["FMTfrmMain"], exe_strings={"a": "FMX.Forms"}))["framework"] == "delphi-fmx"


def test_rank_avalonia_from_dll_class_or_single_file():
    assert detect.rank(ev(modules=[r"C:\App\Avalonia.Base.dll"]))["framework"] == "avalonia"
    assert detect.rank(ev(window_classes=["Avalonia-5f3c2e1a-0000"], exe_strings={"a": "Avalonia.Base"}))[
        "framework"] == "avalonia"


def test_rank_tk():
    r = detect.rank(ev(window_classes=["TkTopLevel", "TkChild"], modules=[r"C:\Py\DLLs\tk86t.dll"]))
    assert r["framework"] == "tk" and r["adapters"][0]["name"] == "uia"
