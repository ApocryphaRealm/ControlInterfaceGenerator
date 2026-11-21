# CIG tool survey - which of our modding tools CIG can drive today (2026-11-20)

Read-only survey, run by the Tooling Agent on the owner's order of 2026-11-20 20:31 (relayed by Main Agent). Each tool was
started, detected, its UI tree read ONCE through CIG's UIA adapter, and asked to close. Nothing was clicked, typed or
chosen except what it took to get past a start-up dialog and to close. Script: `tools/survey_tool.py` in the CIG repo
(one JSON per tool in the repo's `var/survey/`, copied to `fixtures/tool-survey/` beside this file); digest:
`tools/survey_digest.py`.

**How they were started - a deviation from the order, on purpose.** The order said to start the VFS tools through MO2 on
the Njordlinger instance. They were started STANDALONE instead (CIG's own launcher, unelevated, from each tool's own
folder, with the arguments MO2's executables list gives them): MO2 was closed, starting it on the owner's instance is
the launcher session's job (rule 69), and a tool run outside the VFS cannot write into the instance's Overwrite. The
price: two windows that need the VFS were not reached (Outfit Studio's editor, DynDOLOD's options). They are listed
under "Second pass".

## The table

"Named" = share of UI elements with a name; "ids" = share with an automation id. Effort is in CIG sessions (3-4 hours).

| Tool | Version | Framework (as CIG saw it) | Verdict | What works now | What is missing | Effort to close |
|---|---|---|---|---|---|---|
| Synthesis | 0.36.6 | WPF (detected, score 1.0) | **drivable now** | 50 elements, lists with selectable items (game picker), named buttons; the first-run "which game" page was read | nothing structural; patcher list and settings pages not opened in this pass | none - a proof run (0.5) |
| PGPatcher | 2.4.0 | Win32 dialog | **drivable now** | 69 elements, 94 % named, 88 % ids: 31 buttons, the mod-manager choice, the instance location edit, a combo | - | none - a proof run (0.5) |
| NifSkope | 2.0 (Qt 5.15.2) | Qt 5 (detected, score 1.0) | **drivable now**, viewport aside | 119 elements, 71 % named, 52 % ids (Qt object names): 18 buttons, checkboxes, 7 menu paths, the block list / header / details trees with their rows | the 3D viewport is one opaque surface (expected); tree CELL editing not tried | none for the forms; the viewport stays out of reach |
| Creation Kit | 1.7.99.0 | Win32 native | **drivable now** for its forms | 312 elements, 80 % named: the Object Window tree (42 items, expand / select), list views with headers, 28 checkboxes, 9 top-level menus, 41 buttons | the Render Window is opaque; record forms not opened; it asks a start-up question (unpack Scripts.zip?) and saves its own prefs on exit | 0.5 for a start-up rule (answer No) + a proof; render view never |
| BodySlide | 5.8.2 | wxWidgets (score 0.7) | **drivable now**, by position for some | 66 elements, 76 % named, 85 % ids: 20 buttons, 4 edits, 2 combos (outfit / preset), a slider, a checkbox | the 4 edits and 2 combos carry no name (their labels are separate statics); the slider panel was empty without the VFS | 1 - label-by-neighbour rule (shared with the Delphi tools below) |
| xLODGen | 4.1.5o | Delphi VCL (shown as Win32, 0.4) | **partly** | options dialog: 34 named checkboxes, 45 buttons, the worldspace list (7 rows, selectable) | 28 combo boxes and 28 texts with no name and a numeric id that changes each run - reachable only by position | 1 - the label-by-neighbour rule; 0.5 - recognise Delphi (TfrmMain) in the detector |
| TexGen | 3.0 Alpha-211 | Delphi VCL (shown as Win32, 0.4) | **partly** | options window: 75 named buttons, 16 named checkboxes, Start / Exit | 44 combo boxes (texture sizes, formats) with no name and unstable ids | the same rule as xLODGen (no extra) |
| DynDOLOD | 3.0 Alpha-211 | Delphi VCL | **partly (expected), options not reached** | standalone it stops at "DynDOLOD Resources SE version information not found" - that message window was read in full (text, help links, Exit) | its options window needs the VFS; the same toolkit as TexGen, so the same verdict is expected, not observed | second pass under MO2 (0.5) |
| Wabbajack | 4.3.2.2 | Avalonia (unknown to the detector: scored Win32 0.05) | **partly** | 8 named buttons (Home, Browse lists, Create a list, Settings, Get Help ...) | 50 unnamed groups: the page content is not described; no library entry for Avalonia; the launcher updates itself on start | 1 - an Avalonia library entry + probe; then a content check |
| Pandora Behaviour Engine+ | 4.4.0-beta | Avalonia (unknown to the detector) | **needs adapter work** | 6 buttons | three of them are named only by an icon glyph; the list of patches is unnamed groups - CIG cannot tell which patch is which or what Launch is | 1 (Avalonia entry, shared with Wabbajack) + names from tooltips; or drive it from its command line with the CLI adapter (0.5, to verify it has one) |
| xEdit (SSEEdit) | 4.1.5f | Delphi VCL (shown as Win32) | **opaque where it matters** | the Module Selection dialog's OK / Cancel and filter; after loading: 6 tabs, 3 filter edits, 9 buttons, the status text ("Background Loader: finished") | the plugin checklist, the RECORD TREE and the record view are custom-drawn (VirtualTreeView): UIA shows bare panes, no rows; its menus are right-click pop-ups | not through UIA. Use xEdit's own scripts from the command line (CLI adapter + the project's existing plugin-reading scripts): 1. An in-process bridge would be a new adapter (3+) |
| Bethini Pie | 4.17 | Tk (ttkbootstrap, PyInstaller) - shown as Win32, 0.4 | **opaque** | the title bar | 118 unnamed panes: no control is described. Messages sent to its windows do nothing (Tk reads the real mouse position), and it would not close without its own "Do you want to quit?" box being clicked | none worth it: it edits INI files - use the INI files directly (role `ini-edit`). A picture-based fallback would be a new adapter |
| Outfit Studio | 5.8.2 | wxWidgets | **not reached** | standalone it stops at "Failed to load skeleton" (the skeleton comes from a mod, through the VFS) | the editor itself | second pass under MO2 (0.5); expect BodySlide's verdict plus an opaque 3D view |
| xEdit Quick Auto Clean | - | - | **not started, on purpose** | - | it begins cleaning (writing) as soon as it has a plugin | - |
| LOOT | - | - | **not installed** | only its data folder is on disk | - | - |
| Nemesis | - | - | **not installed** | Pandora is used instead; only Nemesis patches are in the list | - | - |

Also registered in MO2 but not on the list, and not surveyed: EasyNPC, Cathedral Assets Optimizer, SSE NIF Optimizer,
ReSaver, Papyrus Compiler App.

## What the survey says about CIG

- **Three of thirteen are drivable today with nothing added** (Synthesis, PGPatcher, NifSkope), and two more for their
  forms (Creation Kit, BodySlide). They are the WPF, Qt and plain Win32 programs - the frameworks M2 and M6 measured.
- **One rule would lift three tools** (xLODGen, TexGen, DynDOLOD) and BodySlide's edits: an unnamed edit or combo takes
  the name of the static text beside it (to its left or above). Delphi labels and wx statics are not tied to their
  controls in UIA, and their ids are window handles that change each run.
- **Avalonia is a gap** (Wabbajack, Pandora): the detector has no entry for it, and both programs leave most of their
  content unnamed. An entry and a probe come first; Pandora's glyph-only buttons need tooltips or its command line.
- **Two tools are out of UIA's reach by construction**: xEdit's VirtualTreeView and Bethini Pie's Tk. For both the right
  route is not the window: xEdit has scripts and a command line, Bethini only edits INI files.
- **The detector under-reports**: Delphi programs came back as "Win32" at 0.4-0.6 although the library has a Delphi
  entry (window class TfrmMain, TfrmModuleSelect), and Tk and Avalonia are unknown.

## Faults in CIG found on the way (for the CIG Agent; nothing in its files was changed)

1. **A launched program inherits the launcher's working folder.** Wabbajack's launcher unpacked its update (336 MB,
   version 4.3.2.2, plus `wabbajack-cli.bat`) into the folder the survey was run from - the CIG repo. Outfit Studio and
   BodySlide take the working folder for home too. `cig.launch` should start a program in its own folder; the survey
   script now changes to it first.
2. **`engine.do` raises when the button it pressed closes the whole program** ("has no visible window", from the
   read-back) instead of finishing ok - seen on DynDOLOD's and TexGen's "Exit DynDOLOD".
3. **`launch.close` cannot answer a start-up question that is not modal** (DynDOLOD's "Select Game Mode", the Creation
   Kit's "unpack scripts?"): it reports them as still open, correctly, but only `answer_dialog` on a modal window has a
   typed answer. A top-level `#32770` window with buttons could be offered the same way.

## What the survey changed on this machine (it was meant to change nothing)

- `ControlInterfaceGenerator\4.3.2.2\` (336 MB) and `wabbajack-cli.bat` in the CIG repo: Wabbajack's self-update, see
  fault 1. Left in place and kept out of git (the repo's local exclude file). Deleting them is the owner's or Main
  Agent's call; the owner's own Wabbajack folder was not touched and still holds 4.2.3.0.
- `CreationKitPrefs.ini` in the Skyrim folder was rewritten when the Creation Kit closed (its own doing, every exit).
  `CreationKit.ini` is unchanged, and Scripts.zip was not unpacked (answered No).
- Bethini Pie was ended with the project's graceful-first process tool (`prockill`) after it refused every close
  request; its `Bethini.ini` and the profile's game INI files are unchanged (file times checked).
- Each tool wrote its own log or cache where it always does. No plugin, profile, Overwrite or game data file was
  written; MO2 and the game were not started.

## Second pass (needs MO2 running on a test profile - Main Agent's batch)

Through `mo2-ctl run` on the Njordlinger test profile, read-only as above: Outfit Studio (the editor), DynDOLOD (the
options window), and xEdit once more with the real load order to confirm the record tree stays opaque at full size.
Each with `tools/survey_tool.py --attach <pid>` on the pid `run` returns.
