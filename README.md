# Control Interface Generator (CIG)

CIG lets an AI agent operate an ordinary Windows program without screenshots or synthetic mouse clicks.

It works in four steps:

1. It detects what the program is built with: Win32, WinForms, WPF, WinUI, Qt, Electron or a console program.
2. It looks that framework up in a capability library, which is data rather than code.
3. It applies rules that turn each UI element into a typed action, such as `set_text`, `set_checked`, `choose`, `menu` or `answer_dialog`.
4. It serves those actions as an MCP server.

A program is handled through its framework's library entry, never through code written for that one program.

## Safety

Every action passes the safety layer before it reaches a program:

- Reads are always allowed.
- Writes are refused while the person at the machine is using it, unless the call carries `confirm` with the person's own words.
- For third-party programs, a write is refused outright when that program's window is in front and has had recent real input. `confirm` does not override this.
- Destructive actions (delete, remove, discard, "Don't Save"... in eleven languages) always need `confirm`.
- Password fields, credential and security windows, and browsers are never acted on.
- Every call is logged as JSON lines, refusals included, with secrets redacted. Files an action is known to change are backed up first, and `cig_undo` restores them.
- `dry_run` checks everything and returns a preview without acting.

## Tools (MCP, stdio)

| Tool | What it does |
|---|---|
| `cig_status` | Version, loaded adapters, the presence reading and the policy thresholds |
| `cig_apps` | Programs with windows that CIG can see |
| `cig_detect` | Framework, version and ranked adapters for a program |
| `cig_launch` | Starts a program at normal integrity |
| `cig_tree` | Compact element tree with stable short ids |
| `cig_actions` | The generated typed action set, each with a JSON input schema |
| `cig_do` | Performs one action (`dry_run`, `confirm`) and reads the result back |
| `cig_read` | Reads one element's current state |
| `cig_wait` | Waits for an element or window |
| `cig_see` | One screenshot of the program's window, on request only |
| `cig_log` | The action log |
| `cig_undo` | Restores a backup |

To register it:

```
claude mcp add --scope user cig -- py -3 "<repo>\cig_server.py"
```

## Layout

| Path | What it holds |
|---|---|
| `cig/` | The engine, safety layer, detector and adapters |
| `library/` | Framework entries, rules, the destructive-word lexicon and schemas, all data |
| `config/policy.json` | Thresholds, plus the allow and deny lists |
| `tests/` | Unit and safety tests on recorded fixtures (`pytest -m "not live"`), and live tests (`-m live`) |

## Licence

GPL-3.0-or-later.
