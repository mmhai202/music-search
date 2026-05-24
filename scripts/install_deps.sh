#!/usr/bin/env bash
set -euo pipefail

VIBRA_REPO="${VIBRA_REPO:-https://github.com/BayernMuller/vibra.git}"
VIBRA_REF="${VIBRA_REF:-5ff95ed1654894631517de1acb5c765bb4fb6c83}"
APPIMAGETOOL_VERSION="${APPIMAGETOOL_VERSION:-1.9.1}"
APPIMAGETOOL_BASE_URL="${APPIMAGETOOL_BASE_URL:-https://github.com/AppImage/appimagetool/releases/download/$APPIMAGETOOL_VERSION}"
APPIMAGETOOL_SHA256_X86_64="${APPIMAGETOOL_SHA256_X86_64:-ed4ce84f0d9caff66f50bcca6ff6f35aae54ce8135408b3fa33abfc3cb384eb0}"
APPIMAGETOOL_SHA256_AARCH64="${APPIMAGETOOL_SHA256_AARCH64:-f0837e7448a0c1e4e650a93bb3e85802546e60654ef287576f46c71c126a9158}"
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
      ffmpeg jq pulseaudio-utils git cmake g++ make wget python3-venv \
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

  local arch checksum target url
  case "$(uname -m)" in
    x86_64)
      arch="x86_64"
      checksum="$APPIMAGETOOL_SHA256_X86_64"
      ;;
    aarch64 | arm64)
      arch="aarch64"
      checksum="$APPIMAGETOOL_SHA256_AARCH64"
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
  echo "$checksum  $target" | sha256sum -c -
  chmod +x "$target"
  echo "appimagetool da cai: $target"
}

install_vibra() {
  if command -v vibra >/dev/null 2>&1; then
    echo "vibra da co: $(command -v vibra)"
    return
  fi

  rm -rf "$BUILD_DIR"
  git clone "$VIBRA_REPO" "$BUILD_DIR"
  git -C "$BUILD_DIR" checkout --detach "$VIBRA_REF"
  cmake -S "$BUILD_DIR" -B "$BUILD_DIR/build" -DCMAKE_BUILD_TYPE=Release
  cmake --build "$BUILD_DIR/build" --parallel
  run_as_root cmake --install "$BUILD_DIR/build"
}

install_main_deps
install_appimagetool
install_vibra

echo "Xong. Co the build AppImage bang: bash build_linux/build_linux.sh --clean"
