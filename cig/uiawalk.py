"""Walk a live window's UI Automation tree into fixture-format nodes (library/schema/fixture.schema.json).
Shared by the detector (a small sample) and the UIA adapter (the full snapshot).

Every call runs in a worker thread with its own COM apartment and a timeout: a busy program can hang a UIA call
(plan 4.5), and a hang must cost the caller a timeout, not the server."""
from __future__ import annotations

import concurrent.futures
import threading
import uiautomation as auto

PATTERNS = {
    # pattern name -> uiautomation PropertyId constant name (UIA_Is<X>PatternAvailablePropertyId)
    "Invoke": "IsInvokePatternAvailableProperty",
    "Value": "IsValuePatternAvailableProperty",
    "Toggle": "IsTogglePatternAvailableProperty",
    "SelectionItem": "IsSelectionItemPatternAvailableProperty",
    "Selection": "IsSelectionPatternAvailableProperty",
    "ExpandCollapse": "IsExpandCollapsePatternAvailableProperty",
    "RangeValue": "IsRangeValuePatternAvailableProperty",
    "Text": "IsTextPatternAvailableProperty",
    "Window": "IsWindowPatternAvailableProperty",
    "Scroll": "IsScrollPatternAvailableProperty",
    "ScrollItem": "IsScrollItemPatternAvailableProperty",
    "Grid": "IsGridPatternAvailableProperty",
    "Table": "IsTablePatternAvailableProperty",
    "Transform": "IsTransformPatternAvailableProperty",
    "VirtualizedItem": "IsVirtualizedItemPatternAvailableProperty",
    "LegacyIAccessible": "IsLegacyIAccessiblePatternAvailableProperty",
}
_PIDS = {name: getattr(auto.PropertyId, const) for name, const in PATTERNS.items()}   # AttributeError = a typo, loudly
TOGGLE = {0: "Off", 1: "On", 2: "Indeterminate"}
EXPAND = {0: "Collapsed", 1: "Expanded", 2: "PartiallyExpanded", 3: "LeafNode"}

_POOL = concurrent.futures.ThreadPoolExecutor(max_workers=2, thread_name_prefix="cig-uia")
_local = threading.local()


class UiaTimeout(Exception):
    pass


def pattern(c, name: str):
    """A control's pattern by name ("Value", "Toggle", ...) through the generic GetPattern: uiautomation only puts the
    named getters on some control classes, and a real program puts patterns where the spec calls them conditional."""
    p = c.GetPattern(getattr(auto.PatternId, name + "Pattern"))
    if p is None:
        raise LookupError(f"{name} pattern not available")
    return p


def run(fn, *a, timeout: float = 20.0, **kw):
    """Run fn in a UIA worker thread (COM initialised there) with a timeout."""
    def wrapped():
        if not getattr(_local, "init", None):
            _local.init = auto.UIAutomationInitializerInThread(debug=False)
        return fn(*a, **kw)
    fut = _POOL.submit(wrapped)
    try:
        return fut.result(timeout=timeout)
    except concurrent.futures.TimeoutError as e:
        raise UiaTimeout(f"UI Automation did not answer within {timeout:g}s") from e


def _prop(c, pid, default=None):
    try:
        return c.GetPropertyValue(pid)
    except Exception:                                      # noqa: BLE001 - a dead element answers nothing
        return default


def node_of(c, with_state: bool = True) -> dict:
    """One element -> fixture node (no children)."""
    try:
        ct = (c.ControlTypeName or "Custom").removesuffix("Control")
    except Exception:                                      # noqa: BLE001
        ct = "Custom"
    n: dict = {"control_type": ct}
    for key, attr in (("name", "Name"), ("automation_id", "AutomationId"), ("class_name", "ClassName"),
                      ("framework_id", "FrameworkId")):
        try:
            v = getattr(c, attr)
        except Exception:                                  # noqa: BLE001
            v = None
        if v:
            n[key] = str(v)
    try:
        r = c.BoundingRectangle
        n["rect"] = [int(r.left), int(r.top), int(r.right), int(r.bottom)]
    except Exception:                                      # noqa: BLE001
        pass
    try:
        n["enabled"] = bool(c.IsEnabled)
        if c.IsOffscreen:
            n["offscreen"] = True
    except Exception:                                      # noqa: BLE001
        pass
    if _prop(c, auto.PropertyId.IsPasswordProperty, False):
        n["is_password"] = True
    pats = [p for p, pid in _PIDS.items() if _prop(c, pid, False)]
    if pats:
        n["patterns"] = pats
    if with_state:
        _state(c, n, set(pats))
    return n


def _state(c, n: dict, pats: set) -> None:
    try:
        if "Value" in pats and not n.get("is_password"):
            vp = pattern(c, "Value")
            n["value"] = str(vp.Value or "")[:4000]
            n["is_read_only"] = bool(vp.IsReadOnly)
        if "Toggle" in pats:
            n["toggle_state"] = TOGGLE.get(int(pattern(c, "Toggle").ToggleState), "Indeterminate")
        if "SelectionItem" in pats:
            n["selected"] = bool(pattern(c, "SelectionItem").IsSelected)
        if "ExpandCollapse" in pats:
            n["expand_state"] = EXPAND.get(int(pattern(c, "ExpandCollapse").ExpandCollapseState), "LeafNode")
        if "RangeValue" in pats:
            rp = pattern(c, "RangeValue")
            n["range"] = {"min": rp.Minimum, "max": rp.Maximum, "value": rp.Value,
                          **({"step": rp.SmallChange} if rp.SmallChange else {})}
        if "Window" in pats:
            if bool(pattern(c, "Window").IsModal):
                n["is_modal"] = True
    except Exception:                                      # noqa: BLE001 - state is best effort; the node stays
        pass


def walk(c, depth: int = 12, max_nodes: int = 3000, with_state: bool = True, _count=None) -> dict:
    count = _count if _count is not None else [0]
    n = node_of(c, with_state)
    count[0] += 1
    if depth > 0 and count[0] < max_nodes:
        kids = []
        try:
            child = c.GetFirstChildControl()
            while child is not None and count[0] < max_nodes:
                kids.append(walk(child, depth - 1, max_nodes, with_state, count))
                child = child.GetNextSiblingControl()
        except Exception:                                  # noqa: BLE001
            pass
        if kids:
            n["children"] = kids
    return n


def snapshot_hwnds(hwnds: list[int], depth: int = 12, max_nodes: int = 3000, with_state: bool = True) -> list[dict]:
    out = []
    for h in hwnds:
        try:
            c = auto.ControlFromHandle(h)
        except Exception:                                  # noqa: BLE001
            continue
        if c is None:
            continue
        node = walk(c, depth, max_nodes, with_state)
        node["hwnd"] = int(h)
        out.append(node)
    return out


def control_at(hwnd: int, path: list[int]):
    """The live control reached from a top-level hwnd by child indices (used by the adapter to re-find an element)."""
    c = auto.ControlFromHandle(hwnd)
    for i in path:
        child = c.GetFirstChildControl()
        for _ in range(i):
            if child is None:
                break
            child = child.GetNextSiblingControl()
        if child is None:
            return None
        c = child
    return c


def richness(windows: list[dict]) -> dict:
    total = named = aid = pat = 0
    fids: dict[str, int] = {}

    def rec(n):
        nonlocal total, named, aid, pat
        total += 1
        named += bool(n.get("name"))
        aid += bool(n.get("automation_id"))
        pat += bool(set(n.get("patterns") or []) - {"LegacyIAccessible"})
        f = n.get("framework_id")
        if f:
            fids[f] = fids.get(f, 0) + 1
        for k in n.get("children") or []:
            rec(k)
    for w in windows:
        rec(w)
    score = 0.0 if total == 0 else min(1.0, (total >= 5) * 0.25 + 0.35 * named / total + 0.4 * pat / total
                                       + 0.1 * min(1.0, aid / max(1, total)))
    return {"elements": total, "named": named, "automation_ids": aid, "with_patterns": pat,
            "framework_ids": fids, "score": round(score, 2)}
