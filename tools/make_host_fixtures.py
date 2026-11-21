"""Cut the host-adapter test fixtures out of a recorded live run of MO2 Agent Control's window commands.

  python tools/make_host_fixtures.py <folder holding replies.log> [--out tests/fixtures/host-mo2]

replies.log is what the live test of MO2 Agent Control 1.1.0 kept (request 3309, 2026-11-20): for every command a
header "=== step <id> ...", the command line "$ mo2_ctl ...", then the plugin's JSON reply. Five replies become the
states of the fake channel in tests/test_host_mo2.py: info, MO2's main window, the Modlist Manager window, its Apply
question, its Restore picker. The instance path in them is replaced by a placeholder: nothing machine-specific is kept.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
WANT = {"info": ("1", "info"), "main": ("2", "ui_tree"), "mm": ("4b", "ui_tree"), "question": ("6c", "ui_tree"),
        "restore": ("10b", "ui_tree")}
PLACEHOLDER = "X:/MO2"


def replies(text: str) -> list[tuple[str, str, dict]]:
    out = []
    for block in re.split(r"(?m)^=== step ", text)[1:]:
        head, _, rest = block.partition("\n")
        cmdline, _, body = rest.partition("\n")
        try:
            out.append((head.split()[0], cmdline, json.loads(body)))
        except ValueError:
            continue
    return out


def scrub(obj, instance: str):
    if isinstance(obj, dict):
        return {k: scrub(v, instance) for k, v in obj.items()}
    if isinstance(obj, list):
        return [scrub(v, instance) for v in obj]
    if isinstance(obj, str) and instance:
        for form in (instance, instance.replace("/", "\\")):
            obj = obj.replace(form, PLACEHOLDER)
    return obj


def main(argv) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("folder")
    p.add_argument("--out", default=str(REPO / "tests" / "fixtures" / "host-mo2"))
    a = p.parse_args(argv)
    got = replies((Path(a.folder) / "replies.log").read_text(encoding="utf-8"))
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    instance = ""
    for name, (step, cmd) in WANT.items():
        hit = next((r for s, c, r in got if s == step and c.split()[2:3] == [cmd] and r.get("ok")), None)
        if hit is None:
            print(f"no reply for step {step} ({cmd})")
            return 1
        if name == "info":
            instance = hit.get("instance", "")
        data = scrub(hit, instance)
        if name == "info":
            data["pid"] = 4242
        (out / f"{name}.json").write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"{name}.json  <- step {step}: {len(data.get('controls', []))} controls")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
