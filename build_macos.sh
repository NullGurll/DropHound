#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"
PYTHON_BIN="${PYTHON_BIN:-python3}"

if [[ ! -d .venv ]]; then
  "$PYTHON_BIN" -m venv .venv
fi

.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m PyInstaller --noconfirm --clean CyberdropDesk.spec

APP="dist/DropHound.app"
ENGINE="dist/DropHoundEngine"
RESOURCES="$APP/Contents/Resources"

test -d "$APP"
test -f "$ENGINE"
cp "$ENGINE" "$APP/Contents/MacOS/DropHoundEngine"
chmod +x "$APP/Contents/MacOS/DropHoundEngine"
mkdir -p "$RESOURCES/licenses"
cp LICENSE "$RESOURCES/licenses/DropHound-GPL-3.0.txt"
cp licenses/THIRD-PARTY-NOTICES.txt "$RESOURCES/licenses/"
cp licenses/Cyberdrop-DL-GPL-3.0.txt "$RESOURCES/licenses/"
xattr -cr "$APP"
codesign --force --deep --sign - "$APP"

mkdir -p release
DMG_STAGE="work/dmg"
rm -rf "$DMG_STAGE"
mkdir -p "$DMG_STAGE"
ditto "$APP" "$DMG_STAGE/DropHound.app"
ln -s /Applications "$DMG_STAGE/Applications"
hdiutil create \
  -volname "DropHound" \
  -srcfolder "$DMG_STAGE" \
  -ov \
  -format UDZO \
  "release/DropHound-0.6.0-macOS-${PACKAGE_ARCH:-$(uname -m)}.dmg"
