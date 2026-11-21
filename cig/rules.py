"""Apply the library's adapter rules to a UI tree snapshot -> the typed action set (plan 2.4, 2.5 "Schemas")."""
from __future__ import annotations

import functools
import json
from typing import Optional

from . import config, locator

PROPS = ("is_password", "is_read_only", "is_modal", "enabled")


@functools.lru_cache(maxsize=None)
def load_rules(name: str = "uia") -> tuple:
    data = json.loads((config.LIBRARY_DIR / "rules" / f"{name}.json").read_text(encoding="utf-8"))
    return tuple(data["rules"])


def matches(rule: dict, node: dict) -> bool:
    w = rule.get("when", {})
    ct = node.get("control_type")
    if "control_type" in w and ct not in w["control_type"]:
        return False
    pats = set(node.get("patterns") or [])
    if not set(w.get("patterns_all", [])) <= pats:
        return False
    if w.get("patterns_any") and not (set(w["patterns_any"]) & pats):
        return False
    if set(w.get("patterns_none", [])) & pats:
        return False
    for p in PROPS:
        if p in w and bool(node.get(p, False if p != "enabled" else True)) != bool(w[p]):
            return False
    return True


def _child_names(node: dict, types: set, skip_into: frozenset = frozenset()) -> list[str]:
    out = []

    def rec(n, depth):
        for c in n.get("children") or []:
            if c.get("control_type") in types and c.get("name"):
                out.append(c["name"])
            if depth < 3 and c.get("control_type") not in skip_into:
                rec(c, depth + 1)
    rec(node, 0)
    return list(dict.fromkeys(out))


def menu_paths(node: dict, prefix: str = "") -> list[str]:
    """Every menu path visible in the snapshot under a MenuBar/Menu node: "File", "File/Open...", ..."""
    out = []
    for c in node.get("children") or []:
        if c.get("control_type") == "MenuItem" and c.get("name"):
            p = f"{prefix}/{c['name']}" if prefix else c["name"]
            out.append(p)
            out += menu_paths(c, p)
        elif c.get("control_type") == "Menu":
            out += menu_paths(c, prefix)
    return out


def _schema(rule: dict, node: dict) -> dict:
    props, req = {}, []
    for arg, spec in (rule.get("args") or {}).items():
        s = {"type": spec["type"]}
        src = spec.get("enum_from")
        if src == "child_buttons":
            # a combo box's drop-down arrow is not one of the dialog's answers
            s["enum"] = _child_names(node, {"Button", "SplitButton"}, frozenset({"ComboBox", "TitleBar"}))
        elif src == "child_items":
            items = _child_names(node, {"ListItem", "MenuItem", "DataItem"})
            if items:
                s["enum"] = items
        elif src == "menu_paths":
            paths = menu_paths(node)
            if paths:
                s["examples"] = paths[:50]          # deeper levels appear only once a menu is opened: not an enum
        if spec.get("range_from") == "range" and node.get("range"):
            r = node["range"]
            s.update({k: r[k] for k in ("min", "max") if k in r})
            if r.get("step"):
                s["multipleOf"] = r["step"]
        props[arg] = s
        req.append(arg)
    return {"type": "object", "properties": props, "required": req, "additionalProperties": False}


def actions_for(windows: list[dict], rules_name: str = "uia", include_disabled: bool = False) -> list[dict]:
    """The generated action set. Each entry: id, element, action, kind, label, input_schema, rule, locator."""
    rules = load_rules(rules_name)
    out = []
    for node, loc, parents, win in locator.walk(windows):
        if node.get("enabled") is False and not include_disabled:
            continue
        for rule in rules:
            if not matches(rule, node):
                continue
            eid = locator.element_id(loc)
            label = node.get("name") or node.get("automation_id") or node.get("control_type")
            out.append({
                "id": f"{eid}.{rule['action']}",
                "element": eid,
                "action": rule["action"],
                "kind": rule.get("kind", "write"),
                "label": f"{rule['action']} {node.get('control_type')} '{label}'",
                "input_schema": _schema(rule, node),
                "rule": rule["id"],
                "verify": rule.get("verify"),
                "locator": loc,
            })
            if rule.get("stop", True):
                break
    return out


def find_rule(action: str, node: dict, rules_name: str = "uia") -> Optional[dict]:
    for rule in load_rules(rules_name):
        if rule["action"] == action and matches(rule, node):
            return rule
    return None
