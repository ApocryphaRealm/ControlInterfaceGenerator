"""The whole path through the meta tools, on the fixture adapter, plus a real stdio MCP handshake."""
import asyncio
import hashlib
import json
import os
import sys

import pytest

from cig import actionlog, server
from cig.adapters.fixture import FixtureAdapter
from cig.engine import Engine

from conftest import REPO

APP = "fixture:editor"


@pytest.fixture
def eng():
    e = Engine([FixtureAdapter()])
    e.register_launch(4242, "editor.exe")          # the fixture program counts as started by cig_launch
    server.set_engine(e)
    yield e
    server.set_engine(None)


def act(eng, action, label):
    for a in eng.actions(APP)["actions"]:
        if a["action"] == action and f"'{label}'" in a["label"]:
            return a["id"]
    raise AssertionError(f"no {action} on {label}")


def body_value(eng):
    t = eng.tree(APP)["elements"]
    return next(r for r in t if r["name"] == "Text editor")["value"]


def empty_body(eng):
    fx = eng.adapters[0]
    fx.resolve(APP)
    next(c for c in fx.state["editor"]["windows"][0]["children"] if c.get("name") == "Text editor")["value"] = ""


def test_set_text_when_away_is_done_and_verified(eng, idle):
    idle(10)
    empty_body(eng)
    r = server.cig_do(APP, act(eng, "set_text", "Text editor"), {"text": "written by CIG"})
    assert r["ok"] and r["verified"] is True
    assert r["changed"]["before"]["value"] == "" and r["changed"]["after"]["value"] == "written by CIG"
    assert body_value(eng) == "written by CIG"
    assert actionlog.tail(1)[0]["log_id"] == r["log_id"]


def test_set_text_while_active_is_refused_and_changes_nothing(eng, idle):
    idle(1)
    r = server.cig_do(APP, act(eng, "set_checked", "Word wrap"), {"checked": True})
    assert not r["ok"] and r["refused"] and r["status"] == "confirm_required"
    assert next(x for x in eng.tree(APP)["elements"] if x["name"] == "Word wrap")["toggle_state"] == "Off"
    assert actionlog.tail(1)[0]["refused"] is True


def test_dry_run_changes_nothing(eng, idle):
    idle(10)
    fx = REPO / "tests" / "fixtures" / "editor.json"
    h0 = hashlib.sha256(fx.read_bytes()).hexdigest()
    r = server.cig_do(APP, act(eng, "set_checked", "Word wrap"), {"checked": True}, dry_run=True)
    assert r["ok"] and r["status"] == "dry_run" and r["preview"]["before"]["toggle_state"] == "Off"
    assert next(x for x in eng.tree(APP)["elements"] if x["name"] == "Word wrap")["toggle_state"] == "Off"
    assert hashlib.sha256(fx.read_bytes()).hexdigest() == h0


def test_destructive_dialog_answer_needs_confirm(eng, idle):
    idle(60)
    aid = act(eng, "answer_dialog", "Save changes?")
    r = server.cig_do(APP, aid, {"button": "Don't Save"})
    assert r["refused"] and r["status"] == "confirm_required" and r["preview"]["kind"] == "destructive"
    r2 = server.cig_do(APP, aid, {"button": "Don't Save"}, confirm="the owner said discard it")
    assert r2["ok"] and r2["verified"] is True
    assert not any(row["name"] == "Save changes?" for row in eng.tree(APP)["elements"])
    assert actionlog.tail(1)[0]["confirm"] == "the owner said discard it"


def test_non_destructive_dialog_answer_is_a_write(eng, idle):
    idle(60)
    r = server.cig_do(APP, act(eng, "answer_dialog", "Save changes?"), {"button": "Cancel"})
    assert r["ok"]


def test_delete_button_needs_confirm_in_any_language(eng, idle):
    idle(60)
    for label in ("&Delete all", "Löschen"):
        r = server.cig_do(APP, act(eng, "invoke", label))
        assert r["refused"] and r["status"] == "confirm_required", label


def test_password_field_never_set_and_never_logged(eng, idle):
    idle(60)
    r = server.cig_do(APP, act(eng, "set_secret", "Password"), {"text": "hunter2"}, confirm="yes")
    assert r["refused"] and "deny" in r["reason"]
    log_text = (actionlog.config.log_file()).read_text(encoding="utf-8")
    assert "hunter2" not in log_text


def test_bad_args_rejected_by_generated_schema(eng, idle):
    idle(60)
    r = server.cig_do(APP, act(eng, "answer_dialog", "Save changes?"), {"button": "Maybe"})
    assert not r["ok"] and "bad args" in r["reason"]


def test_stale_element_is_refused_not_guessed(eng, idle):
    idle(60)
    aid = act(eng, "set_checked", "Word wrap")
    main = eng.adapters[0].state["editor"]["windows"][0]
    main["children"] = [c for c in main["children"] if c.get("name") != "Word wrap"]
    r = server.cig_do(APP, aid, {"checked": True})
    assert r["refused"] and "stale" in r["reason"]


def test_renamed_element_reresolved_by_fingerprint(eng, idle):
    idle(60)
    aid = act(eng, "set_checked", "Word wrap")
    box = next(c for c in eng.adapters[0].state["editor"]["windows"][0]["children"] if c.get("name") == "Word wrap")
    box["automation_id"] = ""             # locator now changes ...
    box["name"] = "Zeilenumbruch"         # ... and so does the name (a language switch)
    r = server.cig_do(APP, aid, {"checked": True})
    assert r["ok"] and str(r.get("verified")) == "True"
    assert actionlog.tail(1)[0]["resolved"].startswith("fingerprint")


def test_unknown_app_and_unknown_id(eng):
    assert not server.cig_tree("nothing-like-this.exe")["ok"]
    assert server.cig_do(APP, "deadbeef.invoke")["refused"]


def test_status_and_log_tools(eng, idle):
    idle(7)
    s = server.cig_status()
    assert s["presence"]["source"] == "watcher" and s["presence"]["idle_min"] == 7.0
    assert "set_secret" in s["policy"]["deny_actions"]
    assert server.cig_log(5)["ok"]


def test_stdio_mcp_handshake_lists_the_meta_tools(tmp_path):
    """Start the real server process over stdio and talk MCP to it."""
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    env = dict(os.environ)
    params = StdioServerParameters(command=sys.executable, args=[str(REPO / "cig_server.py")], env=env)

    async def run():
        async with stdio_client(params) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                tools = {t.name: t for t in (await s.list_tools()).tools}
                res = await s.call_tool("cig_actions", {"app": APP})
                return tools, json.loads(res.content[0].text)

    tools, acts = asyncio.run(asyncio.wait_for(run(), 60))
    for name in ("cig_status", "cig_apps", "cig_detect", "cig_launch", "cig_tree", "cig_actions", "cig_do",
                 "cig_read", "cig_wait", "cig_see", "cig_log", "cig_undo"):
        assert name in tools, name
    assert tools["cig_tree"].annotations.readOnlyHint is True
    assert tools["cig_do"].annotations.destructiveHint is True
    assert acts["ok"] and any(a["action"] == "set_text" for a in acts["actions"])


def test_tonights_case_restored_document_is_never_written_even_confirmed(eng, idle):
    """Notepad, 2026-11-20 19:08: CIG launched Notepad, Notepad restored a session tab holding the owner's document,
    and a set_text replaced it. A document CIG did not write is refused - confirm cannot override (Main Agent's order)."""
    idle(120)
    for confirm in (None, "yes, replace it"):
        r = server.cig_do(APP, act(eng, "set_text", "Text editor"), {"text": "CIG M2 proof"}, confirm=confirm)
        assert r["refused"] and r["status"] == "refused" and "did not write" in r["reason"]
    assert body_value(eng) == "hello"


def test_window_cig_did_not_open_is_never_written_even_confirmed(idle):
    idle(120)
    e = Engine([FixtureAdapter()])                 # nothing registered as launched
    server.set_engine(e)
    try:
        r = server.cig_do(APP, act(e, "set_checked", "Word wrap"), {"checked": True}, confirm="yes")
        assert r["refused"] and "did not open" in r["reason"]
        assert server.cig_tree(APP)["ok"]          # reads stay allowed
    finally:
        server.set_engine(None)


def test_cig_may_replace_its_own_text(eng, idle):
    idle(120)
    empty_body(eng)
    aid = act(eng, "set_text", "Text editor")
    assert server.cig_do(APP, aid, {"text": "first"})["ok"]
    r = server.cig_do(APP, aid, {"text": "second"})
    assert r["ok"] and r["verified"] is True and body_value(eng) == "second"


def test_filling_an_empty_field_is_a_plain_write(eng, idle):
    idle(120)
    main = eng.adapters[0]
    main.resolve(APP)
    body = next(c for c in main.state["editor"]["windows"][0]["children"] if c.get("name") == "Text editor")
    body["value"] = ""
    r = server.cig_do(APP, act(eng, "set_text", "Text editor"), {"text": "new"})
    assert r["ok"] and r["verified"] is True
