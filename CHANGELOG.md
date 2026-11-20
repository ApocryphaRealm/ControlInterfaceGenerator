# Changelog

## 1.0.0 (untested)

- M0: the safety layer, made of presence (the owner-input watcher's real-input file, with GetLastInputInfo as a fallback), a policy with deny lists that `confirm` cannot override, a third-party foreground rule, confirm-first for destructive actions, and dry run. Also added: an append-only action log with redaction, backups with undo, the fixture format and its JSON schema, locators with a fingerprint second chance (an element CIG cannot find is refused, never guessed), and adapter rules as data.
- M0: an MCP server (stdio) with the meta tools, and a fixture adapter that runs the whole path with no program running.
