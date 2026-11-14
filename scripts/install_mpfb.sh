#!/usr/bin/env bash
# Install MPFB (MakeHuman for Blender) + the CC0 MakeHuman system assets and face packs into char3d's
# Blender, in portable mode (nothing is written to ~/.config/blender).
#
#   scripts/install_mpfb.sh
#
# Reuse already-downloaded files with MPFB_ADDON_ZIP=/path MPFB_ASSETS_ZIP=/path.
set -euo pipefail

BLENDER="${CHAR3D_BLENDER:-$HOME/.local/opt/blender/blender}"
BLENDER_DIR="$(dirname "$(readlink -f "$BLENDER")")"
DL="${MPFB_DOWNLOAD_DIR:-$HOME/.local/opt/dl/mpfb}"

ADDON_URL="https://extensions.blender.org/download/sha256:c075b3e9b94b8e5556a5f03f4653602d02ea306de08126e8f55ed6dee28a2dad/add-on-mpfb-v2.0.18.zip"
ADDON_SHA256="c075b3e9b94b8e5556a5f03f4653602d02ea306de08126e8f55ed6dee28a2dad"
ASSETS_URL="https://files.makehumancommunity.org/asset_packs/makehuman_system_assets/makehuman_system_assets_cc0.zip"
ASSETS_SHA256="b542127a8e25547c7c29c19f2d1d2adb9a664c80396ecd694095dbc8028a0107"  # observed 2026-11-14

[ -x "$BLENDER" ] || { echo "Blender not found at $BLENDER (set CHAR3D_BLENDER)"; exit 1; }
mkdir -p "$DL" "$BLENDER_DIR/portable"

ADDON_ZIP="${MPFB_ADDON_ZIP:-$DL/add-on-mpfb-v2.0.18.zip}"
ASSETS_ZIP="${MPFB_ASSETS_ZIP:-$DL/makehuman_system_assets_cc0.zip}"
[ -f "$ADDON_ZIP" ] || { echo "Downloading MPFB add-on (46 MB)..."; curl -fSL -o "$ADDON_ZIP" "$ADDON_URL"; }
[ -f "$ASSETS_ZIP" ] || { echo "Downloading MakeHuman system assets (281 MB)..."; curl -fSL -o "$ASSETS_ZIP" "$ASSETS_URL"; }

echo "$ADDON_SHA256  $ADDON_ZIP" | sha256sum -c -
if ! echo "$ASSETS_SHA256  $ASSETS_ZIP" | sha256sum -c - ; then
  echo "WARNING: asset pack checksum differs from the one recorded on 2026-11-14 (it may have been updated upstream)."
fi

echo "Installing MPFB extension into $BLENDER_DIR/portable ..."
(cd /tmp && "$BLENDER" -b --factory-startup --command extension install-file -r user_default -e "$ADDON_ZIP" >/dev/null)

echo "Extracting asset pack ..."
(cd /tmp && "$BLENDER" -b --factory-startup --python-expr "
import addon_utils, zipfile, sys
addon_utils.enable('bl_ext.user_default.mpfb', default_set=True)
from bl_ext.user_default.mpfb.services import LocationService, AssetService
problem = AssetService.check_asset_pack_zip(r'$ASSETS_ZIP')
if problem:
    print('ASSET PACK CHECK FAILED:', problem); sys.exit(1)
with zipfile.ZipFile(r'$ASSETS_ZIP') as z:
    z.extractall(LocationService.get_user_data())
AssetService.update_all_asset_lists()
print('MPFB_ASSETS_OK', LocationService.get_user_data())
" 2>&1 | grep -E "MPFB_ASSETS_OK|FAILED|Error")
echo "Installing face packs (ARKit face units + visemes, CC0, <0.5 MB) ..."
for pack in faceunits01 visemes01; do
  zip="$DL/$pack.zip"
  [ -f "$zip" ] || curl -fSL -o "$zip" "https://files.makehumancommunity.org/functional/$pack.zip"
done
echo "d113107bd7eb59f3af4df6fc0ec29bfcc593f496d0b336aec14f086a80ce7146  $DL/faceunits01.zip" | sha256sum -c - || echo "WARNING: faceunits01 checksum differs from 2026-11-14"
echo "f61f4f36bb4fe43486efa2a644eea9d6760e510bde10eecc97a4ddf28424e4d3  $DL/visemes01.zip" | sha256sum -c - || echo "WARNING: visemes01 checksum differs from 2026-11-14"
(cd /tmp && "$BLENDER" -b --factory-startup --python-expr "
import addon_utils, zipfile, sys
addon_utils.enable('bl_ext.user_default.mpfb', default_set=True)
from bl_ext.user_default.mpfb.services import LocationService, AssetService
for p in ('faceunits01', 'visemes01'):
    zp = r'$DL/' + p + '.zip'
    problem = AssetService.check_asset_pack_zip(zp)
    if problem:
        print('PACK CHECK FAILED', p, problem); sys.exit(1)
    with zipfile.ZipFile(zp) as z:
        z.extractall(LocationService.get_user_data())
AssetService.update_all_asset_lists()
print('MPFB_FACE_OK')
" 2>&1 | grep -E "MPFB_FACE_OK|FAILED|Error")
echo "Done. Restart the char3d MCP server (or call engine_shutdown) to pick it up."
