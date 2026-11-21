"""Prove that an isolated CDP launch leaves the owner's real data folder untouched - with the program REALLY running.

  py -3 tools/prove_isolation.py <exe> <profile_flag> <real data folder> <manifest.json> <ready button label>

1. the real folder must equal the backup manifest before anything starts
2. launch through CIG (cdp + the library's isolation + guards)
3. the program must REACH ITS MAIN UI: a button with <ready button label> must be offered over CDP (a program that
   quits at start proves nothing - learned 2026-11-20); then it stays idle for 20 s
4. close gracefully (guards restore), then the real folder must still equal the manifest, byte for byte
Exit 0 only when all four hold.
"""
import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tools"))

import folder_snapshot  # noqa: E402
from cig import launch  # noqa: E402
from cig.adapters.cdp import CdpAdapter  # noqa: E402
from cig.engine import Engine  # noqa: E402


def main(exe, flag, real, mf, ready):
    want = json.loads(Path(mf).read_text(encoding="utf-8"))["files"]
    pre = folder_snapshot.diff(want, folder_snapshot.manifest(Path(real)))
    print("1 before:", "IDENTICAL" if not pre else pre[:5])
    if pre:
        return 1
    r = launch.launch(exe, [], cdp=True, profile_flag=flag, wait_s=60)
    print("2 launch:", json.dumps({k: r.get(k) for k in ("ok", "pid", "port", "isolation_env", "guarded", "reason")}))
    if not r.get("ok"):
        return 1
    e = Engine([CdpAdapter()])
    reached = False
    t0 = time.time()
    while time.time() - t0 < 60:
        try:
            acts = e.actions(str(r["pid"]))["actions"]
            if any(a["action"] == "invoke" and a["label"].endswith(f"'{ready}'") for a in acts):
                reached = True
                break
        except Exception:                                  # noqa: BLE001 - not ready yet
            pass
        time.sleep(1)
    print(f"3 reached its main UI ('{ready}' offered over CDP): {reached} after {time.time() - t0:.0f}s")
    if reached:
        time.sleep(20)
    c = launch.close(r["pid"], 30)
    print("4 close:", json.dumps({k: c.get(k) for k in ("ok", "closed")}),
          "guards:", (c.get("side_effects_restored") or {}).get("all_restored"))
    time.sleep(5)
    post = folder_snapshot.diff(want, folder_snapshot.manifest(Path(real)))
    print("5 after:", "IDENTICAL (same files, bytes, times)" if not post else post[:20])
    return 0 if reached and not post and c.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:6]))
