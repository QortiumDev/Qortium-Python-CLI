#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BINARY_PATH="${1:-${ROOT_DIR}/dist/qortium-cli-linux}"
OUTPUT_PATH="${2:-${ROOT_DIR}/dist/qortium-cli-linux-x86_64.AppImage}"
APPDIR="${ROOT_DIR}/build/appimage/QortiumCLI.AppDir"
APPIMAGETOOL="${ROOT_DIR}/build/appimage/appimagetool-x86_64.AppImage"
APPIMAGETOOL_SHA256="a6d71e2b6cd66f8e8d16c37ad164658985e0cf5fcaa950c90a482890cb9d13e0"

if [[ ! -x "${BINARY_PATH}" ]]; then
  echo "Linux executable not found or not executable: ${BINARY_PATH}" >&2
  exit 1
fi

rm -rf "${APPDIR}"
mkdir -p "${APPDIR}/usr/bin"
install -m 0755 "${BINARY_PATH}" "${APPDIR}/usr/bin/qortium-cli-linux"
install -m 0644 "${ROOT_DIR}/packaging/linux/qortium-cli.desktop" "${APPDIR}/qortium-cli.desktop"
install -m 0644 "${ROOT_DIR}/packaging/qortium-cli.svg" "${APPDIR}/qortium-cli.svg"
ln -s "usr/bin/qortium-cli-linux" "${APPDIR}/AppRun"
ln -s "qortium-cli.svg" "${APPDIR}/.DirIcon"

mkdir -p "$(dirname "${APPIMAGETOOL}")" "$(dirname "${OUTPUT_PATH}")"
curl --fail --location --silent --show-error \
  "https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage" \
  --output "${APPIMAGETOOL}"
echo "${APPIMAGETOOL_SHA256}  ${APPIMAGETOOL}" | sha256sum --check -
chmod +x "${APPIMAGETOOL}"

ARCH=x86_64 APPIMAGE_EXTRACT_AND_RUN=1 "${APPIMAGETOOL}" \
  --no-appstream "${APPDIR}" "${OUTPUT_PATH}"
chmod +x "${OUTPUT_PATH}"

APPIMAGE_EXTRACT_AND_RUN=1 QORTIUM_CLI_MOTION=off \
  "${OUTPUT_PATH}" --self-check
echo "Built and verified ${OUTPUT_PATH}"
