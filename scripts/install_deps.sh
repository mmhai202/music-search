#!/usr/bin/env bash
set -euo pipefail

VIBRA_REPO="https://github.com/BayernMuller/vibra.git"
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
      ffmpeg jq pulseaudio-utils git cmake g++ make \
      libcurl4-openssl-dev libfftw3-dev
  elif command -v dnf >/dev/null 2>&1; then
    run_as_root dnf install -y \
      ffmpeg jq pulseaudio-utils git cmake gcc-c++ make \
      libcurl-devel fftw-devel
  elif command -v pacman >/dev/null 2>&1; then
    run_as_root pacman -Sy --needed --noconfirm \
      ffmpeg jq libpulse git cmake base-devel curl fftw
  else
    echo "Chua ho tro package manager nay. Bao toi de them tiep."
    exit 1
  fi
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
install_vibra

echo "Xong. Thu lai: bash vibra_overlay.sh va bash vibra_to_box.sh"
