#!/usr/bin/env bash
# Models are installed only here, never when a TTS tool is called.
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname -- "$SCRIPT_DIR")"
PYTHON="${CHAR3D_PYTHON:-$ROOT/.venv/bin/python}"
TTS_DIR="${CHAR3D_TTS_DIR:-$HOME/.local/share/char3d/tts}"
engines=()
yes=0
for arg in "$@"; do
  case "$arg" in
    --yes) yes=1 ;;
    piper|edge|f5) engines+=("$arg") ;;
    -h|--help)
      echo "Usage: scripts/install_tts.sh [piper] [edge] [f5 --yes]"
      echo "Default: Piper offline + Edge online packages. CHAR3D_TTS_DIR overrides model storage."
      echo "Piper: ~34 MB package/espeak + 63 MB voice. Runtime GPL-3.0; voice personal use (dataset unclear)."
      echo "Edge: small package; unofficial Microsoft API, sends dialog text online."
      echo "F5: >=1.35 GB checkpoint + vocoder + roughly 3 GB CPU PyTorch environment."
      echo "F5 code MIT; Indonesian fine-tune Apache-2.0; upstream base weights CC-BY-NC, non-commercial."
      exit 0 ;;
    *) echo "Unknown option: $arg (see --help)" >&2; exit 1 ;;
  esac
done
if (( ${#engines[@]} == 0 )); then engines=(piper edge); fi
for engine in "${engines[@]}"; do
  if [[ "$engine" == f5 ]]; then
    echo "F5 OPTIONAL: >=1.35 GB checkpoint + vocoder + roughly 3 GB CPU PyTorch environment."
    echo "License: code MIT; fine-tune Apache-2.0; upstream weights CC-BY-NC (NON-COMMERCIAL)."
    cat "$SCRIPT_DIR/f5_assets.tsv"
    if (( ! yes )); then
      read -r -p 'Download F5 weights/vocoder and install a separate CPU environment? [y/N] ' answer
      [[ "$answer" == y || "$answer" == Y ]] || exit 1
    fi
  fi
done
for engine in "${engines[@]}"; do
  case "$engine" in
    piper)
      "$PYTHON" -m pip install 'piper-tts>=1.8.0,<1.9'
      mkdir -p "$TTS_DIR/piper"
      while read -r file bytes sha url; do
        [[ -z "$file" || "$file" == \#* ]] && continue
        target="$TTS_DIR/piper/$file"
        echo "$file: $bytes bytes; sha256 $sha"
        if [[ ! -f "$target" ]]; then
          curl --fail --location --retry 3 --connect-timeout 20 --output "$target.part" "$url"
          [[ "$(wc -c < "$target.part")" -eq "$bytes" ]] || { echo "Size mismatch: $file" >&2; exit 1; }
          echo "$sha  $target.part" | sha256sum -c -
          mv -- "$target.part" "$target"
        else
          [[ "$(wc -c < "$target")" -eq "$bytes" ]] || { echo "Cached size mismatch: $target; remove and rerun" >&2; exit 1; }
          echo "$sha  $target" | sha256sum -c -
        fi
      done < "$SCRIPT_DIR/tts_voices.tsv"
      ;;
    edge) "$PYTHON" -m pip install 'edge-tts>=7.3,<7.4' ;;
    f5)
      "$SCRIPT_DIR/install_f5.sh" --yes
      ;;
  esac
done
echo "TTS INSTALL OK: $TTS_DIR"
