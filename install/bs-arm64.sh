#!/bin/sh
# Install the native ARM64 Beat Saber runtime into an instance and launch it on ARM64 Proton.
# The tool is the Python package next to this script; see `bs-arm64.sh --help`.
# -I: ignore the user's Python environment (PYTHONPATH, user site-packages).
exec python3 -I "$(dirname "$0")/bs_arm64" "$@"
