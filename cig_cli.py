"""Entry point frozen into cig.exe (tools/build_exe.py)."""
import sys

from cig.cli import main

if __name__ == "__main__":
    sys.exit(main())
