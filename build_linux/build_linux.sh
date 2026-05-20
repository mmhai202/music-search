#!/usr/bin/env bash
set -euo pipefail

BUILD_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$BUILD_ROOT/.." && pwd)"
cd "$PROJECT_ROOT"

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

"$BUILD_ROOT/.venv/bin/python" -m PyInstaller "$BUILD_ROOT/music-search-linux.spec" \
  --clean \
  --workpath "$BUILD_ROOT/build" \
  --distpath "$BUILD_ROOT/dist"

echo
echo "Build xong: build_linux/dist/MusicSearch"
echo "Artifact: build_linux/dist/MusicSearch"
