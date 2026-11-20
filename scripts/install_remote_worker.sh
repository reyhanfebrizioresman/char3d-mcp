#!/usr/bin/env bash
# Run on an owner-controlled worker / in a provider image build, never automatically.
# No MPFB, engine checkout, venv or pip packages are required.
set -euo pipefail
if [[ "${1:-}" == --help ]]; then
  echo 'Usage: scripts/install_remote_worker.sh [official-blender-archive-url sha256 destination]'
  echo 'Without arguments: verify python3, rsync and Blender. With arguments: install Blender only.'
  echo 'Install OS dependencies yourself (e.g. python3 rsync libegl1 libgl1 libxrender1 libxi6 libxkbcommon0).'
  echo 'GPU images also need the provider GPU runtime, host drivers and EGL/Vulkan support.'
  exit 0
fi
if [[ $# -ne 0 ]]; then
  [[ $# -eq 3 && "$1" == https://download.blender.org/release/* && "$2" =~ ^[a-fA-F0-9]{64}$ ]] || {
    echo 'Supply an official Blender archive URL, its published SHA256, and install directory.' >&2; exit 1;
  }
  archive="$(mktemp --suffix=.tar.xz)"
  trap 'rm -f -- "$archive"' EXIT
  curl --fail --location --proto '=https' --tlsv1.2 --output "$archive" "$1"
  echo "$2  $archive" | sha256sum --check --status
  mkdir -p -- "$3"
  tar -xJf "$archive" --strip-components=1 -C "$3"
  worker_blender="$3/blender"
else
  worker_blender="${CHAR3D_BLENDER:-blender}"
fi
command -v python3 >/dev/null
command -v rsync >/dev/null
python3 -c 'import fcntl,sys; assert sys.version_info >= (3,9), "Python 3.9+ required"'
"$worker_blender" --version
echo 'REMOTE WORKER REQUIREMENTS OK (GPU access is verified during a render).'
