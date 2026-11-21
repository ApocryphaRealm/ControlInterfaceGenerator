"""CDP adapter, offline: AX tree -> nodes -> the same rules; loopback only; no CDP launch without a separate profile."""
import pytest

from cig import launch, rules
from cig.adapters import cdp
from cig.adapters.base import AdapterError


def ax(nid, role, name="", parent=None, kids=(), props=(), value=None, ignored=False, backend=None):
    n = {"nodeId": str(nid), "role": {"value": role}, "name": {"value": name}, "childIds": [str(k) for k in kids],
         "properties": [{"name": k, "value": {"value": v}} for k, v in props], "ignored": ignored,
         "backendDOMNodeId": backend or nid}
    if parent is not None:
        n["parentId"] = str(parent)
    if value is not None:
        n["value"] = {"value": value}
    return n


AX = [
    ax(1, "RootWebArea", "Vortex", kids=[2]),
    ax(2, "generic", "", parent=1, kids=[3, 4, 5, 6, 7], ignored=True),
    ax(3, "button", "Settings", parent=2),
    ax(4, "switch", "Enable desktop notifications", parent=2, props=[("checked", "true")]),
    ax(5, "textbox", "Search", parent=2, value="abc"),
    ax(6, "dialog", "Confirm", parent=2, kids=[8, 9], props=[("modal", True)]),
    ax(7, "button", "Disabled", parent=2, props=[("disabled", True)]),
    ax(8, "button", "Apply", parent=6),
    ax(9, "button", "Cancel", parent=6),
]


def nodes():
    return [{"control_type": "Window", "name": "Vortex", "patterns": ["Window"], "children": cdp.ax_to_nodes(AX, "P1")}]


def test_ax_tree_becomes_uia_style_nodes():
    doc = nodes()[0]["children"][0]
    assert doc["control_type"] == "Document"
    kinds = {(c["control_type"], c.get("name")) for c in doc["children"]}        # the ignored 'generic' is hoisted
    assert ("Button", "Settings") in kinds and ("CheckBox", "Enable desktop notifications") in kinds
    sw = next(c for c in doc["children"] if c.get("name") == "Enable desktop notifications")
    assert sw["toggle_state"] == "On" and sw["patterns"] == ["Toggle"] and sw["cdp"]["backend"] == 4
    tb = next(c for c in doc["children"] if c.get("name") == "Search")
    assert tb["value"] == "abc" and tb["is_read_only"] is False


def test_same_rules_generate_actions_over_the_ax_tree():
    acts = {(a["action"], a["label"].split("'")[1]) for a in rules.actions_for(nodes())}
    assert ("invoke", "Settings") in acts
    assert ("set_checked", "Enable desktop notifications") in acts
    assert ("set_text", "Search") in acts
    assert ("answer_dialog", "Confirm") in acts
    assert not any(lbl == "Disabled" for _a, lbl in acts)
    dlg = next(a for a in rules.actions_for(nodes()) if a["action"] == "answer_dialog")
    assert dlg["input_schema"]["properties"]["button"]["enum"] == ["Apply", "Cancel"]


def test_debugger_url_must_be_loopback():
    with pytest.raises(AdapterError):
        cdp.CdpSession("ws://192.168.1.5:9222/devtools/page/x")


def test_cdp_launch_without_a_separate_profile_is_refused(idle):
    idle(60)
    r = launch.launch(r"C:\Program Files\Vortex\Vortex.exe", [], cdp=True)
    assert r["refused"] and "profile_flag" in r["reason"]


def test_password_inputs_are_marked_so_set_secret_applies():
    """The AX tree calls <input type=password> a textbox; the DOM marks it, and the deny rule takes over."""
    nodes = cdp.ax_to_nodes([ax(1, "RootWebArea", "p", kids=[2]), ax(2, "textbox", "Password field", parent=1,
                                                                      value="hunter2", backend=77)], "P")
    cdp.mark_passwords(nodes, {77})
    pw = nodes[0]["children"][0]
    assert pw["is_password"] is True and "value" not in pw
    acts = rules.actions_for([{"control_type": "Window", "name": "p", "children": nodes}])
    assert {a["action"] for a in acts if "Password" in a["label"]} == {"set_secret"}


def test_radio_state_comes_from_checked():
    nodes = cdp.ax_to_nodes([ax(1, "RootWebArea", "p", kids=[2]), ax(2, "radio", "Radio one", parent=1,
                                                                      props=[("checked", "true")])], "P")
    assert nodes[0]["children"][0]["selected"] is True
