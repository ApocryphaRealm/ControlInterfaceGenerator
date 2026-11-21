# Changelog

## 1.0.0 (untested)

- M0: the safety layer, made of presence (the owner-input watcher's real-input file, with GetLastInputInfo as a fallback), a policy with deny lists that `confirm` cannot override, a third-party foreground rule, confirm-first for destructive actions, and dry run. Also added: an append-only action log with redaction, backups with undo, the fixture format and its JSON schema, locators with a fingerprint second chance (an element CIG cannot find is refused, never guessed), and adapter rules as data.
- M0: an MCP server (stdio) with the meta tools, and a fixture adapter that runs the whole path with no program running.
- M1: the detector (process metadata, modules with version-conditioned evidence, window classes, PE subsystem, files beside the exe, exe strings, and a UIA sample with a richness score), 18 framework library entries, the doc-derived UIA control-type table, the safe launcher, and `cig_apps` / `cig_detect`. It detected 12 of 12 installed programs correctly.
- M2: the generic UIA adapter (patterns only; `keys` is the last resort), a per-app cache (ids survive a restart; a new program version starts clean), `cig_see` (PrintWindow, on request only), and menu paths learned from opened submenus. Proof: Notepad driven through the MCP server, 19 of 19 steps.
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

