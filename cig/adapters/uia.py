"""The generic UI Automation adapter (plan 2.1, milestone M2).

It reads a live program as fixture-format nodes (cig/uiawalk.py) and acts through UIA patterns - Invoke, Value,
Toggle, SelectionItem, ExpandCollapse, RangeValue, Window - so no cursor moves and no input is injected. The one
exception is the `keys` action, which the safety layer allows only while the person is away.

Nothing here knows any particular program: menus, dialogs and edits are found by control type, name and pattern.
"""
from __future__ import annotations

import re
import time
from typing import Optional

import psutil
import uiautomation as auto
import win32gui

from .. import detect, locator as loc_mod, uiawalk
from ..uiawalk import pattern
from .base import Adapter, AdapterError, Target

MENU_WAIT_S = 3.0


def _norm(s: str) -> str:
    """Menu / button text as a person reads it: no '&' mnemonic, no accelerator after a tab, no trailing dots."""
    s = (s or "").split("\t")[0].replace("&", "")
    s = re.sub(r"\s*(\.\.\.|…)\s*$", "", s)
    s = re.sub(r"\s+(Ctrl|Alt|Shift)\+.*$", "", s)
    return s.strip().lower()


class UiaAdapter(Adapter):
    name = "uia"

    # ------------------------------------------------------------------ resolution
    def resolve(self, app: str) -> Optional[Target]:
        if str(app).startswith("fixture:"):
            return None
        pids = [p for p in detect.resolve_pids(app) if detect.windows_of(p)]
        if not pids:
            return None
        pid = pids[0]
        try:
            proc = psutil.Process(pid)
            exe = proc.name()
            path = proc.exe()
        except psutil.Error:
            return None
        ver = detect.file_version(path).get("product_version", "")
        hw = detect.windows_of(pid)
        integ = detect.integrity_level(pid)
        return Target(key=f"{exe}|{ver}|uia", exe=exe, pid=pid, title=win32gui.GetWindowText(hw[0]) if hw else "",
                      hwnd=hw[0] if hw else None, elevated=integ in ("high", "system"), adapter=self.name)

    def list_apps(self) -> list[dict]:
        return []                                  # cig_apps uses the detector directly

    # ------------------------------------------------------------------ reading
    def snapshot(self, target: Target, depth: int = 12) -> list[dict]:
        hwnds = detect.windows_of(target.pid)
        if not hwnds:
            raise AdapterError(f"{target.exe} (pid {target.pid}) has no visible window")
        return uiawalk.run(uiawalk.snapshot_hwnds, hwnds, depth, 3000, True, timeout=45)

    def _top_controls(self, target: Target):
        out = []
        for h in detect.windows_of(target.pid):
            try:
                out.append(auto.ControlFromHandle(h))
            except Exception:                                  # noqa: BLE001
                continue
        return out

    def _find_live(self, target: Target, locator: str):
        """Walk the live tree segment by segment, computing each child's segment exactly as the snapshot did."""
        tops = self._top_controls(target)
        top_nodes = [uiawalk.node_of(c, False) for c in tops]
        for c, n in zip(tops, top_nodes):
            seg = loc_mod.segment(n, top_nodes)
            if locator == seg:
                return c
            if locator.startswith(seg + "/"):
                found = self._descend(c, seg, locator)
                if found is not None:
                    return found
        return None

    def _descend(self, c, prefix: str, locator: str):
        kids = []
        child = c.GetFirstChildControl()
        while child is not None:
            kids.append(child)
            child = child.GetNextSiblingControl()
        nodes = [uiawalk.node_of(k, False) for k in kids]
        for k, n in zip(kids, nodes):
            full = f"{prefix}/{loc_mod.segment(n, nodes)}"
            if locator == full:
                return k
            if locator.startswith(full + "/"):
                r = self._descend(k, full, locator)
                if r is not None:
                    return r
        return None

    def read(self, target: Target, locator: str, node: dict) -> dict:
        def work():
            c = self._find_live(target, locator)
            if c is None:
                return {"exists": False}
            n = uiawalk.node_of(c, True)
            if "value" not in n and "Selection" in (n.get("patterns") or []) and n.get("control_type") == "ComboBox":
                # a drop-down list with no Value pattern names its choice through Selection (WPF, M6 probe 2026-11-20)
                try:
                    sel = pattern(c, "Selection").GetSelection()
                    if sel:
                        n["value"] = sel[0].Name
                except Exception:                              # noqa: BLE001
                    pass
            if "value" not in n and "Text" in (n.get("patterns") or []) and not n.get("is_password"):
                try:
                    n["value"] = pattern(c, "Text").DocumentRange.GetText(20000)
                except Exception:                              # noqa: BLE001
                    pass
            keep = ("name", "value", "toggle_state", "selected", "expand_state", "range", "enabled", "is_read_only")
            return {"exists": True, **{k: n[k] for k in keep if k in n}}
        return uiawalk.run(work, timeout=20)

    # ------------------------------------------------------------------ acting
    def execute(self, target: Target, locator: str, node: dict, action: str, args: dict) -> dict:
        return uiawalk.run(self._execute, target, locator, node, action, args, timeout=60)

    def _execute(self, target: Target, locator: str, node: dict, action: str, args: dict) -> dict:
        c = self._find_live(target, locator)
        if c is None:
            raise AdapterError(f"element gone before acting: {locator}")
        try:
            if action == "invoke":
                return self._invoke(c)
            if action == "set_text":
                pattern(c, "Value").SetValue(str(args["text"]))
                return {"detail": "ValuePattern.SetValue"}
            if action == "set_checked":
                want = 1 if args["checked"] else 0
                tp = pattern(c, "Toggle")
                for _ in range(3):
                    if int(tp.ToggleState) == want:
                        break
                    tp.Toggle()
                    time.sleep(0.05)
                return {"detail": "TogglePattern.Toggle"}
            if action == "select":
                pattern(c, "SelectionItem").Select()
                return {"detail": "SelectionItemPattern.Select"}
            if action == "expand":
                p = pattern(c, "ExpandCollapse")
                p.Expand() if args.get("expanded", True) else p.Collapse()
                return {"detail": "ExpandCollapsePattern"}
            if action == "set_number":
                pattern(c, "RangeValue").SetValue(float(args["value"]))
                return {"detail": "RangeValuePattern.SetValue"}
            if action == "choose":
                return self._choose(c, str(args["option"]))
            if action == "close_window":
                pattern(c, "Window").Close()
                return {"detail": "WindowPattern.Close"}
            if action == "answer_dialog":
                return self._answer(c, str(args["button"]))
            if action == "menu":
                return self._menu(target, c, str(args["path"]))
            if action == "keys":
                c.SetFocus()
                auto.SendKeys(str(args["keys"]), waitTime=0.05)
                return {"detail": "SendKeys (last resort)"}
        except AdapterError:
            raise
        except Exception as e:                                 # noqa: BLE001 - COM errors become adapter errors
            raise AdapterError(f"{action} failed: {e}") from e
        raise AdapterError(f"the UIA adapter has no '{action}'")

    @staticmethod
    def _invoke(c) -> dict:
        try:
            pattern(c, "Invoke").Invoke()
            return {"detail": "InvokePattern.Invoke"}
        except Exception:                                      # noqa: BLE001 - some buttons only expose MSAA
            pattern(c, "LegacyIAccessible").DoDefaultAction()
            return {"detail": "LegacyIAccessible.DoDefaultAction"}

    def _answer(self, dlg, button: str) -> dict:
        """The dialog's own button with that text: the shallowest match, never a button that belongs to a combo box
        (the Win32 file dialog has four 'Open' buttons - three are combo-box drop-down arrows, 2026-11-20)."""
        want = _norm(button)
        found = []
        for b, depth in auto.WalkControl(dlg, maxDepth=4):
            if b.ControlTypeName in ("ButtonControl", "SplitButtonControl") and _norm(b.Name) == want:
                try:
                    parent = b.GetParentControl()
                    if parent is not None and parent.ControlTypeName == "ComboBoxControl":
                        continue
                except Exception:                              # noqa: BLE001
                    pass
                found.append((depth, b))
        if not found:
            raise AdapterError(f"no button '{button}' in the dialog")
        depth, b = min(found, key=lambda x: x[0])
        name = b.Name
        return {**self._invoke(b), "button": name, "depth": depth}

    def _choose(self, combo, option: str) -> dict:
        try:
            vp = pattern(combo, "Value")
            if not vp.IsReadOnly:
                vp.SetValue(option)
                return {"detail": "ValuePattern.SetValue on the combo"}
        except Exception:                                      # noqa: BLE001
            pass
        ec = pattern(combo, "ExpandCollapse")
        ec.Expand()
        time.sleep(0.2)
        try:
            for item, _d in auto.WalkControl(combo, maxDepth=4):
                if item.ControlTypeName == "ListItemControl" and _norm(item.Name) == _norm(option):
                    pattern(item, "SelectionItem").Select()
                    return {"detail": "SelectionItem.Select in the expanded combo"}
        finally:
            try:
                ec.Collapse()
            except Exception:                                  # noqa: BLE001
                pass
        raise AdapterError(f"no option '{option}'")

    # menus: expand each level, find the next item under the expanded item or in a popup of the same process
    def _menu(self, target: Target, menubar, path: str) -> dict:
        parts = [p for p in path.split("/") if p.strip()]
        if not parts:
            raise AdapterError("empty menu path")
        scope = menubar
        trail = []
        for i, part in enumerate(parts):
            item = self._find_menu_item(target, scope, part, first=(i == 0))
            if item is None:
                raise AdapterError(f"menu item '{part}' not found after {'/'.join(trail) or 'the menu bar'}")
            trail.append(item.Name)
            last = i == len(parts) - 1
            pats = set(uiawalk.node_of(item, False).get("patterns") or [])
            if last:
                if "Invoke" in pats or "LegacyIAccessible" in pats:
                    self._invoke(item)
                elif "ExpandCollapse" in pats:
                    pattern(item, "ExpandCollapse").Expand()
                return {"detail": "menu " + " > ".join(trail)}
            if "ExpandCollapse" in pats:
                pattern(item, "ExpandCollapse").Expand()
            else:
                self._invoke(item)
            scope = item
        return {"detail": "menu " + " > ".join(trail)}

    def _find_menu_item(self, target: Target, scope, name: str, first: bool):
        want = _norm(name)
        deadline = time.time() + (0.1 if first else MENU_WAIT_S)
        while True:
            for c, _d in auto.WalkControl(scope, maxDepth=3 if first else 4):
                if c.ControlTypeName == "MenuItemControl" and _norm(c.Name) == want:
                    return c
            if not first:
                # a submenu opened as a popup window (Win32 #32768, XAML popup host) of the same process
                for top in auto.GetRootControl().GetChildren():
                    try:
                        if top.ProcessId != target.pid:
                            continue
                    except Exception:                          # noqa: BLE001
                        continue
                    for c, _d in auto.WalkControl(top, maxDepth=6):
                        if c.ControlTypeName == "MenuItemControl" and _norm(c.Name) == want:
                            return c
            if time.time() > deadline:
                return None
            time.sleep(0.15)
