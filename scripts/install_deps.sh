#!/usr/bin/env bash
set -euo pipefail

VIBRA_REPO="https://github.com/BayernMuller/vibra.git"
APPIMAGETOOL_BASE_URL="https://github.com/AppImage/AppImageKit/releases/download/continuous"
BUILD_DIR="/tmp/vibra-build"

run_as_root() {
  if [ "$(id -u)" -eq 0 ]; then
    "$@"
  else
    sudo "$@"
  fi
}

install_main_deps() {
  if command -v apt-get >/dev/null 2>&1; then
    run_as_root apt-get update
    run_as_root apt-get install -y \
      ffmpeg jq pulseaudio-utils git cmake g++ make wget \
      libcurl4-openssl-dev libfftw3-dev
  elif command -v dnf >/dev/null 2>&1; then
    run_as_root dnf install -y \
      ffmpeg jq pulseaudio-utils git cmake gcc-c++ make wget \
      libcurl-devel fftw-devel
  elif command -v pacman >/dev/null 2>&1; then
    run_as_root pacman -Sy --needed --noconfirm \
      ffmpeg jq libpulse git cmake base-devel wget curl fftw
  else
    echo "Chua ho tro package manager nay. Bao toi de them tiep."
    exit 1
  fi
}

install_appimagetool() {
  if command -v appimagetool >/dev/null 2>&1; then
    echo "appimagetool da co: $(command -v appimagetool)"
    return
  fi

  local arch target url
  case "$(uname -m)" in
    x86_64)
      arch="x86_64"
      ;;
    aarch64 | arm64)
      arch="aarch64"
      ;;
    *)
      echo "Chua ho tro appimagetool cho kien truc: $(uname -m)" >&2
      exit 1
      ;;
  esac

  mkdir -p "$HOME/bin"
  target="$HOME/bin/appimagetool"
  url="$APPIMAGETOOL_BASE_URL/appimagetool-${arch}.AppImage"

  wget -O "$target" "$url"
  chmod +x "$target"
  echo "appimagetool da cai: $target"
}

install_vibra() {
  if command -v vibra >/dev/null 2>&1; then
    echo "vibra da co: $(command -v vibra)"
    return
  fi

  rm -rf "$BUILD_DIR"
  git clone --depth 1 "$VIBRA_REPO" "$BUILD_DIR"
  cmake -S "$BUILD_DIR" -B "$BUILD_DIR/build" -DCMAKE_BUILD_TYPE=Release
  cmake --build "$BUILD_DIR/build" --parallel
  run_as_root cmake --install "$BUILD_DIR/build"
}

install_main_deps
install_appimagetool
install_vibra

echo "Xong. Co the build AppImage bang: bash build_linux/build_linux.sh --clean"
