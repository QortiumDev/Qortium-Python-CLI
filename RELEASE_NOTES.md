# Qortium CLI 1.0.1

The workflow-focused Qortium command-line client, now distributed in native
single-download formats for each supported platform.

## Highlights

- Responsive workflow dashboard for node status, minting, chat, wallets, QDN, identity, and advanced tools.
- Full-screen terminal chat with public groups, encrypted direct messages, encrypted private groups, replies, edits, and a deliberate reaction picker.
- Terminal-friendly reaction labels such as `+1`, `<3`, `XD`, and `:-)` while preserving Qortium-compatible Unicode reaction payloads.
- Combined QORT and external-wallet portfolio with balances, fiat prices, public wallet information, and transaction history.
- QDN file exploring, downloading, APP publishing, ownership checks, and local or on-chain deletion workflows.
- Guided transaction builder aligned with current Qortium Core endpoints.
- Local Qortium Core detection, verified API-key synchronization, encrypted Qortium Home wallet import/export, and safer secret entry.
- Configurable motion effects, faster startup reveal, responsive narrow-terminal layouts, and non-interactive fallbacks.

## Downloads

- Windows x86-64: `qortium-cli-windows-x86_64.exe`
- Linux x86-64: `qortium-cli-linux-x86_64.AppImage`
- macOS Apple Silicon: `qortium-cli-macos-arm64.dmg`

Every platform executable is built natively and must pass `--self-check` before
the release is published. The AppImage is executed directly, and the DMG is
verified, mounted, and tested from inside the mounted app bundle. Verify
downloads with `SHA256SUMS.txt`.

The macOS app is not yet Developer ID signed or notarized and may require
approval in macOS Privacy & Security settings. Linux users should run
`chmod +x qortium-cli-linux-x86_64.AppImage` once after downloading.
