#!/usr/bin/env bash
# Explicit owner-run installer; tools never invoke this script.
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec "${CHAR3D_PYTHON:-$SCRIPT_DIR/../.venv/bin/python}" "$SCRIPT_DIR/install_toon_asset.py" vrm "$@"
