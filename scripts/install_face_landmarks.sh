#!/usr/bin/env bash
# Explicit owner-run installer; never modifies the shared virtualenv.
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec "${CHAR3D_PYTHON:-$SCRIPT_DIR/../.venv/bin/python}" "$SCRIPT_DIR/install_toon_asset.py" face "$@"
