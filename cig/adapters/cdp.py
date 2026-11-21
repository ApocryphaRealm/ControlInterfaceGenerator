"""The Chrome DevTools Protocol adapter (plan 1.2 / 2.4, milestone M4) for Chromium and Electron programs.

CIG only speaks CDP to a program it launched itself with `--remote-debugging-port` on 127.0.0.1 and a SEPARATE data
folder (cig_launch(..., cdp=true, profile_flag=...)); it never attaches to a browser or app someone is using.

The page's accessibility tree is translated into the same node shape the UIA adapter produces, through the role map
in library/cdp/ax-roles.json, so the one rule table (library/rules/uia.json) generates the actions. Acting goes
through the page's own DOM (click(); the native value setter + input/change events, then Input.insertText as the
fallback for editors that ignore a scripted value - past mistake 8751).
"""
from __future__ import annotations

import functools
import itertools
import json
import threading
import urllib.request
from typing import Optional

import psutil
from websockets.sync.client import connect

from .. import config, locator as loc_mod
from .base import Adapter, AdapterError, Target
from ..uiawalk import secret_name

PORTS: dict[int, int] = {}            # pid -> debugging port, for programs CIG launched with cdp=true
_LOCK = threading.Lock()


def register(pid: int, port: int) -> None:
    with _LOCK:
        PORTS[int(pid)] = int(port)


@functools.lru_cache(maxsize=1)
def role_map() -> dict:
    return json.loads((config.LIBRARY_DIR / "cdp" / "ax-roles.json").read_text(encoding="utf-8"))


class CdpSession:
    def __init__(self, ws_url: str, timeout: float = 15.0):
        # loopback only (plan 2.6 item 9): refuse a debugger URL that points anywhere else
        if not ws_url.startswith(("ws://127.0.0.1:", "ws://localhost:", "ws://[::1]:")):
            raise AdapterError(f"refusing a non-loopback debugger URL: {ws_url}")
        self.ws = connect(ws_url, open_timeout=timeout, max_size=64 * 1024 * 1024)
        self.timeout = timeout
        self.ids = itertools.count(1)

    def call(self, method: str, params: Optional[dict] = None) -> dict:
        mid = next(self.ids)
        self.ws.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
        while True:
            msg = json.loads(self.ws.recv(timeout=self.timeout))
            if msg.get("id") == mid:
                if "error" in msg:
                    raise AdapterError(f"{method}: {msg['error'].get('message')}")
                return msg.get("result", {})

    def close(self):
        try:
            self.ws.close()
        except Exception:                                      # noqa: BLE001
            pass


def pages(port: int) -> list[dict]:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=5) as r:
            targets = json.loads(r.read().decode("utf-8"))
    except OSError as e:
        raise AdapterError(f"no debugger answering on 127.0.0.1:{port}: {e}") from e
    return [t for t in targets if t.get("type") == "page" and not t.get("url", "").startswith("devtools://")]


def _prop(props: list, name: str):
    for p in props or []:
        if p.get("name") == name:
            return (p.get("value") or {}).get("value")
    return None


def ax_to_nodes(ax_nodes: list[dict], page_id: str, max_nodes: int = 4000) -> list[dict]:
    """Full AX tree -> fixture-format nodes (ignored nodes hoisted away, so their children stay)."""
    rm = role_map()
    roles, skip = rm["roles"], set(rm["skip_roles"])
    by_id = {n["nodeId"]: n for n in ax_nodes}
    count = [0]

    def convert(n) -> list[dict]:
        role = ((n.get("role") or {}).get("value")) or ""
        kids = [k for cid in n.get("childIds") or [] if (k := by_id.get(cid))]
        if n.get("ignored") or role in skip:
            out = []
            for k in kids:
                out += convert(k)
            return out
        if count[0] >= max_nodes:
            return []
        count[0] += 1
        m = roles.get(role, {"control_type": "Custom", "patterns": []})
        props = n.get("properties") or []
        node: dict = {"control_type": m["control_type"], "patterns": list(m["patterns"]), "framework_id": "Chrome",
                      "cdp": {"page": page_id, "backend": n.get("backendDOMNodeId"), "role": role}}
        name = ((n.get("name") or {}).get("value")) or ""
        if name:
            node["name"] = str(name)[:200]
        if _prop(props, "disabled"):
            node["enabled"] = False
        if "Value" in node["patterns"]:
            node["value"] = str(((n.get("value") or {}).get("value")) or "")
            node["is_read_only"] = bool(_prop(props, "readonly"))
        checked = _prop(props, "checked")
        if checked is None and "Toggle" in node["patterns"]:
            checked = _prop(props, "pressed")
        if checked is not None:
            node["toggle_state"] = {"true": "On", "false": "Off", "mixed": "Indeterminate"}.get(str(checked).lower(),
                                                                                              "Off")
        sel = _prop(props, "selected")
        if sel is None and m["control_type"] in ("RadioButton", "MenuItem") and "SelectionItem" in node["patterns"]:
            sel = _prop(props, "checked")          # a radio's state is 'checked' in the AX tree (M6 probe, 2026-11-20)
            if isinstance(sel, str):
                sel = sel.lower() == "true"
        if sel is not None:
            node["selected"] = bool(sel)
        exp = _prop(props, "expanded")
        if exp is not None:
            node["expand_state"] = "Expanded" if exp else "Collapsed"
            if "ExpandCollapse" not in node["patterns"]:
                node["patterns"].append("ExpandCollapse")
        if _prop(props, "modal"):
            node["is_modal"] = True
        if "RangeValue" in node["patterns"]:
            node["range"] = {"min": _prop(props, "valuemin") or 0, "max": _prop(props, "valuemax") or 0,
                             "value": float(((n.get("value") or {}).get("value")) or 0)}
        children = []
        for k in kids:
            children += convert(k)
        if children:
            node["children"] = children
        return [node]

    roots = [n for n in ax_nodes if not n.get("parentId")]
    out = []
    for r in roots:
        out += convert(r)
    return out


def password_backends(s: "CdpSession") -> set:
    """Backend ids of password inputs. The AX tree reports <input type=password> as a plain textbox, so without
    this the set_secret deny would never fire over CDP (found by the M6 Electron probe, 2026-11-20)."""
    try:
        root = s.call("DOM.getDocument", {"depth": 0})["root"]["nodeId"]
        ids = s.call("DOM.querySelectorAll", {"nodeId": root, "selector": "input[type=password]"}).get("nodeIds", [])
        return {s.call("DOM.describeNode", {"nodeId": i})["node"]["backendNodeId"] for i in ids}
    except (AdapterError, KeyError):
        return set()


def mark_passwords(nodes: list, backends: set) -> None:
    for n in nodes:
        named_secret = n.get("control_type") == "Edit" and secret_name(n.get("name", ""))
        if (backends and (n.get("cdp") or {}).get("backend") in backends) or named_secret:
            n["is_password"] = True
            n.pop("value", None)                    # never read or log a secret
        mark_passwords(n.get("children") or [], backends)


@functools.lru_cache(maxsize=1)
def widget_kits() -> tuple:
    p = config.LIBRARY_DIR / "cdp" / "dom-widgets.json"
    return tuple(json.loads(p.read_text(encoding="utf-8"))["widgets"]) if p.exists() else ()


WIDGET_JS = """function(spec) {
  const pick = (sel) => sel === ':scope' ? this : this.querySelector(sel);
  let name = '';
  if (spec.name && spec.name.selector) {
    const el = pick(spec.name.selector);
    if (el) name = spec.name.own_text_only
      ? [...el.childNodes].filter(n => n.nodeType === 3).map(n => n.textContent).join(' ').trim()
      : el.textContent.trim();
  } else if (spec.name && spec.name.aria_label_or_next_label) {
    name = this.getAttribute('aria-label') || (this.nextElementSibling ? this.nextElementSibling.textContent.trim() : '');
  }
  const st = spec.state ? pick(spec.state.selector) : null;
  let state = null;
  if (st) {
    if (spec.state.on_class && st.classList.contains(spec.state.on_class)) state = 'On';
    else if (!spec.state.off_class || st.classList.contains(spec.state.off_class)) state = 'Off';
  }
  const disabled = !!(this.closest('[disabled], .disabled, [aria-disabled="true"]'));
  return {name: name.slice(0, 200), state, disabled};
}"""


def dom_widgets(s: "CdpSession", page_id: str) -> list[dict]:
    """Custom controls with no accessibility, found by the widget-kit library (library/cdp/dom-widgets.json)."""
    out: list[dict] = []
    kits = widget_kits()
    if not kits:
        return out
    root = s.call("DOM.getDocument", {"depth": 0})["root"]["nodeId"]
    for kit in kits:
        try:
            ids = s.call("DOM.querySelectorAll", {"nodeId": root, "selector": kit["container"]}).get("nodeIds", [])
        except AdapterError:
            continue
        for nid in ids[:300]:
            try:
                obj = s.call("DOM.resolveNode", {"nodeId": nid})["object"]["objectId"]
                r = s.call("Runtime.callFunctionOn", {"objectId": obj, "functionDeclaration": WIDGET_JS,
                                                      "arguments": [{"value": kit}], "returnByValue": True})
                info = (r.get("result") or {}).get("value") or {}
                click_id = nid
                if kit.get("click") and kit["click"] != ":scope":
                    click_id = s.call("DOM.querySelector", {"nodeId": nid, "selector": kit["click"]}).get("nodeId") or nid
                backend = s.call("DOM.describeNode", {"nodeId": click_id})["node"]["backendNodeId"]
            except (AdapterError, KeyError):
                continue
            if not info.get("name"):
                continue                       # an unlabelled control cannot be addressed safely
            node = {"control_type": kit["control_type"], "name": info["name"], "patterns": list(kit["patterns"]),
                    "framework_id": "Chrome", "cdp": {"page": page_id, "backend": backend, "kit": kit["id"]}}
            if info.get("state"):
                node["toggle_state"] = info["state"]
            if info.get("disabled"):
                node["enabled"] = False
            out.append(node)
    return out


SET_VALUE_JS = """function(v) {
  this.focus && this.focus();
  if (this.isContentEditable) { document.execCommand('selectAll'); return 'contenteditable'; }
  const proto = this instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype
              : this instanceof HTMLSelectElement ? HTMLSelectElement.prototype : HTMLInputElement.prototype;
  const d = Object.getOwnPropertyDescriptor(proto, 'value');
  if (d && d.set) d.set.call(this, v); else this.value = v;
  this.dispatchEvent(new Event('input', {bubbles: true}));
  this.dispatchEvent(new Event('change', {bubbles: true}));
  return 'setter';
}"""
CLICK_JS = "function() { this.scrollIntoView && this.scrollIntoView({block: 'center'}); this.click(); return true; }"


class CdpAdapter(Adapter):
    name = "cdp"

    def resolve(self, app: str) -> Optional[Target]:
        a = str(app)
        pid = None
        if a.isdigit() and int(a) in PORTS:
            pid = int(a)
        else:
            for p, _port in PORTS.items():
                try:
                    if psutil.Process(p).name().lower() == a.lower():
                        pid = p
                        break
                except psutil.Error:
                    continue
        if pid is None or not psutil.pid_exists(pid):
            return None
        port = PORTS[pid]
        try:
            pg = pages(port)
        except AdapterError:
            return None
        exe = psutil.Process(pid).name()
        return Target(key=f"{exe}|cdp|{port}", exe=exe, pid=pid, title=pg[0].get("title", "") if pg else "",
                      adapter=self.name)

    def _sessions(self, target: Target):
        port = PORTS[target.pid]
        for pg in pages(port):
            yield pg, CdpSession(pg["webSocketDebuggerUrl"])

    def snapshot(self, target: Target, depth: int = 12) -> list[dict]:
        windows = []
        for pg, s in self._sessions(target):
            try:
                s.call("Accessibility.enable")
                ax = s.call("Accessibility.getFullAXTree").get("nodes", [])
                widgets = dom_widgets(s, pg["id"])
                secret = password_backends(s)
            finally:
                s.close()
            children = ax_to_nodes(ax, pg["id"])
            mark_passwords(children, secret)
            if widgets:
                # controls the page hides from accessibility, found by the widget-kit library: one group, first child
                # of the window, so their locators do not move when the page's own tree changes
                children.insert(0, {"control_type": "Group", "name": "", "children": widgets,
                                    "cdp": {"page": pg["id"], "widget_kits": True}})
            windows.append({"control_type": "Window", "name": pg.get("title") or pg.get("url", ""),
                            "patterns": ["Window"], "framework_id": "Chrome", "cdp": {"page": pg["id"]},
                            "children": children})
        if not windows:
            raise AdapterError("the program has no page open on its debugger")
        return windows

    def _live(self, target: Target, locator: str) -> Optional[dict]:
        for node, loc, _p, _w in loc_mod.walk(self.snapshot(target)):
            if loc == locator:
                return node
        return None

    def _with_node(self, target: Target, node: dict, fn: str, args: Optional[list] = None):
        info = node.get("cdp") or {}
        port = PORTS[target.pid]
        pg = next((p for p in pages(port) if p["id"] == info.get("page")), None)
        if not pg or not info.get("backend"):
            raise AdapterError("the element has no DOM node to act on")
        s = CdpSession(pg["webSocketDebuggerUrl"])
        try:
            obj = s.call("DOM.resolveNode", {"backendNodeId": info["backend"]})["object"]["objectId"]
            r = s.call("Runtime.callFunctionOn", {"objectId": obj, "functionDeclaration": fn,
                                                  "arguments": [{"value": a} for a in (args or [])],
                                                  "returnByValue": True, "awaitPromise": True})
            if r.get("exceptionDetails"):
                raise AdapterError(f"page script failed: {r['exceptionDetails'].get('text')}")
            return s, (r.get("result") or {}).get("value")
        except Exception:
            s.close()
            raise

    def read(self, target: Target, locator: str, node: dict) -> dict:
        live = self._live(target, locator)
        if live is None:
            return {"exists": False}
        keep = ("name", "value", "toggle_state", "selected", "expand_state", "range", "enabled", "is_read_only")
        out = {"exists": True, **{k: live[k] for k in keep if k in live}}
        if live.get("control_type") == "Document" and "Text" in (live.get("patterns") or []):
            # the page's text, so the Text pattern the role map gives a Document is real (M6 probe to-do)
            try:
                s, txt = self._with_node(target, live, "function(){ const b = this.body || this.documentElement "
                                         "|| (this.ownerDocument && this.ownerDocument.body); "
                                         "return b ? b.innerText.slice(0, 20000) : ''; }")
                s.close()
                out["value"] = txt or ""
            except AdapterError:
                pass
        return out

    def execute(self, target: Target, locator: str, node: dict, action: str, args: dict) -> dict:
        live = self._live(target, locator)
        if live is None:
            raise AdapterError(f"element gone before acting: {locator}")
        if action in ("invoke", "select", "expand"):
            s, _ = self._with_node(target, live, CLICK_JS)
            s.close()
            return {"detail": "DOM click()"}
        if action == "set_checked":
            want = "On" if args["checked"] else "Off"
            if live.get("toggle_state") != want:
                s, _ = self._with_node(target, live, CLICK_JS)
                s.close()
            return {"detail": "DOM click() to " + want}
        if action in ("set_text", "set_number", "choose"):
            value = str(args.get("text", args.get("value", args.get("option", ""))))
            s, how = self._with_node(target, live, SET_VALUE_JS, [value])
            try:
                if how == "contenteditable":
                    s.call("Input.insertText", {"text": value})
            finally:
                s.close()
            after = self._live(target, locator) or {}
            if action == "set_text" and str(after.get("value", "")) != value:
                # the editor ignored a scripted value: type it as input instead (focus is inside the page only)
                s, _ = self._with_node(target, live, "function(){ this.focus(); this.select && this.select(); }")
                try:
                    s.call("Input.insertText", {"text": value})
                finally:
                    s.close()
                return {"detail": "Input.insertText fallback"}
            return {"detail": f"value setter + input/change ({how})"}
        if action == "answer_dialog":
            want = str(args["button"]).strip().lower()
            for n, _l, _p, _w in loc_mod.walk([live]):
                if n.get("control_type") == "Button" and (n.get("name") or "").strip().lower() == want:
                    s, _ = self._with_node(target, n, CLICK_JS)
                    s.close()
                    return {"detail": "DOM click() on the dialog's button"}
            raise AdapterError(f"no button '{args['button']}' in the dialog")
        raise AdapterError(f"the CDP adapter has no '{action}' (close windows with the UIA adapter or cig_close)")
