"""Build cig.exe with PyInstaller (plan section 5). Used locally and by .github/workflows/release.yml.

  py -3 tools/build_exe.py            -> dist/cig.exe, with a Windows version resource taken from VERSION

The version resource is not decoration: SignPath Foundation requires every signed binary to carry the project's
product name and the release's product version, the same in each build (docs/SIGNING.md).
"""
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


def main() -> int:
    version = (REPO / "VERSION").read_text(encoding="utf-8").strip()
    vf = version_file(version)
    sep = ";"
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile", "--console", "--name", "cig",
           "--version-file", str(vf),
           "--add-data", f"{REPO / 'library'}{sep}library",
           "--add-data", f"{REPO / 'config'}{sep}config",
           "--add-data", f"{REPO / 'VERSION'}{sep}.",
           "--collect-all", "uiautomation", "--collect-submodules", "comtypes", "--collect-submodules", "cig",
           # only the MCP parts CIG uses: collecting all of 'mcp' pulls in mcp.cli, which needs typer
           "--collect-submodules", "mcp.server", "--collect-submodules", "mcp.shared", "--hidden-import", "mcp.types",
           "--hidden-import", "win32timezone",
           "--distpath", str(REPO / "dist"), "--workpath", str(REPO / "build" / "pyinstaller"),
           "--specpath", str(REPO / "build"),
           str(REPO / "cig_cli.py")]
    print(" ".join(cmd))
    return subprocess.call(cmd, cwd=str(REPO))


if __name__ == "__main__":
    sys.exit(main())
