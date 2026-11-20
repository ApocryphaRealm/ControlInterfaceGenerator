"""Entry point for the CIG MCP server (stdio)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from cig.server import main  # noqa: E402

if __name__ == "__main__":
    main()
