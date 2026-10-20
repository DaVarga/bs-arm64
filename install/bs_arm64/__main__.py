"""Entry point: `python3 -I install/bs_arm64 ...` (what bs-arm64.sh runs) or `python3 -m bs_arm64`."""
import sys
from pathlib import Path

# Run as a directory, Python puts this directory itself on sys.path; the package's parent is needed.
sys.path[0] = str(Path(__file__).resolve().parent.parent)

from bs_arm64.cli import main

sys.exit(main())
