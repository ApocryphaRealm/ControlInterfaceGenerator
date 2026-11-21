import json, pathlib, sys
D = pathlib.Path(sys.argv[1]) / "library" / "frameworks"
D.mkdir(parents=True, exist_ok=True)
DOC = "doc: plan 2.2 and learn.microsoft.com UIA overview (2026-10-24)"


def E(fw, label, detect, adapters, version_from=None, specializes=None, in_v1=True, notes=""):
    e = {"framework": fw, "label": label, "versions": "any", "source": [DOC], "adapter_in_v1": in_v1,
         "detect": detect, "adapters": adapters}
    if version_from:
        e["version_from"] = version_from
    if specializes:
        e["specializes"] = specializes
    if notes:
        e["notes"] = notes
    return e


def m(r, w):
    return {"re": r, "w": w}


def mv(r, w, version):
    """module evidence that counts only when that module's file version satisfies `version` (">=3", "<3")"""
    return {"re": r, "w": w, "version": version}


entries = [
    E("win32", "Win32 (USER32 / common controls)",
      {"window_class": [m(r"^#32770$", 0.3),
                        m(r"^(SysListView32|SysTreeView32|Edit|Button|ToolbarWindow32|msctls_.*|ComboBox|RichEdit.*)$", 0.2),
                        m(r".", 0.05)],
       "uia_framework_id": [m(r"^Win32$", 0.35)]},
      [{"name": "uia", "base": 0.85}], {"exe_file_version": True},
      notes="The fallback for any native window. Low weights on purpose: every richer framework also shows Win32 evidence."),
    E("mfc", "MFC", {"modules": [m(r"^mfc\d+u?\.dll$", 0.6)], "window_class": [m(r"^Afx:", 0.4)]},
      [{"name": "uia", "base": 0.8}], {"exe_file_version": True}, specializes=["win32"]),
    E("winforms", "Windows Forms (.NET)",
      {"window_class": [m(r"^WindowsForms10\.", 0.6)], "modules": [m(r"^system\.windows\.forms(\.ni)?\.dll$", 0.4)],
       "uia_framework_id": [m(r"^WinForm$", 0.3)]},
      [{"name": "uia", "base": 0.85}], {"module_re": r"^system\.windows\.forms(\.ni)?\.dll$"}, specializes=["win32"]),
    E("wpf", "WPF (.NET)",
      {"window_class": [m(r"^HwndWrapper\[", 0.6)],
       "modules": [m(r"^presentationframework(\.ni)?\.dll$", 0.4), m(r"^wpfgfx_", 0.2)],
       "uia_framework_id": [m(r"^WPF$", 0.4)]},
      [{"name": "uia", "base": 0.9}], {"module_re": r"^presentationframework(\.ni)?\.dll$"}, specializes=["win32"]),
    E("winui3", "WinUI 3 (Windows App SDK)",
      {"window_class": [m(r"^WinUIDesktopWin32WindowClass$", 0.6)], "modules": [mv(r"^microsoft\.ui\.xaml\.dll$", 0.6, ">=3")],
       "uia_framework_id": [m(r"^XAML$", 0.2)]},
      [{"name": "uia", "base": 0.9}], {"module_re": r"^microsoft\.ui\.xaml\.dll$"}, specializes=["win32", "uwp"],
      notes="Microsoft.UI.Xaml.dll at 3.x is WinUI 3; at 2.x it is WinUI 2 (a UWP control library, also in XAML islands)."),
    E("uwp", "UWP / system XAML / WinUI 2 (CoreWindow, XAML islands)",
      {"window_class": [m(r"^(Windows\.UI\.Core\.CoreWindow|ApplicationFrameWindow)$", 0.5)],
       "modules": [m(r"^windows\.ui\.xaml\.dll$", 0.4), mv(r"^microsoft\.ui\.xaml\.dll$", 0.2, "<3")],
       "uia_framework_id": [m(r"^XAML$", 0.2)], "msix": [m(r".", 0.1)]},
      [{"name": "uia", "base": 0.85}], {"exe_file_version": True}, specializes=["win32"]),
    E("qt5", "Qt 5", {"modules": [m(r"^qt5core\.dll$", 0.8)], "window_class": [m(r"^Qt5\d*QWindow", 0.3)],
                      "uia_framework_id": [m(r"^Qt$", 0.1)]},
      [{"name": "uia", "base": 0.75}], {"module_re": r"^qt5core\.dll$"}, specializes=["win32"],
      notes="Qt 5 exposes UIA through its MSAA bridge: names yes, AutomationIds rarely (to verify by probe)."),
    E("qt6", "Qt 6", {"modules": [m(r"^qt6core\.dll$", 0.8)], "window_class": [m(r"^Qt6\d*QWindow", 0.3)],
                      "uia_framework_id": [m(r"^Qt$", 0.1)]},
      [{"name": "uia", "base": 0.8}], {"module_re": r"^qt6core\.dll$"}, specializes=["win32"],
      notes="Qt 6 has a native UIA provider (qtbase src/plugins/platforms/windows/uiautomation)."),
    E("chromium", "Chromium / CEF",
      {"window_class": [m(r"^Chrome_WidgetWin_\d+$", 0.4), m(r"^Chrome_RenderWidgetHostHWND$", 0.2)],
       "modules": [m(r"^libcef\.dll$", 0.6), m(r"^chrome_elf\.dll$", 0.2)],
       "uia_framework_id": [m(r"^Chrome$", 0.2)]},
      [{"name": "cdp", "base": 0.9, "needs": "--remote-debugging-port on a separate profile"}, {"name": "uia", "base": 0.6}],
      {"module_re": r"^libcef\.dll$", "exe_regex": r"Chrome/(\d+\.\d+\.\d+\.\d+)", "exe_file_version": True},
      specializes=["win32"]),
    E("electron", "Electron",
      {"files_beside_exe": [m(r"^resources[\\/]app\.asar$", 0.6), m(r"^resources[\\/]app[\\/]package\.json$", 0.4)],
       "exe_strings": [m(r"Electron/\d+\.\d+\.\d+", 0.5)], "window_class": [m(r"^Chrome_WidgetWin_1$", 0.1)]},
      [{"name": "cdp", "base": 0.9, "needs": "--remote-debugging-port (fuse permitting)"}, {"name": "uia", "base": 0.6}],
      {"exe_regex": r"Electron/(\d+\.\d+\.\d+)"}, specializes=["chromium", "win32"]),
    E("console", "Console program",
      {"pe_subsystem": [m(r"^console$", 0.7)], "window_class": [m(r"^(ConsoleWindowClass|PseudoConsoleWindow)$", 0.4)]},
      [{"name": "cli", "base": 0.9}, {"name": "uia", "base": 0.3}], {"exe_file_version": True}),
    E("gecko", "Firefox / Gecko", {"window_class": [m(r"^MozillaWindowClass$", 0.7)], "modules": [m(r"^xul\.dll$", 0.5)],
                                   "uia_framework_id": [m(r"^Gecko$", 0.2)]},
      [{"name": "uia", "base": 0.6}], {"exe_file_version": True}, specializes=["win32"], in_v1=False),
    E("java", "Java AWT / Swing / SWT", {"window_class": [m(r"^SunAwt", 0.7), m(r"^SWT_Window", 0.6)],
                                        "modules": [m(r"^jvm\.dll$", 0.6)]},
      [{"name": "java-access-bridge", "base": 0.7}], in_v1=False),
    E("flutter", "Flutter", {"window_class": [m(r"^FLUTTER_RUNNER_WIN32_WINDOW$", 0.8)],
                             "modules": [m(r"^flutter_windows\.dll$", 0.7)]},
      [{"name": "uia", "base": 0.6}], in_v1=False),
    E("delphi-vcl", "Delphi VCL", {"window_class": [m(r"^T(Form|Application)", 0.6)]}, [{"name": "uia", "base": 0.5}],
      in_v1=False, specializes=["win32"]),
    E("wxwidgets", "wxWidgets", {"window_class": [m(r"^wxWindow", 0.7)]}, [{"name": "uia", "base": 0.7}],
      in_v1=False, specializes=["win32"]),
    E("sdl", "SDL / GLFW / custom-drawn", {"window_class": [m(r"^(SDL_app|GLFW30)$", 0.6)],
                                           "modules": [m(r"^(sdl2|sdl3|glfw3)\.dll$", 0.4)]},
      [{"name": "none", "base": 0.0, "needs": "an in-process bridge (the DevBench pattern)"}], in_v1=False),
    E("game-engine", "Unity / Unreal", {"window_class": [m(r"^(UnityWndClass|UnrealWindow)$", 0.8)],
                                        "modules": [m(r"^unityplayer\.dll$", 0.6)]},
      [{"name": "none", "base": 0.0, "needs": "an in-process bridge"}], in_v1=False),
]
QUIRKS = {
    "qt5": [{"id": "qt5-objectname-automationid", "source": "probe:2026-11-20 IDA Freeware 8.4 (Qt 5.15.3)",
             "text": "Qt 5.15 exports the objectName chain as AutomationId (e.g. 'MsgBoxCritical.qt_msgbox_label'), "
                     "so locators get stable AutomationIds where the program names its widgets."},
            {"id": "qt-messagebox", "source": "probe:2026-11-20 IDA Freeware 8.4",
             "text": "QMessageBox is a Window (AutomationId 'MsgBox<Icon>') whose buttons sit in a Group "
                     "'<id>.qt_msgbox_buttonbox'; Button + Invoke answers it."}],
    "qt6": [{"id": "qt6-window-class", "source": "probe:2026-11-20 MO2 2.5 (Qt 6.7.1), Equalizer APO Editor (Qt 6.7.2)",
             "text": "Top-level window class is Qt<major><minor><patch>QWindowIcon, e.g. Qt671QWindowIcon; UIA "
                     "FrameworkId is 'Qt'."}],
    "winui3": [{"id": "winui-version", "source": "probe:2026-11-20 Notepad, Paint",
                "text": "Microsoft.UI.Xaml.dll 3.x = WinUI 3; Settings and Explorer load 2.9.x = WinUI 2 (UWP library / "
                        "XAML islands), so the module's version decides, not its name."}],
}
for e in entries:
    p = D / f"{e['framework']}.json"
    if p.exists():                                   # keep what probes and the field have added since
        old = json.loads(p.read_text(encoding="utf-8"))
        e["source"] += [s for s in old.get("source", []) if not s.startswith("doc") and s not in e["source"]]
        if old.get("observed"):
            e["observed"] = old["observed"]
        if old.get("quirks"):
            e["quirks"] = old["quirks"]
    have = {q["id"] for q in e.get("quirks", [])}
    e.setdefault("quirks", []).extend(q for q in QUIRKS.get(e["framework"], []) if q["id"] not in have)
    if not e["quirks"]:
        del e["quirks"]
    p.write_text(json.dumps(e, indent=1), encoding="utf-8")
print(len(entries), "entries")
