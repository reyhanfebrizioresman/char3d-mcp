#!/usr/bin/env bash
# Called by install_tts.sh only after explicit acceptance. Separate CPU environment.
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname -- "$SCRIPT_DIR")"
TTS_DIR="${CHAR3D_TTS_DIR:-$HOME/.local/share/char3d/tts}"
F5_PYTHON="${CHAR3D_F5_PYTHON:-$HOME/.local/share/char3d/f5-venv/bin/python}"
if [[ "${1:-}" != --yes ]]; then
  echo 'F5: ~3 GB CPU environment + 1,402,798,428 bytes of weights/config; personal/non-commercial.'
  cat "$SCRIPT_DIR/f5_assets.tsv"
  read -r -p 'Download and install? [y/N] ' answer
  [[ "$answer" == y || "$answer" == Y ]] || exit 1
fi
if [[ ! -x "$F5_PYTHON" ]]; then
  "${CHAR3D_F5_BOOTSTRAP_PYTHON:-python3.13}" -m venv "$(dirname -- "$(dirname -- "$F5_PYTHON")")"
fi
"$F5_PYTHON" -m pip install 'torch==2.15.0+cpu' 'torchaudio==2.11.1+cpu' --index-url https://download.pytorch.org/whl/cpu
"$F5_PYTHON" -m pip install -r "$ROOT/requirements-f5.txt"
while read -r filename bytes sha url; do
  [[ -z "$filename" || "$filename" == \#* ]] && continue
  path="$TTS_DIR/f5/$filename"
  mkdir -p -- "$(dirname -- "$path")"
  echo "$filename: $bytes bytes; sha256 $sha"
  if [[ ! -f "$path" ]]; then
    curl --fail --location --retry 3 --connect-timeout 20 --output "$path.part" "$url"
    [[ "$(wc -c < "$path.part")" -eq "$bytes" ]] || { echo 'Size mismatch' >&2; exit 1; }
    echo "$sha  $path.part" | sha256sum -c -
    mv -- "$path.part" "$path"
  else
    [[ "$(wc -c < "$path")" -eq "$bytes" ]] || { echo 'Cached size mismatch' >&2; exit 1; }
    echo "$sha  $path" | sha256sum -c -
  fi
done < "$SCRIPT_DIR/f5_assets.tsv"
"$F5_PYTHON" - "$TTS_DIR/f5/vocab.txt" <<'PY'
import hashlib, shutil, sys
from importlib.resources import files
from pathlib import Path
source = files('f5_tts').joinpath('infer/examples/vocab.txt')
data = source.read_bytes()
if len(data) != 11255 or hashlib.sha256(data).hexdigest() != '4e173934be56219eb38759fa8d4c48132d5a34454f0c44abce409bcf6a07ec46':
    raise RuntimeError('Bundled vocabulary changed')
Path(sys.argv[1]).write_bytes(data)
PY
mkdir -p "$TTS_DIR/f5/voices"
echo "F5 INSTALL OK: $F5_PYTHON; $TTS_DIR/f5"
echo 'Builtin references are generated from installed Piper on first use. Install Piper separately.'
