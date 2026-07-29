#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BINARY_PATH="${1:-${ROOT_DIR}/dist/qortium-cli-macos}"
OUTPUT_PATH="${2:-${ROOT_DIR}/dist/qortium-cli-macos-arm64.dmg}"
VERSION="${3:-1.0.1}"
PACKAGE_ROOT="${ROOT_DIR}/build/macos-package"
APP_PATH="${PACKAGE_ROOT}/Qortium CLI.app"
DMG_ROOT="${PACKAGE_ROOT}/dmg"
MOUNT_PATH="$(mktemp -d)"

cleanup() {
  hdiutil detach "${MOUNT_PATH}" -quiet >/dev/null 2>&1 || true
  rmdir "${MOUNT_PATH}" >/dev/null 2>&1 || true
}
trap cleanup EXIT

if [[ ! -x "${BINARY_PATH}" ]]; then
  echo "macOS executable not found or not executable: ${BINARY_PATH}" >&2
  exit 1
fi
if [[ ! "${VERSION}" =~ ^[0-9]+([.][0-9]+){1,3}$ ]]; then
  echo "Invalid bundle version: ${VERSION}" >&2
  exit 1
fi

rm -rf "${PACKAGE_ROOT}"
mkdir -p "${APP_PATH}/Contents/MacOS" "${APP_PATH}/Contents/Resources" "${DMG_ROOT}"
install -m 0755 "${ROOT_DIR}/packaging/macos/qortium-cli-launcher" \
  "${APP_PATH}/Contents/MacOS/Qortium CLI"
install -m 0755 "${BINARY_PATH}" \
  "${APP_PATH}/Contents/Resources/qortium-cli-macos"
sed "s/@VERSION@/${VERSION}/g" \
  "${ROOT_DIR}/packaging/macos/Info.plist.in" \
  > "${APP_PATH}/Contents/Info.plist"

plutil -lint "${APP_PATH}/Contents/Info.plist"
zsh -n "${APP_PATH}/Contents/MacOS/Qortium CLI"
cp -R "${APP_PATH}" "${DMG_ROOT}/"
ln -s /Applications "${DMG_ROOT}/Applications"

mkdir -p "$(dirname "${OUTPUT_PATH}")"
hdiutil create -quiet -ov -format UDZO \
  -volname "Qortium CLI" \
  -srcfolder "${DMG_ROOT}" \
  "${OUTPUT_PATH}"
hdiutil verify "${OUTPUT_PATH}"
hdiutil attach -quiet -nobrowse -readonly -mountpoint "${MOUNT_PATH}" "${OUTPUT_PATH}"
QORTIUM_CLI_MOTION=off \
  "${MOUNT_PATH}/Qortium CLI.app/Contents/Resources/qortium-cli-macos" --self-check
hdiutil detach "${MOUNT_PATH}" -quiet

echo "Built and verified ${OUTPUT_PATH}"
