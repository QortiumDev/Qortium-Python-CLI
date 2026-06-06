# Qortium CLI 0.2.0

## 1) Prerequisites

- Python 3.10+ installed
- A running Qortium/Qortal node API (default expected endpoint: `http://127.0.0.1:24891`)

## 2) Install

### Linux/macOS

```bash
python3 -m pip install --user pipx
python3 -m pipx ensurepath
pipx install "git+https://github.com/QortiumDev/Qortium-Python-CLI.git"
```

### Windows

```powershell
py -m pip install --user pipx
py -m pipx ensurepath
pipx install "git+https://github.com/QortiumDev/Qortium-Python-CLI.git"
```

### Update An Existing Install

```bash
pipx upgrade qortium-cli
```

## 3) Start The App

```bash
qortium-cli
```

## 4) First-Run Setup Flow

On first launch, setup asks for:

1. Endpoint URL (default: `http://127.0.0.1:24891`)
2. Timeout seconds
3. API key
4. Key mode: private key
5. Key mode: seed phrase (the app derives the private key)

Then it auto-fills:

- public key
- account address
- display name (primary name if available)

## 5) Runtime Settings Files

The app writes runtime settings here:

- Linux/macOS: `~/.qortium-cli`
- Windows: `%APPDATA%\QortiumCLI`

Files created:

- `endpoint.py`
- `config.py`
- `chat_settings.json`

Optional custom location:

- set `QORTIUM_CLI_HOME=/path/to/folder` before launch

## 6) Reconfigure Or Reset

- In the app, choose menu option `9` to re-run setup.
- Or delete the runtime settings files above and launch again.

## 7) Startup Troubleshooting

- `qortium-cli: command not found`: open a new terminal after `pipx ensurepath`, or add pipx bin dir to `PATH`.
- Cannot reach node/API: verify your node is running and listening on `127.0.0.1:24891`.
- API key prompt blocks setup: enter a valid `X-API-KEY` (or press Enter to keep current during reconfigure).

## 8) Sign And Submit Raw Transactions

Use this helper to load transaction bytes (or JSON containing `transactionBytes`), sign, and submit:

```bash
qortium-submit-tx --tx-file unsigned_tx.txt
```

Common usage:

```bash
# Load JSON that contains transactionBytes
qortium-submit-tx --tx-file unsigned_tx.json

# Pipe input via stdin
cat unsigned_tx.txt | qortium-submit-tx

# Sign only (do not broadcast)
qortium-submit-tx --tx-file unsigned_tx.txt --skip-process --out-signed signed_tx.txt

# Submit already signed bytes
qortium-submit-tx --tx-file signed_tx.txt --signed

# Disable automatic nonce/PoW retry
qortium-submit-tx --tx-file unsigned_tx.txt --no-auto-nonce
```

Notes:

- This command does not calculate transaction fees. It signs and submits exactly what you provide.
- If processing fails with `INSUFFICIENT_FEE`, nonce/PoW, or some mempow-related `invalid signature` responses, it can retry using known mempow/nonce compute endpoints (unless `--no-auto-nonce` is used).

## 9) Build + Sign + Submit Common Transactions

Use this helper for direct endpoint flows:

- `/groups/join`
- `/groups/create`
- `/names/register`

Basic examples:

```bash
# JOIN_GROUP
qortium-build-tx group-join --group-id 694

# CREATE_GROUP
qortium-build-tx group-create \
  --group-name "MY-GROUP" \
  --description "My Qortium group" \
  --approval-threshold NONE

# REGISTER_NAME
qortium-build-tx name-register --name "myname" --data "{}"
```

Optional behavior:

```bash
# Build unsigned only
qortium-build-tx name-register --name "myname" --build-only --out-unsigned unsigned.txt

# Build + sign only (skip broadcast)
qortium-build-tx group-join --group-id 694 --skip-process --out-signed signed.txt

# Disable automatic nonce/PoW retry
qortium-build-tx group-join --group-id 694 --no-auto-nonce
```

Notes:

- `fee` defaults to `0` (`--fee` can override).
- The command auto-fetches `timestamp` and `reference` unless overridden.
- If your chain/node enforces non-zero fees for specific tx types, pass `--fee`.
- If processing fails with `INSUFFICIENT_FEE`, nonce/PoW, or some mempow-related `invalid signature` responses, the tool can auto-compute mempow/nonce via known `*/compute` endpoints (unless `--no-auto-nonce` is used).
- If processing fails with `INSUFFICIENT_FEE`, the tool auto-fetches `/transactions/fee`, rebuilds, and retries once.

## 10) Interactive Transactions Menu

Inside `qortium-cli`, use:

1. `3) Transactions`
2. Choose:
   - `Join group (/groups/join)`
   - `Create group (/groups/create)`
   - `Register name (/names/register)`

The menu flow builds, signs, and processes the transaction using your configured wallet values.
If processing fails with `INSUFFICIENT_FEE`, nonce/PoW, or some mempow-related `invalid signature` responses, it auto-computes mempow/nonce and retries once when the node supports a compute endpoint.
If processing fails with `INSUFFICIENT_FEE`, it auto-fetches `/transactions/fee`, rebuilds, and retries once.

## 11) Wallet Menu

Inside `qortium-cli`, the Wallet tool is available from the main menu:

- `Check QORT balance`
- `Check all asset balances`
- `Send QORT payment`
- `Send asset transfer`
