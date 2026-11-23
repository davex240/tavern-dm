#!/usr/bin/env bash
# Builds Tavern_DM-x86_64.AppImage from tavern_dm.py + web/ + icon.png
# Needs: python3, pip. Downloads pyinstaller/PyQt6/qrcode into a venv and appimagetool.
set -euo pipefail
cd "$(dirname "$0")"
ROOT=$PWD
BUILD=$ROOT/build

python3 -m venv "$BUILD/venv"
"$BUILD/venv/bin/pip" install -q --upgrade pip
"$BUILD/venv/bin/pip" install -q pyinstaller PyQt6 qrcode
PY="$BUILD/venv/bin/python"

[ -f icon.png ] || "$PY" make_icon.py

"$PY" -m PyInstaller --noconfirm --clean --windowed --name tavern-dm \
  --distpath "$BUILD/dist" --workpath "$BUILD/work" --specpath "$BUILD" \
  --add-data "$ROOT/web:web" --add-data "$ROOT/icon.png:." \
  --hidden-import qrcode --collect-submodules qrcode \
  --exclude-module tkinter \
  --exclude-module PyQt6.QtQml --exclude-module PyQt6.QtQuick --exclude-module PyQt6.QtPdf \
  --exclude-module PyQt6.QtMultimedia --exclude-module PyQt6.QtBluetooth --exclude-module PyQt6.QtSql \
  tavern_dm.py

APPDIR=$BUILD/AppDir
rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/lib"
cp -a "$BUILD/dist/tavern-dm" "$APPDIR/usr/lib/tavern-dm"
cp icon.png "$APPDIR/tavern-dm.png"
cp icon.png "$APPDIR/.DirIcon"
cat > "$APPDIR/tavern-dm.desktop" <<'EOF'
[Desktop Entry]
Type=Application
Name=Tavern DM
Comment=AI dungeon master and story roleplay for LM Studio
Exec=tavern-dm
Icon=tavern-dm
Terminal=false
Categories=Game;RolePlaying;
StartupWMClass=tavern-dm
EOF
cat > "$APPDIR/AppRun" <<'EOF'
#!/bin/sh
HERE="$(dirname "$(readlink -f "$0")")"
exec "$HERE/usr/lib/tavern-dm/tavern-dm" "$@"
EOF
chmod +x "$APPDIR/AppRun"

TOOL=$BUILD/appimagetool-x86_64.AppImage
[ -f "$TOOL" ] || curl -sSL -o "$TOOL" https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage
chmod +x "$TOOL"
ARCH=x86_64 APPIMAGE_EXTRACT_AND_RUN=1 "$TOOL" --no-appstream "$APPDIR" "$ROOT/Tavern_DM-x86_64.AppImage"
echo "Built: $ROOT/Tavern_DM-x86_64.AppImage"
