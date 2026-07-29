# Qortium CLI

A colorful, workflow-focused command console for Qortium Core.

Qortium CLI is being rebuilt as a daily-use tool for node operators and Qortium
users. The interface combines an old-school terminal-console style with
responsive Rich layouts and bounded
[TerminalTextEffects](https://github.com/ChrisBuilds/terminaltexteffects)
animation.

## Focus

- Node health, synchronization, settings, and minting
- Public, direct-private, and private-group chat with group workflows
- Qortal QORT, Qortium assets, and enabled external-wallet balances and backups
- QDN discovery, file downloads, APP publishing, and resource management
- Clear numbered menus organized by user intent

The home screen is the dashboard. Its workflow numbers are stable:

```text
[1] Node & Minting
[2] Chat & Groups
[3] Wallets & Payments
[4] QDN Files & Apps
[5] Identity & Names
[6] Advanced Tools
[7] Help
[8] Updates
[9] Settings
[0] Exit
```

Opening **Node & Minting** immediately shows responsive node-health and
minting-status cards. Setup, settings, and maintenance actions share one menu;
there are no extra dashboard or minting-status submenu steps.

Opening **Chat & Groups** goes straight to a responsive full-screen terminal
chat client. Direct conversations and groups stay visible beside the selected
timeline on wide terminals; narrow terminals turn the inbox into an F2
overlay. The composer remains fixed at the bottom while messages refresh in
the background.

Inside Chat, F2/F3/F4 focus groups, messages, and the composer. On a
selected message, `[1]` replies, `[2]` reacts, `[3]` edits your own message,
and `[4]` copies its text. `Ctrl+N` starts a direct chat by name or address,
`Ctrl+R` refreshes, and `Ctrl+Q` exits Chat and returns to the dashboard. The
active pane has a bright highlight and the footer changes to explain the controls
available there. A first-use guide opens automatically; press `F1`, `?`, or
enter `/help` to reopen it. Reactions open a mouse- and keyboard-friendly picker
and display as ASCII labels such as `+1`, `<3`, `XD`, and `:-)` while preserving
Qortium reaction compatibility. From the composer, `/back` also exits Chat. Public,
encrypted direct, and encrypted private-group operations are routed through
their corresponding Qortium Core APIs. The legacy non-full-screen chat remains
as a fallback for non-interactive terminals or when
`QORTIUM_CLI_CHAT_UI=legacy` is set.

Opening **Wallets & Payments** discovers the wallet networks currently enabled
by Qortium Core and immediately loads their tickers, balances, fiat values, and
24-hour price changes in one concise table. Numbered wallet rows open focused detail pages with
per-wallet transaction history, expanded inputs/outputs, address copying, and
full public wallet information. The portfolio page adds combined transaction
history, received/sent filters, persistent sorting, fiat-currency selection,
zero-balance visibility, copy-all addresses, and one-step refresh.

Qortium has no native coin: the QORT row represents Qortal and is read from a
separate Qortal node, preferring a synced local node at `127.0.0.1:12391` before
Qortal's public read nodes. QORT is intentionally excluded from the foreign-coin
fiat total. Foreign wallets use the same deterministic derivation as Qortium
Home, based on the active CLI login. QORT lookups send only the public account
address, and foreign lookups send only derived xpubs; private keys are neither
transmitted nor saved.

Foreign-coin prices use CoinGecko's public simple-price endpoint in one batched
request and are cached for ten minutes. No API key is required for normal use.
An optional CoinGecko Demo key can be supplied with
`QORTIUM_CLI_COINGECKO_API_KEY`; it is sent only to CoinGecko and is not written
to CLI settings.

## Requirements

- Python 3.10 or newer
- A running Qortium Core API, normally at `http://127.0.0.1:24891`

## Install for development

```bash
git clone https://github.com/QortiumDev/Qortium-Python-CLI.git
cd Qortium-Python-CLI
python -m pip install -e ".[dev]"
qortium-cli
```

Useful command-line options:

```bash
qortium-cli --help
qortium-cli --version
qortium-cli --no-motion
qortium-cli --self-check
```

## Responsive terminal UI

The CLI never resizes the terminal window.

- Loading operations retain the screen the user selected from and apply the
  chosen TerminalTextEffects animation directly to that screen while the next
  view is prepared. The global effect can be changed in Settings; static or
  reduced-motion fallbacks remain available for accessibility and
  non-interactive use.
- At 94 columns or wider, dashboard status cards appear side by side.
- On narrower terminals, cards stack vertically.
- Below 82 columns, menu descriptions move below their action labels.
- Non-interactive output, CI, `NO_COLOR`, and dumb terminals automatically use
  static output.

Motion can also be selected for a session:

```bash
# full, reduced, or off
QORTIUM_CLI_MOTION=reduced qortium-cli
```

The startup reveal is rendered at a fast 6× frame step. Feature-area
transitions retain their normal timing.

PowerShell:

```powershell
$env:QORTIUM_CLI_MOTION = "reduced"
qortium-cli
```

## First-run configuration

Setup asks for:

1. Qortium Core API URL
2. Request timeout
3. API key
4. QORT account key source

The account can come from a private key, seed phrase, existing Qortium Home
wallet backup, or a newly created encrypted wallet backup. API keys and account
details are stored in the platform runtime-data directory, not the installation
folder.

- Windows: `%APPDATA%\QortiumCLI`
- Linux/macOS: `~/.qortium-cli`
- Override: `QORTIUM_CLI_HOME=/custom/path`

The selected full/reduced/off motion preference and global loading-effect style
are stored in `appearance.json`. Explicit `QORTIUM_CLI_MOTION` and
`QORTIUM_CLI_LOADING_EFFECT` environment variables override the saved
preferences for that session.

Never share private keys, seed phrases, API keys, or decrypted wallet data.
On Windows, hidden credential prompts support Ctrl+V clipboard paste. API keys
are validated before storage and before use as HTTP headers so control
characters cannot produce malformed Core requests.

For a configured local endpoint, startup scans the managed Qortium Core
installation metadata and its configured `apiKeyPath`. A discovered key is
saved only after the connected Core accepts it via `/admin/apikey/test`; the
key itself is never printed.

## Architecture

See [docs/architecture.md](docs/architecture.md) for the product map, layer
boundaries, visual rules, and migration strategy.

The rebuild keeps proven transaction, chat-formatting, wallet-backup, and Core
integration code working behind the new shell. Those compatibility modules are
being split into feature-specific typed services incrementally.

## Tests

```bash
python -m unittest discover -s tests -v
python -m compileall -q qortium_cli main.py
```

The responsive menu and Textual chat tests render against wide and narrow
virtual terminals to catch clipping, focus, workflow, and resize regressions
without requiring a physical console.

## Standalone builds

Standalone binaries are built natively with PyInstaller:

```bash
python -m pip install ".[build]"
python scripts/build_binary.py
```

Output names are platform-specific:

- `qortium-cli-windows.exe`
- `qortium-cli-macos`
- `qortium-cli-linux`

GitHub Actions tests the project and builds Windows, Linux, and both Apple
Silicon and Intel macOS artifacts.
Pushing a `v*` tag publishes them together in a GitHub release only after the
test and build jobs succeed.

## Transaction helpers

The existing non-interactive helpers remain available during the rebuild:

```bash
qortium-submit-tx --help
qortium-build-tx --help
```
