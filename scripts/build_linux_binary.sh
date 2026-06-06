#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ "${INSTALL_DEPS:-0}" == "1" ]]; then
  python3 -m pip install --upgrade pip
  python3 -m pip install ".[build]"
fi

command -v pyinstaller >/dev/null 2>&1 || {
  echo "pyinstaller is not installed."
  echo "Install once with: python3 -m pip install '.[build]'"
  exit 1
}

pyinstaller \
  --noconfirm \
  --clean \
  --onefile \
  --name qortium-cli \
  main.py

echo
echo "Build complete:"
echo "  $ROOT_DIR/dist/qortium-cli"
