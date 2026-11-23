"""Write THIRD-PARTY-NOTICES.txt: the name, version, licence and licence text of every package cig.exe bundles, read
from the build environment's own package metadata (so the list is what was actually frozen, not a hand-kept copy).

  python tools/third_party_notices.py [OUT]      (run with the interpreter that builds the exe)

Build- and test-only packages are left out, except PyInstaller, whose bootloader is part of the exe."""
import sys
from importlib import metadata
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SKIP = {"pip", "setuptools", "wheel", "pytest", "pluggy", "iniconfig", "pyinstaller-hooks-contrib", "altgraph",
        "pefile", "pywin32-ctypes", "control-interface-generator", "colorama", "packaging"}
LICENSE_NAMES = ("LICENSE", "LICENCE", "COPYING", "NOTICE", "AUTHORS")


def licence_texts(dist) -> list:
    out = []
    for f in dist.files or []:
        name = Path(str(f)).name.upper()
        if any(name.startswith(n) for n in LICENSE_NAMES) and "dist-info" in str(f) or (
                any(name.startswith(n) for n in LICENSE_NAMES) and "licenses" in str(f).lower()):
            try:
                out.append((str(f), Path(dist.locate_file(f)).read_text(encoding="utf-8", errors="replace").strip()))
            except OSError:
                pass
    return out


def main(argv) -> int:
    out_path = Path(argv[1]) if len(argv) > 1 else REPO / "THIRD-PARTY-NOTICES.txt"
    dists = sorted({d.metadata["Name"].lower(): d for d in metadata.distributions()}.items())
    parts = ["Control Interface Generator (cig.exe) - third-party notices",
             "",
             "cig.exe is a PyInstaller bundle. Besides CIG's own code (GPL-3.0-or-later) it contains the Python runtime",
             "(Python Software Foundation License) and the packages below, each under its own licence.",
             ""]
    missing = []
    for key, d in dists:
        if key in SKIP:
            continue
        md = d.metadata
        lic = md.get("License-Expression") or md.get("License") or ""
        if len(lic) > 120:
            lic = lic.splitlines()[0][:120]
        classifiers = [c.split("::")[-1].strip() for c in md.get_all("Classifier") or [] if c.startswith("License ::")]
        parts += ["=" * 78, f"{md['Name']} {md['Version']}",
                  f"Licence: {lic or ', '.join(classifiers) or 'see the text below'}",
                  f"Home: {md.get('Home-page') or next((u.split(',', 1)[1].strip() for u in md.get_all('Project-URL') or []), '')}",
                  ""]
        texts = licence_texts(d)
        if not texts:
            missing.append(md["Name"])
            parts += ["(no licence file in the package metadata; licence as stated above)", ""]
        for _f, t in texts:
            parts += [t, ""]
    out_path.write_text("\n".join(parts) + "\n", encoding="utf-8")
    print(f"wrote {out_path} ({len(dists)} distributions seen; no licence file: {', '.join(missing) or 'none'})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
