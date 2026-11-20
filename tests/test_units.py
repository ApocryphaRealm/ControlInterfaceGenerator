"""Unit tests: classification, locators, rules, fixtures, log, backups."""
import json

import jsonschema
import pytest

from cig import actionlog, backups, classify, fixtures, locator, rules
from cig.policy import DESTRUCTIVE, WRITE, READ


@pytest.mark.parametrize("text", ["&Delete all", "Löschen", "Don't Save", "Don’t save", "删除文件", "Remove mod",
                                  "Supprimer", "Не сохранять"])
def test_destructive_words(text):
    assert classify.classify("invoke", "write", [text])[0] == DESTRUCTIVE


@pytest.mark.parametrize("text", ["Save", "Open...", "Undelete", "Formatting", "Clearance sale", "OK"])
def test_harmless_words(text):
    assert classify.classify("invoke", "write", [text])[0] == WRITE


def test_reads_never_escalate():
    assert classify.classify("get_text", "read", ["Delete"])[0] == READ


def test_locator_segments():
    a = {"control_type": "Button", "automation_id": "OkBtn", "name": "OK"}
    b = {"control_type": "Button", "name": "Go"}
    c = {"control_type": "Button", "name": "Go"}
    d = {"control_type": "Button", "automation_id": "1001", "name": "Go"}   # numeric id = not stable
    sibs = [a, b, c, d]
    assert locator.segment(a, sibs) == 'Button[aid="OkBtn"]'
    assert locator.segment(b, sibs) == 'Button[name="Go"][0]'
    assert locator.segment(c, sibs) == 'Button[name="Go"][1]'
    assert locator.segment(d, sibs) == 'Button[name="Go"][2]'


def test_fingerprint_score():
    n = {"control_type": "Edit", "name": "Path", "patterns": ["Value"], "rect": [10, 10, 100, 30]}
    f1 = locator.fingerprint(n, ["Main", "Pane"], [0, 0, 500, 500])
    renamed = dict(n, name="Pfad")
    f2 = locator.fingerprint(renamed, ["Main", "Pane"], [0, 0, 500, 500])
    assert locator.fingerprint_score(f1, f2) == 0.8           # everything but the name
    other = locator.fingerprint(dict(n, control_type="Button"), ["Main", "Pane"], [0, 0, 500, 500])
    assert locator.fingerprint_score(f1, other) == 0.0


def test_fixture_validates():
    data = fixtures.load(fixtures.config.REPO / "tests" / "fixtures" / "editor.json")
    assert data["app"]["exe"] == "editor.exe"
    with pytest.raises(jsonschema.ValidationError):
        fixtures.validate({"cig_fixture": 1, "app": {}, "windows": []})


def test_fixture_save_roundtrip(tmp_path):
    p = fixtures.save({"app": {"exe": "x.exe"}, "windows": [{"control_type": "Window", "name": "X"}]},
                      tmp_path / "x.json")
    assert fixtures.load(p)["cig_fixture"] == 1


def test_rules_generate_the_expected_actions():
    data = fixtures.load(fixtures.config.REPO / "tests" / "fixtures" / "editor.json")
    acts = rules.actions_for(data["windows"])
    by = {(a["action"], a["label"].split("'")[1]) for a in acts}
    assert ("set_text", "Text editor") in by
    assert ("get_text", "Text editor") in by
    assert ("set_checked", "Word wrap") in by
    assert ("set_secret", "Password") in by
    assert ("invoke", "&Delete all") in by
    assert not any("Disabled thing" in a["label"] for a in acts)
    dlg = next(a for a in acts if a["action"] == "answer_dialog")
    assert dlg["input_schema"]["properties"]["button"]["enum"] == ["Save", "Don't Save", "Cancel"]
    menu = next(a for a in acts if a["action"] == "menu")
    assert "File/Open..." in menu["input_schema"]["properties"]["path"]["examples"]
    assert len({a["id"] for a in acts}) == len(acts)


def test_log_redacts_and_tails():
    actionlog.write({"action": "x", "args": {"password": "hunter2", "text": "ok"}})
    last = actionlog.tail(1)[0]
    assert last["args"]["password"] == "<redacted>" and last["args"]["text"] == "ok"
    assert "hunter2" not in actionlog.config.log_file().read_text(encoding="utf-8")


def test_backup_and_undo(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("one", encoding="utf-8")
    new = tmp_path / "new.txt"
    bid = backups.take("editor.exe", "save", [str(f), str(new)])
    f.write_text("two", encoding="utf-8")
    new.write_text("created", encoding="utf-8")
    r = backups.undo(bid)
    assert r["ok"] and f.read_text(encoding="utf-8") == "one" and not new.exists()
    assert not backups.undo("../../etc")["ok"]
