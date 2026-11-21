"""Build CIG's in-process bridges into var/bridges/ (or $CIG_BRIDGES).
  py -3 tools/build_bridges.py      -> var/bridges/dotnet/Cig.Bridge.DotNet.dll (needs the .NET 8+ SDK)
The Python bridge is plain source (bridges/python) and needs no build."""
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def main() -> int:
    out = REPO / "var" / "bridges" / "dotnet"
    r = subprocess.call(["dotnet", "build", str(REPO / "bridges" / "dotnet" / "Cig.Bridge.DotNet.csproj"), "-c",
                         "Release", "-o", str(out)])
    print("built" if r == 0 else "FAILED", out / "Cig.Bridge.DotNet.dll")
    return r


if __name__ == "__main__":
    sys.exit(main())
