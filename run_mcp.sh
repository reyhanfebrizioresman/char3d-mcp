#!/usr/bin/env bash
# Launcher used by Claude / Codex MCP configs. Works from any current directory.
# Creates/repairs the virtualenv on first run (all setup output goes to stderr,
# because stdout is the MCP protocol channel).
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"
# Optional secrets (e.g. FAL_KEY) kept OUTSIDE the repo; one file serves Claude and Codex.
ENV_FILE="${CHAR3D_ENV_FILE:-$HOME/.config/char3d/env}"
if [ -f "$ENV_FILE" ]; then
  set -a; . "$ENV_FILE"; set +a
fi
if ! .venv/bin/python -c "import mcp" >/dev/null 2>&1; then
  echo "char3d: setting up .venv ..." >&2
  rm -rf .venv
  python3 -m venv .venv >&2
  .venv/bin/pip install -q -r requirements.txt >&2
fi
exec .venv/bin/python -m mcp_server.server "$@"
