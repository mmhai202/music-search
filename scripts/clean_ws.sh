#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

rm -rf \
  build_linux/build \
  build_linux/dist \
  build_windows/build \
  build_windows/dist \
  __pycache__ \
  src/__pycache__ \
  .pytest_cache \
  .mypy_cache \
  .ruff_cache \
  htmlcov \
  squashfs-root

find . \
  -path ./.git -prune -o \
  -path ./build_linux/.venv -prune -o \
  -path ./build_windows/.venv -prune -o \
  \( -name '*.pyc' -o -name '*.pyo' -o -name '*$py.class' \) \
  -type f -print0 | xargs -0 --no-run-if-empty rm -f

find . \
  -path ./.git -prune -o \
  -path ./build_linux/.venv -prune -o \
  -path ./build_windows/.venv -prune -o \
  -name '__pycache__' \
  -type d -empty -print0 | xargs -0 --no-run-if-empty rmdir

echo "Workspace cleaned."
