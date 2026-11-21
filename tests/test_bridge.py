"""In-process bridges, CIG side: the protocol (token, loopback only) and the whole engine path over a fake bridge
that answers like the real ones (tree in CIG's node format, act by bridge path)."""
import json
import os
import secrets
import socket
import threading

import pytest

from cig.adapters import bridge
from cig.adapters.base import AdapterError
from cig.engine import Engine

STATE = {"combo": "Alpha", "checked": False}


def fake_tree():
    return [{"control_type": "Window", "name": "Fake app", "patterns": ["Window"], "bridge": "w0", "children": [
        {"control_type": "CheckBox", "name": "A checkbox", "patterns": ["Toggle"], "bridge": "w0/0",
         "toggle_state": "On" if STATE["checked"] else "Off"},
        {"control_type": "ComboBox", "name": "Choice", "patterns": ["Selection", "ExpandCollapse"], "bridge": "w0/1",
         "value": STATE["combo"], "children": [
            {"control_type": "ListItem", "name": n, "patterns": ["SelectionItem"], "bridge": f"w0/1/i{i}",
             "selected": n == STATE["combo"]} for i, n in enumerate(("Alpha", "Beta", "Gamma"))]},
        {"control_type": "Edit", "name": "Password field", "patterns": ["Value"], "is_password": True,
         "bridge": "w0/2"}]}]


@pytest.fixture
def fake_bridge():
    token = secrets.token_hex(16)
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(4)
    seen = []

    def serve():
        while True:
            try:
                conn, _ = srv.accept()
            except OSError:
                return
            with conn, conn.makefile("rwb") as fh:
                for raw in fh:
                    req = json.loads(raw)
                    if req.get("token") != token:
                        out = {"ok": False, "error": "bad token"}
                    elif req["cmd"] == "tree":
                        out = {"ok": True, "windows": fake_tree()}
                    elif req["cmd"] == "act":
                        a = req["args"]
                        seen.append(a)
                        if a["action"] == "choose":
                            STATE["combo"] = a["option"]
                        elif a["action"] == "set_checked":
                            STATE["checked"] = a["checked"]
                        out = {"ok": True}
                    else:
                        out = {"ok": True}
                    fh.write((json.dumps(out) + "\n").encode())
                    fh.flush()
    threading.Thread(target=serve, daemon=True).start()
    info = {"host": "127.0.0.1", "port": srv.getsockname()[1], "token": token, "pid": os.getpid(), "bridge": "fake"}
    bridge.register(os.getpid(), info)
    STATE.update(combo="Alpha", checked=False)
    yield info, seen
    bridge.BRIDGES.pop(os.getpid(), None)
    srv.close()


def test_token_is_required(fake_bridge):
    info, _ = fake_bridge
    with pytest.raises(AdapterError):
        bridge.call(dict(info, token="wrong"), "tree")
    assert bridge.call(info, "tree")["windows"][0]["name"] == "Fake app"


def test_a_bridge_off_loopback_is_refused():
    with pytest.raises(AdapterError):
        bridge.register(99999, {"host": "10.0.0.5", "port": 1, "token": "x"})


def test_choose_and_toggle_through_the_engine(fake_bridge, idle):
    idle(120)
    info, seen = fake_bridge
    e = Engine([bridge.BridgeAdapter()])
    e.register_launch(os.getpid(), "python.exe")
    app = str(os.getpid())
    acts = e.actions(app)["actions"]
    combo = next(a for a in acts if a["action"] == "choose")
    assert combo["input_schema"]["properties"]["option"]["enum"] == ["Alpha", "Beta", "Gamma"]
    r = e.do(app, combo["id"], {"option": "Beta"})
    assert r["ok"] and r["verified"] is True and seen[-1] == {"path": "w0/1", "action": "choose", "option": "Beta"}
    chk = next(a for a in acts if a["action"] == "set_checked")
    assert e.do(app, chk["id"], {"checked": True})["verified"] is True
    assert not any(a["action"] == "set_text" and "Password" in a["label"] for a in acts)   # still a password field


def test_a_program_cig_did_not_launch_is_refused_even_through_a_bridge(fake_bridge, idle):
    idle(120)
    e = Engine([bridge.BridgeAdapter()])                   # not registered as launched
    app = str(os.getpid())
    chk = next(a for a in e.actions(app)["actions"] if a["action"] == "set_checked")
    assert e.do(app, chk["id"], {"checked": True}, confirm="yes")["refused"]
