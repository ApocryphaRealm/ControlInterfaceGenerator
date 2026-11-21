"""Three faults the Tooling agent's tool survey found (2026-11-20): the launch folder, a button that closes the whole
program, and start-up questions that are standard dialogs but not modal."""
import subprocess

from cig import launch, rules
from cig.adapters.base import AdapterError
from cig.adapters.fixture import FixtureAdapter
from cig.engine import Engine

APP = "fixture:editor"


def test_a_program_starts_in_its_own_folder(idle, tmp_path, monkeypatch):
    idle(60)
    exe = tmp_path / "tool" / "Tool.exe"
    exe.parent.mkdir()
    exe.write_bytes(b"MZ")
    seen = {}

    class FakePopen:
        def __init__(self, argv, **kw):
            seen.update(kw)
    monkeypatch.setattr(subprocess, "Popen", FakePopen)
    r = launch.launch(str(exe), [], wait_s=0.2)
    assert seen["cwd"] == str(exe.parent)          # never CIG's own folder
    assert r["cwd"] == str(exe.parent)


class ExitsOnPress(FixtureAdapter):
    """Pressing the button ends the program: afterwards nothing can be read."""
    def __init__(self):
        super().__init__()
        self.gone = False

    def execute(self, target, locator, node, action, args):
        r = super().execute(target, locator, node, action, args)
        self.gone = True
        return r

    def read(self, target, locator, node):
        if self.gone:
            raise AdapterError("editor.exe (pid 4242) has no visible window")
        return super().read(target, locator, node)


def test_a_button_that_closes_the_whole_program_is_a_success(idle, monkeypatch):
    idle(120)
    import cig.engine as eng_mod
    monkeypatch.setattr(eng_mod, "_process_alive", lambda pid: False)
    e = Engine([ExitsOnPress()])
    e.register_launch(4242, "editor.exe")
    aid = next(a["id"] for a in e.actions(APP)["actions"] if a["action"] == "set_checked")
    r = e.do(APP, aid, {"checked": True})
    assert r["ok"] and r.get("program_exited") is True


def test_a_failed_read_back_while_the_program_still_runs_is_still_a_failure(idle, monkeypatch):
    idle(120)
    import cig.engine as eng_mod
    monkeypatch.setattr(eng_mod, "_process_alive", lambda pid: True)
    e = Engine([ExitsOnPress()])
    e.register_launch(4242, "editor.exe")
    aid = next(a["id"] for a in e.actions(APP)["actions"] if a["action"] == "set_checked")
    r = e.do(APP, aid, {"checked": True})
    assert not r["ok"] and "read-back failed" in r["reason"]


def test_a_non_modal_standard_dialog_can_be_answered_once():
    q = {"control_type": "Window", "name": "Select Game Mode", "class_name": "#32770", "patterns": ["Window"],
         "children": [{"control_type": "Button", "name": "Skyrim SE", "patterns": ["Invoke"]},
                      {"control_type": "Button", "name": "Cancel", "patterns": ["Invoke"]}]}
    acts = [a for a in rules.actions_for([q]) if a["action"] == "answer_dialog"]
    assert len(acts) == 1 and acts[0]["input_schema"]["properties"]["button"]["enum"] == ["Skyrim SE", "Cancel"]
    modal = dict(q, is_modal=True)
    assert len([a for a in rules.actions_for([modal]) if a["action"] == "answer_dialog"]) == 1   # not twice
