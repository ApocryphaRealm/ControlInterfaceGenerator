"""Build cig.exe with PyInstaller (plan section 5). Used locally and by .github/workflows/release.yml.

  py -3 tools/build_exe.py            -> dist/cig.exe, with a Windows version resource taken from VERSION

The version resource is not decoration: SignPath Foundation requires every signed binary to carry the project's
product name and the release's product version, the same in each build (docs/SIGNING.md).
"""
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
NAME = "Control Interface Generator"


def version_file(version: str) -> Path:
    parts = [int(x) for x in version.split(".")] + [0] * (4 - len(version.split(".")))
    t = tuple(parts[:4])
    text = f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={t}, prodvers={t}, mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0,
                    date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', 'ApocryphaRealm'),
      StringStruct('FileDescription', '{NAME} - a safety-checked MCP control interface for Windows programs'),
      StringStruct('FileVersion', '{version}'),
      StringStruct('InternalName', 'cig'),
      StringStruct('LegalCopyright', 'GPL-3.0-or-later'),
      StringStruct('OriginalFilename', 'cig.exe'),
      StringStruct('ProductName', '{NAME}'),
      StringStruct('ProductVersion', '{version}')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""
    out = REPO / "build" / "version_info.txt"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    return out


def machine_paths() -> list:
    """Every file that goes into the exe, checked for an absolute Windows path (a drive letter, then a folder name) in
    ASCII or UTF-16 - a build-machine path must never ship (rule 45). Build output, so it runs after the bridge build."""
    pat = re.compile(rb"(?<![A-Za-z0-9])[A-Za-z]:(?:\\\\?|/)[A-Za-z_]")
    roots = [REPO / "cig", REPO / "library", REPO / "config", REPO / "var" / "bridges" / "dotnet",
             REPO / "bridges" / "python", REPO / "cig_cli.py"]
    hits = []
    for root in roots:
        files = [root] if root.is_file() else [p for p in root.rglob("*") if p.is_file() and "__pycache__" not in p.parts]
        for f in files:
            raw = f.read_bytes()
            for blob in (raw, raw.replace(b"\x00", b"")):
                m = pat.search(blob)
                if m:
                    hits.append(f"{f.relative_to(REPO)}: ...{blob[max(0, m.start() - 20):m.end() + 40]!r}")
                    break
    return hits


def main() -> int:
    version = (REPO / "VERSION").read_text(encoding="utf-8").strip()
    vf = version_file(version)
    sep = ";"
    # the in-process bridges travel inside the exe (cig/adapters/bridge.py assets_dir copies them out on first use)
    rc = subprocess.call([sys.executable, str(REPO / "tools" / "build_bridges.py")], cwd=str(REPO))
    dll = REPO / "var" / "bridges" / "dotnet" / "Cig.Bridge.DotNet.dll"
    if rc != 0 or not dll.is_file():
        print(f"the .NET bridge did not build ({dll}); refusing to make an exe without it")
        return 1
    hits = machine_paths()
    if hits:
        print("refusing to build: an absolute path would ship inside cig.exe (rule 45)\n  " + "\n  ".join(hits))
        return 1
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile", "--console", "--name", "cig",
           "--version-file", str(vf),
           "--add-data", f"{REPO / 'library'}{sep}library",
           "--add-data", f"{REPO / 'config'}{sep}config",
           "--add-data", f"{REPO / 'VERSION'}{sep}.",
           "--add-data", f"{REPO / 'var' / 'bridges' / 'dotnet'}{sep}bridge-assets/dotnet",
           "--add-data", f"{REPO / 'bridges' / 'python'}{sep}bridge-assets/python",
           "--collect-all", "uiautomation", "--collect-submodules", "comtypes", "--collect-submodules", "cig",
           # only the MCP parts CIG uses: collecting all of 'mcp' pulls in mcp.cli, which needs typer
           "--collect-submodules", "mcp.server", "--collect-submodules", "mcp.shared", "--hidden-import", "mcp.types",
           "--hidden-import", "win32timezone",
           "--distpath", str(REPO / "dist"), "--workpath", str(REPO / "build" / "pyinstaller"),
           "--specpath", str(REPO / "build"),
           str(REPO / "cig_cli.py")]
    print(" ".join(cmd))
    rc = subprocess.call(cmd, cwd=str(REPO))
    if rc != 0:
        return rc
    # the bundled packages' licences travel beside the exe (dist/THIRD-PARTY-NOTICES.txt)
    return subprocess.call([sys.executable, str(REPO / "tools" / "third_party_notices.py"),
                            str(REPO / "dist" / "THIRD-PARTY-NOTICES.txt")], cwd=str(REPO))


if __name__ == "__main__":
    sys.exit(main())
