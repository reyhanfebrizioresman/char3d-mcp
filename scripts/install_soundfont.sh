#!/usr/bin/env bash
# Explicit installer only. Runtime rendering never downloads assets or uses PyAudio.
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname -- "$SCRIPT_DIR")"
TARGET="${CHAR3D_SOUNDFONT:-$HOME/.local/share/char3d/soundfonts/GeneralUser-GS.sf2}"
PYTHON="${CHAR3D_PYTHON:-$ROOT/.venv/bin/python}"
if [[ "${1:-}" == --help ]]; then
  echo 'Usage: scripts/install_soundfont.sh [--yes]'
  echo 'Installs tinysoundfont 0.3.7 --no-deps and GeneralUser GS 2.0.3 (32,319,396 bytes).'
  echo 'CHAR3D_SOUNDFONT overrides destination. Music creation: private/commercial permitted.'
  exit 0
fi
echo 'GeneralUser GS 2.0.3: 32,319,396 bytes + 2,317-byte license; tinysoundfont 0.3.7.'
echo 'License permits private and commercial music creation; see installed LICENSE.'
if [[ "${1:-}" != --yes ]]; then
  read -r -p 'Download and install these files and package? [y/N] ' answer
  [[ "$answer" == y || "$answer" == Y ]] || exit 1
fi
"$PYTHON" -m pip install --no-deps 'tinysoundfont==0.3.7'
mkdir -p -- "$(dirname -- "$TARGET")"
while read -r filename bytes sha url; do
  [[ -z "$filename" || "$filename" == \#* ]] && continue
  path="$(dirname -- "$TARGET")/$filename"
  [[ "$filename" == GeneralUser-GS.sf2 ]] && path="$TARGET"
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
done < "$SCRIPT_DIR/soundfonts.tsv"
echo "SOUNDFONT INSTALL OK: $TARGET"
