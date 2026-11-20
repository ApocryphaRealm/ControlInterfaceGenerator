# Prior art - searched 2026-11-20 before registering CIG

The owner's rule (2026-11-01): search Nexus and GitHub for something that already does this before making a new one.

## Nexus (Modding Tools section, searched 2026-11-20 through houseCARL)

| Query | Found | Does it already do what CIG does? |
|---|---|---|
| `automation` | nothing | - |
| `MCP` | Vortex MCP (id 2263), MCP - MO2 (id 2549), Claude.AI MCP Bridge (id 1743, Vortex) | No. Each is a hand-written MCP server for ONE program. CIG generates the interface from what a program's framework exposes, with no per-program code. Vortex MCP and MCP - MO2 are useful cross-checks for M3/M4 proofs and are not dependencies. |

## GitHub and package indexes (plan section 3, researched 2026-10-24, re-read 2026-11-20)

| Project | Licence | Relation to CIG |
|---|---|---|
| Windows-MCP (CursorTouch) | MIT | Closest: a desktop MCP server with a UIA state tool plus mouse and keyboard. It has no framework library, no typed actions generated from rules, and no presence or confirm safety layer. Read for ideas only. |
| Playwright MCP, chrome-devtools-mcp | Apache-2.0 | Browser-only (CDP). Reference design for "snapshot, then act". |
| pywinauto, uiautomation, comtypes | BSD-3 / Apache-2.0 / MIT | Building blocks that CIG uses. They are libraries, not generators. |
| FlaUI, WinAppDriver | MIT | A .NET UIA library and an abandoned WebDriver server. Reference only. |

Conclusion: nothing found turns a program's framework into a typed, policy-guarded MCP action set without per-program code. CIG goes ahead.
