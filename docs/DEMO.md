# Demo - an agent drives 7-Zip File Manager through CIG (M7 run, 2026-11-20)

7-Zip File Manager had never been scripted, and CIG holds no 7-Zip code. This is the conversation between the agent
(the proof script `tools/prove_m7_7zfm.py`) and CIG's MCP server, shortened. Ids such as `43e787c1` are CIG's
short element ids. Every value shown comes from the recorded run in [proofs/M7-7zfm.md](proofs/M7-7zfm.md).

```
> cig_launch  exe="C:\Program Files\7-Zip\7zFM.exe"  args=["…\var\proof\m7"]
< ok · pid 14712 · started unelevated · presence: owner idle

> cig_detect  target="14712"
< framework: win32 · version 26.02 · adapters: [uia 0.73]

> cig_actions app="14712"
< … menu MenuBar 'Application' · system_menu MenuBar 'System' · select ListItem 'sample.txt' …

> cig_do  action_id="….menu"  args={"path": "File/Create Folder"}
< ok · menu File > Create Folder (F7)            ← CIG notes the dialog that just opened as its own

> cig_actions
< set_text Edit 'Folder name:' (value "New Folder") · answer_dialog Window 'Create Folder' {button: ["OK","Cancel"]}

> cig_do  action_id="….set_text"  args={"text": "made-by-cig"}
< ok · verified (read back "made-by-cig")        ← a pre-filled default in a dialog CIG opened: a plain write

> cig_do  action_id="….answer_dialog"  args={"button": "OK"}
< ok · verified (dialog gone)                    → the folder exists on disk

> cig_do  action_id="….select"   (ListItem 'sample.txt')        < ok · verified (selected)
> cig_do  action_id="….menu"  args={"path": "File/CRC/CRC-32"} < ok
> cig_tree
< … the checksum dialog shows A778AE0E           ← equals zlib.crc32 of the file, computed by the script

> cig_do  action_id="….menu"  args={"path": "File/Delete"}
< REFUSED · confirm_required · "destructive action: needs confirm with the person's own words (preview returned)"

> cig_close app="14712"
< ok · closed gracefully
```

Not shown, but always running: the presence check before every write, the action log entry for every call (refusals
included), and the read-back after every write.
