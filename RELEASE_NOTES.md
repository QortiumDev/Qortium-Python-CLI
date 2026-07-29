# Qortium CLI 1.0.0

The first production release of the workflow-focused Qortium command-line client.

## Highlights

- Responsive workflow dashboard for node status, minting, chat, wallets, QDN, identity, and advanced tools.
- Full-screen terminal chat with public groups, encrypted direct messages, encrypted private groups, replies, edits, and a deliberate reaction picker.
- Terminal-friendly reaction labels such as `+1`, `<3`, `XD`, and `:-)` while preserving Qortium-compatible Unicode reaction payloads.
- Combined QORT and external-wallet portfolio with balances, fiat prices, public wallet information, and transaction history.
- QDN browsing, downloading, APP publishing, ownership checks, and local or on-chain deletion workflows.
- Guided transaction builder aligned with current Qortium Core endpoints.
- Local Qortium Core detection, verified API-key synchronization, encrypted Qortium Home wallet import/export, and safer secret entry.
- Configurable motion effects, faster startup reveal, responsive narrow-terminal layouts, and non-interactive fallbacks.

## Downloads

- Windows x86-64: `qortium-cli-windows-x86_64.zip`
- Linux x86-64: `qortium-cli-linux-x86_64.tar.gz`
- macOS Apple Silicon: `qortium-cli-macos-arm64.tar.gz`
- macOS Intel: `qortium-cli-macos-x86_64.tar.gz`

Every platform executable is built natively and must pass `--self-check` before the release is published. Verify downloads with `SHA256SUMS.txt`.

Unsigned macOS builds may require approval in macOS Privacy & Security settings. Linux and macOS users can run the extracted executable directly; if an archive tool does not preserve its mode, run `chmod +x qortium-cli-*`.
