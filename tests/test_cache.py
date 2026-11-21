"""Per-app cache: ids survive a server restart; a new program version starts clean; popup menus become paths."""
from cig import appcache, engine as engine_mod
from cig.adapters.fixture import FixtureAdapter
from cig.engine import Engine

APP = "fixture:editor"


def first_id(e, action, label):
    return next(a["id"] for a in e.actions(APP)["actions"] if a["action"] == action and f"'{label}'" in a["label"])


def test_id_from_an_earlier_run_resolves_after_restart(idle):
    idle(60)
    e1 = Engine([FixtureAdapter()])
    aid = first_id(e1, "set_checked", "Word wrap")
    appcache._last_save.clear()
    e2 = Engine([FixtureAdapter()])              # a new server: no in-memory snapshot
    e2.register_launch(4242, "editor.exe")
    r = e2.do(APP, aid, {"checked": True})
    assert r["ok"] and r["verified"] is True


def test_renamed_element_found_from_cache_after_restart(idle):
    idle(60)
    e1 = Engine([FixtureAdapter()])
    aid = first_id(e1, "set_checked", "Word wrap")
    e2 = Engine([FixtureAdapter()])
    e2.register_launch(4242, "editor.exe")
    fx = e2.adapters[0]
    fx.resolve(APP)
    box = next(c for c in fx.state["editor"]["windows"][0]["children"] if c.get("name") == "Word wrap")
    box["automation_id"], box["name"] = "", "Zeilenumbruch"
    r = e2.do(APP, aid, {"checked": True})
    assert r["ok"], r["reason"]
    from cig import actionlog
    assert actionlog.tail(1)[0]["resolved"].startswith("fingerprint")


def test_cache_key_carries_version():
    snap = {"known": {"aa": {"locator": "L", "fingerprint": {"control_type": "Button"}}}, "menu_paths": ["File"]}
    appcache.save("app.exe|1.0|uia", snap, force=True)
    assert "aa" in appcache.load_known("app.exe|1.0|uia")
    assert appcache.load_known("app.exe|2.0|uia") == {}
    assert appcache.load_menu_paths("app.exe|1.0|uia") == ["File"]


def test_popup_menu_items_become_paths():
    windows = [{"control_type": "Window", "name": "Main", "children": [
        {"control_type": "MenuBar", "name": "Application", "children": [
            {"control_type": "MenuItem", "name": "&File"}]}]},
        {"control_type": "Window", "name": "", "children": [
            {"control_type": "Menu", "name": "File", "children": [
                {"control_type": "MenuItem", "name": "Open..."}, {"control_type": "MenuItem", "name": "Save"}]}]}]
    paths = engine_mod._popup_menu_paths(windows, {"&File"})
    assert paths == {"&File/Open...", "&File/Save"}
