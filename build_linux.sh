#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"
PYTHON_BIN="${PYTHON_BIN:-python3}"
ARCH="${RUNNER_ARCH:-$(uname -m)}"
VERSION="0.6.2"

if [[ ! -d .venv ]]; then
  "$PYTHON_BIN" -m venv .venv
fi

.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m PyInstaller --noconfirm --clean CyberdropDesk.spec

APP_DIR="dist/DropHound"
test -d "$APP_DIR"
test -f "dist/DropHoundEngine"
cp dist/DropHoundEngine "$APP_DIR/DropHoundEngine"
chmod +x "$APP_DIR/DropHound" "$APP_DIR/DropHoundEngine"
mkdir -p "$APP_DIR/licenses"
cp LICENSE "$APP_DIR/licenses/DropHound-GPL-3.0.txt"
cp licenses/THIRD-PARTY-NOTICES.txt "$APP_DIR/licenses/"
cp licenses/Cyberdrop-DL-GPL-3.0.txt "$APP_DIR/licenses/"

mkdir -p release
tar -C dist -czf "release/DropHound-${VERSION}-Linux-${ARCH}.tar.gz" DropHound

DEB_ROOT="work/deb"
rm -rf "$DEB_ROOT"
mkdir -p \
  "$DEB_ROOT/DEBIAN" \
  "$DEB_ROOT/opt/drophound" \
  "$DEB_ROOT/usr/bin" \
  "$DEB_ROOT/usr/share/applications" \
  "$DEB_ROOT/usr/share/icons/hicolor/256x256/apps"
cp -a "$APP_DIR/." "$DEB_ROOT/opt/drophound/"
ln -s /opt/drophound/DropHound "$DEB_ROOT/usr/bin/drophound"
cp assets/drophound-icon.png "$DEB_ROOT/usr/share/icons/hicolor/256x256/apps/drophound.png"
cat > "$DEB_ROOT/usr/share/applications/drophound.desktop" <<EOF
[Desktop Entry]
Name=DropHound
Comment=Bulk download manager powered by Cyberdrop-DL
Exec=/opt/drophound/DropHound
Icon=drophound
Terminal=false
Type=Application
Categories=Network;FileTransfer;
EOF
cat > "$DEB_ROOT/DEBIAN/control" <<EOF
Package: drophound
Version: ${VERSION}
Section: net
Priority: optional
Architecture: amd64
Depends: libx11-6, libxft2, libxrender1, libfontconfig1
Maintainer: DropHound Contributors
Description: Modern desktop bulk downloader powered by Cyberdrop-DL
EOF
dpkg-deb --build "$DEB_ROOT" "release/drophound_${VERSION}_amd64.deb"
