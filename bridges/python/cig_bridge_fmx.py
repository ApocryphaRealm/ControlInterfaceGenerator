"""CIG Python bridge - Delphi FireMonkey through Embarcadero's delphifmx. FMX objects may only be touched on the main
thread: install() (called by cig_bridge_boot on the main thread, before the script runs) creates a delphifmx Timer
owned by the real Application; once Application.Run() starts the loop, it runs CIG's queued requests every 50 ms.
The tree is FMX's own Children list; actions go through the controls' own properties (IsChecked, Text, ItemIndex,
Value, TabIndex). An element is addressed by its index path from the main form."""
import queue
import threading

NAME = "fmx"
_Q: "queue.Queue" = queue.Queue()
_real_app = None


_timer = None


def _tick(sender):
    while True:
        try:
            fn, box, done = _Q.get_nowait()
        except queue.Empty:
            return
        try:
            box["r"] = fn()
        except Exception as e:                              # noqa: BLE001
            box["e"] = e
        finally:
            done.set()


def install():
    """Called by cig_bridge_boot ON THE MAIN THREAD before the script runs: create a delphifmx Timer owned by the real
    Application. It starts firing once the script's Application.Run() starts the message loop, and runs CIG's queued
    requests on the main thread. (Application.Run is read-only and a stand-in Application cannot own Delphi
    controls - both tried 2026-11-20 - so the Timer is made here instead.)"""
    global _real_app, _timer
    import delphifmx
    _real_app = delphifmx.Application
    _timer = delphifmx.Timer(_real_app)
    _timer.Interval = 50
    _timer.OnTimer = _tick
    _timer.Enabled = True


def on_main(fn, timeout=15):
    box, done = {}, threading.Event()
    _Q.put((fn, box, done))
    if not done.wait(timeout):
        raise TimeoutError("FMX's main thread did not answer")
    if "e" in box:
        raise box["e"]
    return box.get("r")


def _kids(o):
    """Children of o, in creation order. delphifmx's Children list cannot be indexed from Python, but the form's
    Components can, and each knows its Parent (Delphi objects compare with ==) - found 2026-11-20."""
    form = _real_app.MainForm
    try:
        comps = [form.Components[i] for i in range(int(form.ComponentCount))]
    except Exception:                                       # noqa: BLE001
        return []
    out = []
    for c in comps:
        try:
            if c.Parent == o:
                out.append(c)
        except Exception:                                   # noqa: BLE001 - non-visual components have no Parent
            continue
    return out


def _cls(o):
    try:
        return o.ClassName
    except Exception:                                       # noqa: BLE001
        return type(o).__name__


def _items(o):
    it = o.Items
    for get in (lambda: [it[i] for i in range(it.Count)], lambda: [it.Strings[i] for i in range(it.Count)],
                lambda: [s for s in str(it.Text).splitlines() if s]):
        try:
            return [str(x) for x in get()]
        except Exception:                                   # noqa: BLE001
            continue
    return []


def _node(o, path, prev_label):
    cls = _cls(o)
    n = {"bridge": path, "framework_id": "FMX(bridge)", "patterns": []}
    text = ""
    try:
        text = str(o.Text) if hasattr(o, "Text") else ""
    except Exception:                                       # noqa: BLE001
        pass
    if cls in ("TButton", "TSpeedButton"):
        n.update(control_type="Button", name=text, patterns=["Invoke"])
    elif cls in ("TCheckBox", "TSwitch"):
        n.update(control_type="CheckBox", name=text or prev_label or ("switch" if cls == "TSwitch" else ""),
                 patterns=["Toggle"], toggle_state="On" if o.IsChecked else "Off")
    elif cls == "TRadioButton":
        n.update(control_type="RadioButton", name=text, patterns=["SelectionItem"], selected=bool(o.IsChecked))
    elif cls == "TEdit":
        n.update(control_type="Edit", name=prev_label, patterns=["Value"])
        if o.Password:
            n["is_password"] = True                         # never read
        else:
            n["value"] = text
            n["is_read_only"] = bool(o.ReadOnly)
    elif cls in ("TComboBox", "TListBox"):
        items = _items(o)
        idx = o.ItemIndex
        combo = cls == "TComboBox"
        n.update(control_type="ComboBox" if combo else "List", name=prev_label or ("combobox" if combo else "list"),
                 patterns=["Selection", "ExpandCollapse"] if combo else ["Selection"],
                 children=[{"control_type": "ListItem", "name": v, "patterns": ["SelectionItem"], "selected": i == idx,
                            "bridge": f"{path}#i{i}", "framework_id": "FMX(bridge)"} for i, v in enumerate(items)])
        if combo:
            n["value"] = items[idx] if 0 <= idx < len(items) else ""
        return n
    elif cls in ("TTrackBar", "TSpinBox"):
        n.update(control_type="Slider" if cls == "TTrackBar" else "Spinner", name=prev_label or cls[1:].lower(),
                 patterns=["RangeValue"], range={"min": float(o.Min), "max": float(o.Max), "value": float(o.Value)})
        return n
    elif cls == "TTabControl":
        count = o.TabCount
        n.update(control_type="Tab", name="tabs", patterns=["Selection"],
                 children=[{"control_type": "TabItem", "name": str(o.Tabs[i].Text), "patterns": ["SelectionItem"],
                            "selected": i == o.TabIndex, "bridge": f"{path}#i{i}", "framework_id": "FMX(bridge)"}
                           for i in range(count)])
        return n
    elif cls == "TLabel":
        n.update(control_type="Text", name=text)
    else:
        n.update(control_type="Group", name="")
    try:
        if not o.Enabled:
            n["enabled"] = False
    except Exception:                                       # noqa: BLE001
        pass
    kids, label = [], ""
    for i, c in enumerate(_kids(o)):
        k = _node(c, f"{path}/{i}", label)
        label = k["name"].rstrip(":").strip() if k.get("control_type") == "Text" else ""
        kids.append(k)
    if kids:
        n["children"] = kids
    return n


def tree():
    def build():
        form = _real_app.MainForm
        node = _node(form, "f", "")
        node.update(control_type="Window", name=str(form.Caption), patterns=["Window"])
        return [node]
    return on_main(build)


def _resolve(path):
    parts = path.split("#i")[0].split("/")
    o = _real_app.MainForm
    for p in parts[1:]:
        o = _kids(o)[int(p)]
    return o


def act(args):
    path, action = args["path"], args["action"]
    item = int(path.split("#i")[1]) if "#i" in path else None

    def run():
        o = _resolve(path)
        cls = _cls(o)
        if action == "invoke":
            handler = getattr(o, "OnClick", None)
            if callable(handler):
                handler(o)
        elif action == "set_checked":
            o.IsChecked = bool(args["checked"])
        elif action == "select" and item is None:
            o.IsChecked = True
        elif action == "select" and cls == "TTabControl":
            o.TabIndex = item
        elif action == "select":
            o.ItemIndex = item
        elif action == "choose":
            items = _items(o)
            o.ItemIndex = items.index(args["option"])
        elif action == "set_text":
            o.Text = args["text"]
        elif action == "set_number":
            o.Value = float(args["value"])
        else:
            raise ValueError(f"the FMX bridge has no '{action}' for {cls}")
    on_main(run)
