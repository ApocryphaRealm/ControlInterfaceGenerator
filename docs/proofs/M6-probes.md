# M6 proof - probe harness and reference galleries (2026-11-20 19:51)

Generated from `library/probes/*/*.json` (written by `tools/probe.py`). Every framework the plan names for M6 now has
library data with `source: probe:...`; spec deviations became `quirks` with their probe as the source.

Galleries are CIG's own (`tools/galleries/`), built only from what Windows ships (Win32 via pywin32, WinForms and WPF
via PowerShell's .NET) - nothing was downloaded. Third-party programs were probed READ-ONLY (patterns present, no
actions). Vortex ran on the proven-isolated profile; the owner's Vortex folder was byte-identical afterwards.

| Framework | Probe | Elements | Control types | Actions verified | Spec deviations found |
|---|---|---|---|---|---|
| win32 | win32-gallery (own gallery, actions) | 25 | 14 | 8/8 | Text: forbidden ['Value'] |
| winforms | winforms-gallery (own gallery, actions) | 34 | 20 | 9/9 | ComboBox: missing ['ExpandCollapse']; Text: forbidden ['Value'] |
| wpf | wpf-gallery (own gallery, actions) | 49 | 21 | 13/13 | none |
| qt6 | equalizer-apo-editor (installed app, read-only) | 96 | 17 | - | Image: forbidden ['Invoke']; TabItem: forbidden ['Invoke'] |
| winui3 | paint (installed app, read-only) | 251 | 18 | - | ListItem: missing ['SelectionItem'] |
| electron | vortex-isolated (installed app on an isolated profile, read-only over CDP) | 1146 | 10 | - | Document: missing ['Text']; ListItem: missing ['SelectionItem'] |
