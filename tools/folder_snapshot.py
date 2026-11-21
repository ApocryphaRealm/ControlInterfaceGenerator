"""Back up a folder with a SHA-256 manifest, verify a backup, or diff a folder against a manifest.

  py -3 tools/folder_snapshot.py backup <src> <dest-parent> <name>   copy + manifest.json, then verify the copy
  py -3 tools/folder_snapshot.py diff <src> <manifest.json>          exit 0 = byte-identical (no file added, removed,
                                                                     changed, or re-timed), 1 = differences listed
Used before any launch of a program whose real data folder must not change (M4, Main Agent's order 2026-11-20).
"""
import hashlib
import json
import os
import shutil
import sys
import time
from pathlib import Path


def manifest(root: Path) -> dict:
    out = {}
    for p in sorted(root.rglob("*")):
        if p.is_file():
            h = hashlib.sha256()
            with open(p, "rb") as f:
                for chunk in iter(lambda: f.read(1 << 20), b""):
                    h.update(chunk)
            st = p.stat()
            out[str(p.relative_to(root)).replace("\\", "/")] = {"sha256": h.hexdigest(), "size": st.st_size,
                                                                  "mtime_ns": st.st_mtime_ns}
    return out


def diff(a: dict, b: dict) -> list[str]:
    lines = []
    for k in sorted(set(a) | set(b)):
        if k not in b:
            lines.append(f"REMOVED  {k}")
        elif k not in a:
            lines.append(f"ADDED    {k}")
        elif a[k]["sha256"] != b[k]["sha256"]:
            lines.append(f"CHANGED  {k}")
        elif a[k]["mtime_ns"] != b[k]["mtime_ns"]:
            lines.append(f"RETIMED  {k}")
    return lines


def main():
    cmd = sys.argv[1]
    if cmd == "backup":
        src, parent, name = Path(sys.argv[2]), Path(sys.argv[3]), sys.argv[4]
        dest = parent / f"{name}-{time.strftime('%Y%m%d-%H%M%S')}"
        before = manifest(src)
        shutil.copytree(src, dest / "files", copy_function=shutil.copy2)
        (dest / "manifest.json").write_text(json.dumps({"source": str(src), "files": before}, indent=1),
                                            encoding="utf-8")
        copied = manifest(dest / "files")
        bad = [k for k in before if k not in copied or copied[k]["sha256"] != before[k]["sha256"]]
        print(json.dumps({"backup": str(dest), "files": len(before), "copied": len(copied),
                          "bytes": sum(v["size"] for v in before.values()), "hash_mismatches": bad}))
        sys.exit(0 if not bad and len(copied) == len(before) else 1)
    if cmd == "diff":
        src, mf = Path(sys.argv[2]), Path(sys.argv[3])
        want = json.loads(mf.read_text(encoding="utf-8"))["files"]
        lines = diff(want, manifest(src))
        print("\n".join(lines) if lines else "IDENTICAL (same files, same bytes, same times)")
        sys.exit(0 if not lines else 1)


if __name__ == "__main__":
    main()
