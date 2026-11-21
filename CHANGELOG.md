# Changelog

## 1.0.0 (untested)

- M0: the safety layer, made of presence (the owner-input watcher's real-input file, with GetLastInputInfo as a fallback), a policy with deny lists that `confirm` cannot override, a third-party foreground rule, confirm-first for destructive actions, and dry run. Also added: an append-only action log with redaction, backups with undo, the fixture format and its JSON schema, locators with a fingerprint second chance (an element CIG cannot find is refused, never guessed), and adapter rules as data.
- M0: an MCP server (stdio) with the meta tools, and a fixture adapter that runs the whole path with no program running.
- M1: the detector (process metadata, modules with version-conditioned evidence, window classes, PE subsystem, files beside the exe, exe strings, and a UIA sample with a richness score), 18 framework library entries, the doc-derived UIA control-type table, the safe launcher, and `cig_apps` / `cig_detect`. It detected 12 of 12 installed programs correctly.
- M2: the generic UIA adapter (patterns only; `keys` is the last resort), a per-app cache (ids survive a restart; a new program version starts clean), `cig_see` (PrintWindow, on request only), and menu paths learned from opened submenus. Proof: Notepad driven through the MCP server, 19 of 19 steps.
- M3: the host adapter for Mod Organizer 2 (`cig/adapters/host_mo2.py`, adapter `host:mo2-agent-control`). It speaks MO2 Agent Control's loopback protocol (1.1.0 or newer) and turns the plugin's `ui_tree` into the same nodes the UIA adapter produces, so `library/rules/uia.json` generates the actions with no MO2 rule. A press that opens a dialog comes back at once with the dialog described; the dialog is then a modal Window whose buttons are its answers. The caller's `confirm` is handed on to the plugin, whose own in-use refusal is reported as a refusal, and the profile's three list files are backed up before a press. App reference: `mo2` or `mo2:<instance folder>`.
- M3: `tools/prove_m3.py` (the plan 4.2 exit criterion on a scratch MO2) and `tools/make_host_fixtures.py` (cuts the fake channel's states out of a recorded live run).
- Safety, found live:
  - CIG writes only into programs it launched (first-party host programs excepted).
  - A Document is written only when it is empty or holds CIG's own text. `confirm` cannot override either rule.
  - Replacing existing text in an edit field is destructive.
  - Writes and launches are refused while a game holds the screen.
- Fixes, found live:
  - A dialog is answered with its own button, never a combo box's drop-down arrow.
  - Containers are located by position, because a Win32 Pane takes its edit's text as its name.
  - A read-back that loses the element re-resolves it by fingerprint.
  - An action that closes its own element is judged by the read-back.
- M4 (done after isolation, 14/14 - see the next entry): the CDP adapter for Chromium and Electron. It translates the AX tree into the same nodes, so the UIA rules apply unchanged.
  - Added a widget-kit library for custom-drawn controls that are missing from the accessibility tree.
  - `cig_launch(cdp=true, profile_flag=...)` uses a loopback port and a separate data folder.
  - System side-effect guards (registry keys exported before a launch, restored and verified on close) and `cig_close`.
  - The Vortex proof was halted: Vortex reads its default state before it applies `--user-data`.
- M5: the CLI adapter.
  - PowerShell modules become typed commands from `Get-Command` metadata. The kind comes from the verb and ConfirmImpact, and dry runs use the command's own `-WhatIf`.
  - Native tools become typed commands from their own help text, read through a format in `library/cli/help-formats.json`.
  - Runs are argument lists, never shell strings, and secret parameters are never offered.
  - Proof: 7z.exe and Microsoft.PowerShell.Archive, 14 of 14 steps.
- M4 done:
  - A program's library entry can declare an isolation block: environment variables and folders that move ALL of its data into CIG's profile (Vortex: its own end-to-end test hook).
  - `tools/folder_snapshot.py` backs up and byte-diffs a real data folder.
  - `tools/prove_isolation.py` accepts isolation only when the program reached its main UI and the real folder is unchanged byte for byte.
  - Proof: Vortex settings toggled and read back over CDP, 14 of 14, with the owner's Vortex folder byte-identical and the nxm:// handler unchanged.
- M6: the probe harness (`tools/probe.py`).
  - It surveys a running program through the engine: patterns present per control type, Name and AutomationId rates, and deviations from the spec table.
  - With `--actions`, on CIG's own galleries only, it tries each generated action, reads it back and restores the element.
  - It records into `library/probes/` and the framework entries (`probed`, plus quirks with a probe source).
  - Galleries for Win32, WinForms and WPF are built from what Windows ships. Qt 6, WinUI 3 and Electron were probed read-only.
  - Launcher: console programs get a hidden console instead of none, and a window that ignores WM_CLOSE is closed through UIA's WindowPattern.Close.

