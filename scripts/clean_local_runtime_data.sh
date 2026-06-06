#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

rm -f endpoint.py config.py chat_settings.json
rm -rf .qortium-cli-data dist/.qortium-cli-data

echo "Removed local runtime files:"
echo "  endpoint.py"
echo "  config.py"
echo "  chat_settings.json"
echo "  .qortium-cli-data/"
echo "  dist/.qortium-cli-data/"
