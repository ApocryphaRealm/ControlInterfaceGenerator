"""CIG Python bridge - Tk (tkinter). Reads Tk's own widget tree and acts through Tk's own methods, always on Tk's
main thread (root.after + wait). An element is addressed by its Tk path name ('.!frame.!button'), plus '#i<n>' for an
item inside a list, combo, tree or notebook. Nodes come back in CIG's fixture format."""
import threading
import tkinter

NAME = "tk"


def _root():
    return tkinter._default_root


def on_tk(fn, timeout=15):
    """Run fn on Tk's main thread and return its result (Tk is not thread-safe)."""
    root = _root()
    box, done = {}, threading.Event()

    def run():
        try:
            box["r"] = fn()
        except Exception as e:                              # noqa: BLE001
            box["e"] = e
        finally:
            done.set()
    root.after(0, run)
    if not done.wait(timeout):
        raise TimeoutError("Tk did not answer (its event loop is busy)")
    if "e" in box:
        raise box["e"]
    return box.get("r")


def _opt(w, key, default=""):
    try:
        return w.cget(key)
    except Exception:                                       # noqa: BLE001
        return default


def _var(w, key):
    name = str(_opt(w, key, "") or "")
    if not name:
        return None
    try:
        return w.getvar(name)
    except Exception:                                       # noqa: BLE001
        return None


def _label_before(w):
    """Tk widgets have no accessible name: a field is named by the Label just before it in the same parent."""
    try:
        sibs = w.master.winfo_children()
        i = sibs.index(w)
        for s in reversed(sibs[:i]):
            if s.winfo_class() in ("Label", "TLabel"):
                return str(_opt(s, "text", "")).strip().rstrip(":").strip()
            break
    except Exception:                                       # noqa: BLE001
        pass
    return ""


def _node(w):
    cls = w.winfo_class()
    path = str(w)
    n = {"bridge": path, "framework_id": "Tk(bridge)", "patterns": []}
    text = str(_opt(w, "text", "") or "")
    if cls in ("Tk", "Toplevel"):
        n.update(control_type="Window", name=w.title(), patterns=["Window"])
    elif cls in ("Button", "TButton"):
        n.update(control_type="Button", name=text, patterns=["Invoke"])
    elif cls in ("Checkbutton", "TCheckbutton"):
        on = _opt(w, "onvalue", 1)
        val = _var(w, "variable")
        n.update(control_type="CheckBox", name=text, patterns=["Toggle"],
                 toggle_state="On" if val is not None and str(val) == str(on) else "Off")
    elif cls in ("Radiobutton", "TRadiobutton"):
        n.update(control_type="RadioButton", name=text, patterns=["SelectionItem"],
                 selected=str(_var(w, "variable")) == str(_opt(w, "value", "")))
    elif cls in ("Entry", "TEntry", "Spinbox", "TSpinbox"):
        secret = bool(str(_opt(w, "show", "") or ""))
        n.update(control_type="Edit" if "Spinbox" not in cls else "Spinner", name=text or _label_before(w),
                 patterns=["Value"] if "Spinbox" not in cls else ["RangeValue"])
        if "Spinbox" in cls:
            try:
                n["range"] = {"min": float(_opt(w, "from", 0)), "max": float(_opt(w, "to", 0)), "value": float(w.get() or 0)}
            except ValueError:
                n["range"] = {"min": float(_opt(w, "from", 0)), "max": float(_opt(w, "to", 0)), "value": 0.0}
        elif secret:
            n["is_password"] = True                         # never read: the value stays inside the program
        else:
            n["value"] = w.get()
            n["is_read_only"] = str(_opt(w, "state", "normal")) in ("readonly", "disabled")
    elif cls == "TCombobox":
        values = [str(v) for v in (w.cget("values") or ())]
        cur = w.get()
        n.update(control_type="ComboBox", name=_label_before(w) or "combobox", value=cur,
                 patterns=["Selection", "ExpandCollapse"],
                 children=[{"control_type": "ListItem", "name": v, "patterns": ["SelectionItem"], "selected": v == cur,
                            "bridge": f"{path}#i{i}", "framework_id": "Tk(bridge)"} for i, v in enumerate(values)])
        return n
    elif cls == "Listbox":
        sel = set(w.curselection())
        items = [str(x) for x in w.get(0, "end")]
        n.update(control_type="List", name=_label_before(w) or "list", patterns=["Selection"],
                 children=[{"control_type": "ListItem", "name": v, "patterns": ["SelectionItem"], "selected": i in sel,
                            "bridge": f"{path}#i{i}", "framework_id": "Tk(bridge)"} for i, v in enumerate(items)])
        return n
    elif cls in ("Scale", "TScale"):
        n.update(control_type="Slider", name=text or str(_opt(w, "label", "")) or _label_before(w),
                 patterns=["RangeValue"],
                 range={"min": float(_opt(w, "from", 0)), "max": float(_opt(w, "to", 0)), "value": float(w.get())})
    elif cls == "Treeview":
        def item(iid):
            kids = w.get_children(iid)
            d = {"control_type": "TreeItem", "name": str(w.item(iid, "text")), "patterns": ["SelectionItem"],
                 "selected": iid in w.selection(), "bridge": f"{path}#i{iid}", "framework_id": "Tk(bridge)"}
            if kids:
                d["patterns"] = ["SelectionItem", "ExpandCollapse"]
                d["expand_state"] = "Expanded" if w.item(iid, "open") else "Collapsed"
                d["children"] = [item(k) for k in kids]
            return d
        n.update(control_type="Tree", name=_label_before(w) or "tree", children=[item(i) for i in w.get_children("")])
        return n
    elif cls == "TNotebook":
        tabs = w.tabs()
        cur = w.select()
        n.update(control_type="Tab", name="tabs", patterns=["Selection"],
                 children=[{"control_type": "TabItem", "name": str(w.tab(t, "text")), "patterns": ["SelectionItem"],
                            "selected": t == cur, "bridge": f"{path}#i{i}", "framework_id": "Tk(bridge)"}
                           for i, t in enumerate(tabs)])
        return n
    elif cls in ("Label", "TLabel"):
        n.update(control_type="Text", name=text)
    else:
        n.update(control_type="Group", name="")
    if str(_opt(w, "state", "normal")) == "disabled":
        n["enabled"] = False
    kids = [_node(c) for c in w.winfo_children()]
    if kids:
        n["children"] = kids
    return n


def tree():
    def build():
        root = _root()
        tops = [root] + [w for w in root.winfo_children() if w.winfo_class() == "Toplevel"]
        out = []
        for t in tops:
            node = _node(t)
            if t is root:
                node["children"] = [c for c in node.get("children", []) if c.get("control_type") != "Window"]
            out.append(node)
        return out
    return on_tk(build)


def act(args):
    path, action = args["path"], args["action"]
    widget_path, _, item = path.partition("#i")

    def run():
        w = _root().nametowidget(widget_path)
        cls = w.winfo_class()
        if action == "invoke":
            w.invoke()
        elif action == "set_checked":
            on = str(_opt(w, "onvalue", 1))
            if (str(_var(w, "variable")) == on) != bool(args["checked"]):
                w.invoke()                                  # Tk's own toggle: the command and the variable both run
        elif action == "select" and not item:
            w.invoke()                                      # a radio button
        elif action == "select" and cls == "Listbox":
            w.selection_clear(0, "end")
            w.selection_set(int(item))
            w.event_generate("<<ListboxSelect>>")
        elif action == "select" and cls == "TNotebook":
            w.select(w.tabs()[int(item)])
        elif action == "select" and cls == "Treeview":
            w.selection_set(item)
        elif action == "select" and cls == "TCombobox":
            w.current(int(item))
            w.event_generate("<<ComboboxSelected>>")
        elif action == "choose":
            w.set(args["option"])
            w.event_generate("<<ComboboxSelected>>")
        elif action == "set_text":
            w.delete(0, "end")
            w.insert(0, args["text"])
        elif action == "set_number":
            if cls in ("Spinbox", "TSpinbox"):
                w.delete(0, "end")
                w.insert(0, str(args["value"]))
            else:
                w.set(args["value"])
        elif action == "expand":
            w.item(item, open=bool(args.get("expanded", True)))
        else:
            raise ValueError(f"the Tk bridge has no '{action}' for {cls}")
    on_tk(run)
