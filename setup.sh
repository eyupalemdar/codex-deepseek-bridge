#!/bin/sh
# Native macOS entry point; no PowerShell or Python packages required.
set -eu
if ! command -v python3 >/dev/null 2>&1; then
    echo 'Python 3.9+ is required. Install Python 3, then run setup.sh again.' >&2
    exit 1
fi
exec python3 "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)/src/macos/bridge.py" setup "$@"
