#!/usr/bin/env bash
# Local UI, using the same optional environment and virtualenv as run_mcp.sh.
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"
ENV_FILE="${CHAR3D_ENV_FILE:-$HOME/.config/char3d/env}"
if [ -f "$ENV_FILE" ]; then
  set -a; . "$ENV_FILE"; set +a
fi
if ! .venv/bin/python -c "import starlette, uvicorn, mcp" >/dev/null 2>&1; then
  echo "Jalankan instalasi requirements.txt di .venv terlebih dahulu." >&2
  exit 1
fi
exec .venv/bin/python -m webui "$@"
