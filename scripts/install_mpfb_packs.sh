#!/usr/bin/env bash
# Optional MakeHuman CC0 asset packs. Install MPFB first with install_mpfb.sh.
# Usage: scripts/install_mpfb_packs.sh [shirts01 pants01 ...]
# Reuses MPFB_DOWNLOAD_DIR (default ~/.local/opt/dl/mpfb); no download if cached.
set -euo pipefail

BLENDER="${CHAR3D_BLENDER:-$HOME/.local/opt/blender/blender}"
DL="${MPFB_DOWNLOAD_DIR:-$HOME/.local/opt/dl/mpfb}"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
MANIFEST="$SCRIPT_DIR/mpfb_packs.tsv"
if [[ "${1:-}" == --help || "${1:-}" == -h ]]; then
  echo "Usage: $0 [pack ...]"
  echo "Default packs (CC0; sizes in compressed bytes):"
  cat "$MANIFEST"
  exit 0
fi
[ -x "$BLENDER" ] || { echo "Blender not found at $BLENDER (set CHAR3D_BLENDER)" >&2; exit 1; }
declare -A sizes hashes
packs=()
while read -r pack bytes sha; do
  [[ -z "$pack" || "$pack" == \#* ]] && continue
  sizes[$pack]="$bytes"
  hashes[$pack]="$sha"
  packs+=("$pack")
done < "$MANIFEST"
if (( $# )); then packs=("$@"); fi
total=0
for pack in "${packs[@]}"; do
  [[ -n "${sizes[$pack]:-}" ]] || { echo "Unknown pack: $pack (see --help)" >&2; exit 1; }
  bytes="${sizes[$pack]}"
  if [ -f "$DL/${pack}_cc0.zip" ]; then
    echo "$pack: $bytes bytes, cached"
  else
    echo "$pack: $bytes bytes to download (~$(( (bytes + 1048575) / 1048576 )) MiB)"
    total=$((total + bytes))
  fi
done
echo "Total download: $total bytes (~$(( (total + 1048575) / 1048576 )) MiB)"
mkdir -p "$DL"
archives=()
for pack in "${packs[@]}"; do
  archive="$DL/${pack}_cc0.zip"
  if [ ! -f "$archive" ]; then
    curl -fSL -o "$archive.part" \
      "https://files.makehumancommunity.org/asset_packs/$pack/${pack}_cc0.zip"
    mv -- "$archive.part" "$archive"
  fi
  if ! echo "${hashes[$pack]}  $archive" | sha256sum -c -; then
    echo "WARNING: $pack checksum differs from the value recorded on 2026-11-16; upstream may have changed." >&2
  fi
  archives+=("$archive")
done

# Pass paths as argv, never interpolate shell paths into Python source.
(cd /tmp && "$BLENDER" -b --factory-startup --python-exit-code 1 --python-expr '
import addon_utils, os, sys, zipfile
module = "bl_ext.user_default.mpfb"
# Optional isolated destination, also useful for worktree sandbox verification.
if os.environ.get("MPFB_USER_DATA"):
    import importlib, bpy
    cls = importlib.import_module(module + "._preferences").MpfbPreferences
    if "bl_rna" not in cls.__dict__:
        bpy.utils.register_class(cls)
    addon = bpy.context.preferences.addons.get(module)
    if addon is None:
        addon = bpy.context.preferences.addons.new()
        addon.module = module
    addon.preferences.mpfb_user_data = os.path.abspath(os.environ["MPFB_USER_DATA"])
addon_utils.enable(module, default_set=True)
from bl_ext.user_default.mpfb.services import AssetService, LocationService
paths = sys.argv[sys.argv.index("--") + 1:]
root = LocationService.get_user_data()
for path in paths:
    problem = AssetService.check_asset_pack_zip(path)
    if problem:
        raise RuntimeError("ASSET PACK CHECK FAILED: " + path + ": " + str(problem))
    with zipfile.ZipFile(path) as archive:
        # Reject unsafe member paths before extracting a cached or updated pack.
        for member in archive.namelist():
            target = os.path.abspath(os.path.join(root, member))
            if os.path.commonpath((os.path.abspath(root), target)) != os.path.abspath(root):
                raise RuntimeError("Unsafe archive member: " + member)
        archive.extractall(root)
    print("MPFB_PACK_OK", os.path.basename(path))
AssetService.update_all_asset_lists()
print("MPFB_PACKS_OK", root)
' -- "${archives[@]}")
echo "Done. Restart your char3d engine to refresh MPFB asset caches."
