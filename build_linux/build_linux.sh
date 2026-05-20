#!/usr/bin/env bash
set -euo pipefail

BUILD_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$BUILD_ROOT/.." && pwd)"
cd "$PROJECT_ROOT"

VERSION="$(tr -d '[:space:]' < "$BUILD_ROOT/VERSION")"
ARCH="$(uname -m)"
INTERNAL_BINARY="MusicSearch"
APPIMAGE_NAME="MusicSearch-${VERSION}-${ARCH}.AppImage"
APP_ID="music-search"
APP_NAME="Music Search"
PACKAGE_NAME="music-search"
PYINSTALLER_DIST="$BUILD_ROOT/build/pyinstaller-dist"
APPDIR="$BUILD_ROOT/build/$APP_ID.AppDir"
APPIMAGE_TOOL="${APPIMAGE_TOOL:-appimagetool}"

if ! command -v "$APPIMAGE_TOOL" >/dev/null 2>&1 && [ -x "$HOME/bin/appimagetool" ]; then
  APPIMAGE_TOOL="$HOME/bin/appimagetool"
fi

if [ "${1:-}" = "--clean" ]; then
  rm -rf "$BUILD_ROOT/build" "$BUILD_ROOT/dist"
fi

if [ ! -d "$BUILD_ROOT/.venv" ]; then
  python3 -m venv "$BUILD_ROOT/.venv"
fi

"$BUILD_ROOT/.venv/bin/python" -m pip install --upgrade pip
"$BUILD_ROOT/.venv/bin/python" -m pip install -r "$BUILD_ROOT/requirements-dev.txt"

for binary in ffmpeg vibra pactl; do
  if ! command -v "$binary" >/dev/null 2>&1 && [ ! -x "bin/$binary" ]; then
    echo "Missing $binary. Install it once on this build machine or put it at bin/$binary." >&2
    exit 1
  fi
done

export MUSIC_SEARCH_ARTIFACT_NAME="$INTERNAL_BINARY"
"$BUILD_ROOT/.venv/bin/python" -m PyInstaller "$BUILD_ROOT/music-search-linux.spec" \
  --clean \
  --workpath "$BUILD_ROOT/build" \
  --distpath "$PYINSTALLER_DIST"

mkdir -p "$APPDIR/usr/bin"
mkdir -p "$APPDIR/usr/share/applications"
mkdir -p "$APPDIR/usr/share/icons/hicolor/scalable/apps"
mkdir -p "$BUILD_ROOT/dist"

install -m 0755 "$PYINSTALLER_DIST/$INTERNAL_BINARY" "$APPDIR/usr/bin/$INTERNAL_BINARY"
install -m 0644 "$BUILD_ROOT/resources/$APP_ID.svg" "$APPDIR/$APP_ID.svg"
install -m 0644 "$BUILD_ROOT/resources/$APP_ID.svg" "$APPDIR/usr/share/icons/hicolor/scalable/apps/$APP_ID.svg"

cat > "$APPDIR/AppRun" <<EOF
#!/usr/bin/env bash
HERE="\$(dirname "\$(readlink -f "\$0")")"
exec "\$HERE/usr/bin/$INTERNAL_BINARY" "\$@"
EOF
chmod +x "$APPDIR/AppRun"

cat > "$APPDIR/$APP_ID.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=$APP_NAME
Comment=Identify songs from system audio or uploaded audio files
Exec=$INTERNAL_BINARY
Icon=$APP_ID
Categories=AudioVideo;Audio;
Terminal=false
StartupNotify=true
X-PackageName=$PACKAGE_NAME
X-AppVersion=$VERSION
EOF
install -m 0644 "$APPDIR/$APP_ID.desktop" "$APPDIR/usr/share/applications/$APP_ID.desktop"

cat > "$APPDIR/$APP_ID.release.json" <<EOF
{
  "name": "$APP_NAME",
  "package": "$PACKAGE_NAME",
  "version": "$VERSION",
  "architecture": "$ARCH",
  "artifact": "$APPIMAGE_NAME",
  "desktop_entry": "$APP_ID.desktop",
  "icon": "$APP_ID.svg"
}
EOF

if ! command -v "$APPIMAGE_TOOL" >/dev/null 2>&1; then
  echo "Missing appimagetool. Install appimagetool or set APPIMAGE_TOOL=/path/to/appimagetool." >&2
  echo "Prepared AppDir: build_linux/build/$APP_ID.AppDir" >&2
  exit 1
fi

APPIMAGE_EXTRACT_AND_RUN=1 "$APPIMAGE_TOOL" "$APPDIR" "$BUILD_ROOT/dist/$APPIMAGE_NAME"
chmod +x "$BUILD_ROOT/dist/$APPIMAGE_NAME"

echo
echo "Build xong: build_linux/dist/$APPIMAGE_NAME"
