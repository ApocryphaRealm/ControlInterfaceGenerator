# Control Interface Generator (CIG)

**An MCP server that lets an AI agent operate ordinary Windows programs without screenshots and without moving the
mouse, using typed, safety-checked actions generated from what each program's UI framework already exposes.**

You point CIG at a program. It works out what the program is built with, looks that framework up in a capability
library, turns every control it finds into a typed action with a JSON schema, and serves those actions to the agent.
CIG has no code for any particular program. A new program is handled by library entries and rules, which are data.

```
agent (Claude Code / any MCP client)
   |  MCP over stdio
CIG server ── safety layer: presence · deny lists · confirm · provenance · dry run · backups · guards · log
   |── detector         process, modules (with versions), window classes, PE subsystem, UIA sample
   |── capability library   frameworks/ · rules/ · apps/ · cdp/ · cli/ · uia/ · probes/   (all data)
   |── adapters         uia (Win32/WinForms/WPF/WinUI/Qt) · cdp (Chromium/Electron) · cli (PowerShell/native)
   |                    · host (Mod Organizer 2, through its plugin channel)
   └── per-app cache    stable element ids across runs, menu paths learned
```

## What it does, concretely

| Ask | What CIG gives the agent |
|---|---|
| `cig_detect` on any running program | Its framework and version (e.g. *Qt 6.7.1*, *Electron 44.2.0*, *WinUI 3*), with adapters ranked |
| `cig_actions` | One typed action per control, for example `set_checked {checked: bool}`, `choose {option: enum}`, `menu {path}`, `answer_dialog {button: enum}`, or a CLI command with a schema built from its own metadata |
| `cig_do` | The action, done through the framework's own API (UIA patterns, DOM calls, PowerShell parameters), then **read back** to confirm it |
| `cig_do dry_run=true` | A preview of what would happen, plus the program's own dry run where it has one (`-WhatIf`) |

## Safety model (enforced in the server, never left to the client)

- **The person comes first.** Writes are refused while the person at the machine is using it. Presence comes from a
  watcher that sees only *real* input, with Windows' idle clock as a fallback.
  - For third-party programs, a write into the window in front during recent input is refused outright.
  - While a game holds the screen, nothing is written or launched.
- **Confirm-first.** Anything destructive needs `confirm` with the person's own words, and that text is logged. This
  covers delete, discard and "Don't Save" in eleven languages, ConfirmImpact=High, switches that delete, and replacing
  text that is already there.
- **Deny lists cannot be overridden:** password fields, credential and security windows, browsers, UAC.
- **Provenance.** CIG writes only into programs it launched. A document is written only when it is empty or holds
  CIG's own text. Text a program pre-fills into a dialog CIG itself just opened counts as the program's default.
- **Isolation, then proof of isolation.** A browser-engine program runs on a separate profile inside CIG's own folder,
  using the library's isolation recipe. Isolation is accepted only when the program reached its main UI AND the real
  data folder is byte-identical afterwards (`tools/prove_isolation.py`).
- **System side-effect guards.** Registry keys a program is known to take over (Vortex: `nxm://`) are exported
  before a launch, and restored and verified on close.
- **Never a guess.** An element is found by its locator, or by fingerprint as a second chance. Anything else is
  refused as stale. Every write is verified by reading it back.
- **Everything is logged** as append-only JSON lines with secrets redacted. Files an action changes are backed up
  first, and `cig_undo` restores them.

## Proofs (each one is a script run through the real MCP server; results checked independently on disk)

| Milestone | Program | Result | Proof |
|---|---|---|---|
| M0 | safety layer, MCP server | 98 tests, including a real stdio MCP handshake | `tests/` |
| M1 | detection on 12 installed programs (Qt 6, Qt 5, Electron, CEF, Chromium, Win32, WinUI 3, UWP, WinForms, console) | 12 of 12 correct | [M1](docs/proofs/M1-detection.md) |
| M2 | Notepad (WinUI 3): open a file through the menus and file dialog, set the text, save | 19/19 | [M2](docs/proofs/M2-notepad.md) |
| M3 | Mod Organizer 2 (Qt 6) through its plugin channel, including its modal dialogs | 44/44 | [M3](docs/proofs/M3-mo2-host.md) |
| M4 | Vortex (Electron) over CDP: custom-drawn switches, on an isolated profile | 14/14 | [M4](docs/proofs/M4-vortex.md) |
| M5 | 7z.exe and a PowerShell module as typed tools (`-WhatIf` dry runs) | 14/14 | [M5](docs/proofs/M5-cli.md) |
| M6 | probe harness on CIG's own galleries (Win32, WinForms, WPF) | 9/9 · 9/11 · 14/14 actions verified | [M6](docs/proofs/M6-probes.md) |
| M6 | official reference galleries: Microsoft **WinUI 3 Gallery** (5 control pages), Microsoft **WPF Gallery**, Qt 6.12, Electron 45 quick-start | 93/97 · 36/39 · 7/9 · 8/10 actions verified | `library/probes/` |
| M7 | **never-scripted programs:** 7-Zip File Manager (UIA) | 15/15 | [M7 7-Zip](docs/proofs/M7-7zfm.md) |
| M7 | **never-scripted programs:** FreeTube (Electron, CDP, isolated profile) | 13/13 | [M7 FreeTube](docs/proofs/M7-freetube.md) |

A short demo transcript of the 7-Zip run is in [docs/DEMO.md](docs/DEMO.md).

## What went wrong on the way, and what it changed

These are recorded because they are why the safety model looks the way it does:

- **Notepad session restore.** A first proof run failed to open its file, kept going, and wrote into a tab that
  Notepad had restored: the owner's document. The file on disk was never touched, and the buffer was restored exactly.
  This led to three rules: provenance, overwrite-is-destructive, and stop at the first failed check.
- **Vortex `--user-data` was not isolation.** Vortex reads its default database before it applies the flag, and
  takes over the `nxm://` handler on every start. This led to the isolation recipes, the "prove it byte for byte"
  check, and the side-effect guards. One isolation check passed hollowly because Vortex had quit at start-up; the
  check now requires the program to reach its main UI.
- **Real frameworks differ from the spec.** The probes found these, and they are kept as library quirks with their
  source:
  - the WinForms ComboBox has no ExpandCollapse
  - the WPF drop-down list reports its choice through Selection, not Value
  - Qt 6 images expose Invoke
  - the Win32 file dialog has four "Open" buttons
  - a Win32 Pane is named after its edit's text

## Install and register

From a release, use the single `cig.exe`:

```
claude mcp add --scope user cig -- "C:\path\to\cig.exe" serve
```

From source (Windows 10/11, Python 3.11+):

```
py -3 -m pip install -e .[test]
claude mcp add --scope user cig -- py -3 "<repo>\cig_server.py"
```

`cig.exe` also offers `cig detect <program>`, `cig apps`, `cig tree <program>` and `cig log`, all read-only. CIG runs
unelevated and starts programs unelevated. Uninstall: delete `cig.exe` and `%LOCALAPPDATA%\CIG`.

## Code signing policy

Free code signing provided by [SignPath.io](https://about.signpath.io), certificate by
[SignPath Foundation](https://signpath.org). This is in progress: until the project is accepted, releases are
unsigned (see [docs/SIGNING.md](docs/SIGNING.md)).

- Releases are built from this repository's source by the `release` GitHub Actions workflow, on GitHub-hosted runners.
- Committers and reviewers: [ApocryphaRealm](https://github.com/ApocryphaRealm)
- Approvers: [ApocryphaRealm](https://github.com/ApocryphaRealm)

**Privacy:** this program will not transfer any information to other networked systems unless specifically requested
by the user or the person installing or operating it. It talks only to its MCP client over stdio, and to programs on
the same machine over 127.0.0.1.

## Licence

GPL-3.0-or-later.
