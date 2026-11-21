"""One compact line group per surveyed program, from the JSON files tools/survey_tool.py wrote.

  py -3 tools/survey_digest.py [names...] [--dir DIR]
"""
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def digest(d):
    t = d.get("tree") or {}
    det = d.get("detect") or {}
    proc = det.get("process") or {}
    top = (det.get("ranked") or [{}])[0]
    types = t.get("control_types") or {}
    print(f"== {d['name']}  version {proc.get('version') or (d.get('version') or {}).get('product_version')}  "
          f"framework {det.get('framework')} {det.get('framework_version') or ''} (score {top.get('score')}; "
          f"{'; '.join((top.get('evidence') or [])[:3])})")
    if not (d.get("launch") or {}).get("ok"):
        print("   launch:", d.get("launch"))
        return
    print("   windows:", [(w["title"][:50], w["class"][:28], "modal" if w["modal"] else "") for w in d.get("windows", [])][:5])
    print(f"   elements {t.get('elements')}  named {t.get('named_rate')}  automation-id {t.get('aid_rate')}  opaque {t.get('opaque')}  "
          f"uia ids {t.get('framework_ids')}  menus {d.get('menu_paths')}  cpu {d.get('busy_cpu_percent')}/{d.get('busy_cpu_percent_after')}")
    print("   types:", {k: f"{v['count']} ({v['named']} named)" for k, v in list(types.items())[:11]})
    print("   actions:", d.get("actions"))
    for c in (t.get("containers") or [])[:5]:
        print(f"   container {c['type']} '{c['name'] or c['aid'][-40:]}': {c['items']} items {c['sample'][:3]} patterns {c['item_patterns']}")
    if t.get("error"):
        print("   TREE ERROR:", t["error"][:300])
    print("   closed:", d.get("closed"), json.dumps(d.get("close_log"), ensure_ascii=False)[:420])


def main(argv):
    folder = Path(argv[argv.index("--dir") + 1]) if "--dir" in argv else REPO / "var" / "survey"
    names = [a for i, a in enumerate(argv) if not a.startswith("--") and (i == 0 or argv[i - 1] != "--dir")]
    files = [folder / f"{n}.json" for n in names] if names else sorted(folder.glob("*.json"))
    for f in files:
        digest(json.loads(f.read_text(encoding="utf-8")))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
