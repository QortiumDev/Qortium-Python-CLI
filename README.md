# Qortium CLI

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

### Startup Update Checks

On interactive startup, the CLI checks the GitHub releases page at most once per
day and lets you know when a newer release is available.

- The newest stable release is shown when it is newer than the installed CLI.
- A prerelease is shown first only when it is newer than both the installed CLI
  and the newest stable release.
- A prerelease is not offered when the newest stable release is newer.

Set `QORTIUM_CLI_NO_UPDATE_CHECK=1` before launch to skip startup update checks.

## 3) Start The App

```bash
qortium-cli
```

## 4) First-Run Setup Flow

On first launch, setup asks for:

1. Endpoint URL (default: `http://127.0.0.1:24891`)
2. Timeout seconds
3. API key
4. Wallet key: Base58 private key, seed phrase, existing wallet file, or new
   encrypted wallet file

Then it auto-fills:

- public key
- account address
- display name (primary name if available)

For an existing Qortium Home wallet file, choose `Use wallet file`, enter the JSON
backup path, then enter the wallet password. Version 2 master-seed wallets use
address `0`; version 3 private-key wallets use the stored private key directly.

To create a new account, choose `New wallet file`, enter and confirm a
wallet password, then choose where to save the JSON backup. The CLI creates an
encrypted version 2 master-seed wallet compatible with Qortium Home, uses address
`0` for CLI setup, and keeps the password out of the CLI config. Keep the wallet
file and password; the master-seed wallet can derive additional addresses later.

The endpoint URL is checked with `/admin/status` when selected. If the node is not
connected or does not return node status, setup lets you enter a different endpoint
or continue with the selected endpoint anyway.

When the selected endpoint is local, the CLI tries to detect a running
Qortium/Qortal Core process and read its `apikey.txt`. If exactly one matching
local Core API key is found, setup offers it as the default without printing the
key; press Enter at the API-key prompt to use it.

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

## 6) Reconfigure Or Run Setup

- Choose main menu option `9` to change the endpoint URL, request timeout,
  API key, or wallet key independently.
- Inside reconfigure, choose option `9` (`Run initial setup`) to run the
  initial setup flow again, then return to the main menu.
- Endpoint URL changes run the same connection check and can be retried or kept
  anyway if the node is offline.
- API key changes also look for a matching local Core `apikey.txt`; when one is
  found, press Enter to use it or type a different key.
- Changing the API key does not ask for, replace, or re-derive your private key.
- Delete the runtime settings files above to run first-time setup again.

## 7) Startup Troubleshooting

- `qortium-cli: command not found`: open a new terminal after `pipx ensurepath`, or add pipx bin dir to `PATH`.
- Cannot reach node/API: verify your node is running and listening on `127.0.0.1:24891`.
- API key prompt blocks setup: enter a valid `X-API-KEY`; if local Core detection
  finds a key, press Enter to use it. In the reconfigure menu, type `/cancel` to
  cancel a detected-key prompt without changing it.

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
- `/arbitrary/APP/{name}/{identifier}`

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

# Publish APP from a local folder or zip
qortium-build-tx app-publish \
  --name "myname" \
  --identifier "default" \
  --path "/path/to/my-app-or-zip"
```

Optional behavior:

```bash
# Build unsigned only
qortium-build-tx --build-only --out-unsigned unsigned.txt \
  name-register --name "myname"

# Build + sign only (skip broadcast)
qortium-build-tx --skip-process --out-signed signed.txt \
  group-join --group-id 694

# Disable automatic nonce/PoW retry
qortium-build-tx --no-auto-nonce group-join --group-id 694

# Build an APP publish without signing or broadcasting
qortium-build-tx --build-only --out-unsigned unsigned.txt \
  app-publish --name "myname" --path "/path/to/my-app"
```

Notes:

- `fee` defaults to `0` (`--fee` can override).
- The command auto-fetches `timestamp` and `reference` unless overridden.
- Accepting a pending group invite uses the same `group-join` transaction for the invited group ID.
- APP publishing accepts a folder or `.zip`. The app root must contain `index.html`.
- A zip can contain `index.html` directly or inside one top-level folder.
- Path-based publishing requires the CLI and node to run on the same machine, or to share
  the same filesystem path.
- If your chain/node enforces non-zero fees for specific tx types, pass `--fee`.
- If processing fails with `INSUFFICIENT_FEE`, nonce/PoW, or some mempow-related `invalid signature` responses, the tool can auto-compute mempow/nonce via known `*/compute` endpoints (unless `--no-auto-nonce` is used).
- If processing fails with `INSUFFICIENT_FEE`, the tool auto-fetches `/transactions/fee`, rebuilds, and retries once.

## 10) Interactive Menus

The main menu is organized as:

1. `Node`
2. `Chat`
3. `Groups`
4. `Register Name`
5. `Wallet`
6. `QDN Resources`
8. `Help/Info`
9. `Reconfigure endpoint/config`

`Register Name` checks the configured wallet for existing registered names first.
If none are found, it opens the normal registration prompt. If names already
exist, it lists them and lets you choose `Update name` or `New name`; choose `0`
to go back. At the register-name prompt, press Enter without typing a name to
cancel.

The Groups menu contains:

- `Join group (/groups/join)`
- `Create group (/groups/create)`
- `View / accept invites sent to this account`
- `Review join requests for groups you manage`

These are separate workflows:

- Incoming invites load from `/groups/invites/{address}` and are accepted by submitting
  `/groups/join`.
- Pending join requests load from `/groups/joinrequests/admin/{address}`. Older nodes fall
  back to checking managed groups through `/groups/member/{address}`,
  `/groups/members/{groupid}`, and `/groups/joinrequests/{groupid}`.
- Approving a join request submits `/groups/invite`. When the request is still pending,
  Core immediately adds the applicant as a member and removes the request.

The menu flow builds, signs, and processes the transaction using your configured wallet values.
If processing fails with `INSUFFICIENT_FEE`, nonce/PoW, or some mempow-related `invalid signature` responses, it auto-computes mempow/nonce and retries once when the node supports a compute endpoint.
If processing fails with `INSUFFICIENT_FEE`, it auto-fetches `/transactions/fee`, rebuilds, and retries once.

## 11) Wallet Menu

Inside `qortium-cli`, the Wallet tool is available from the main menu:

- `Check QORT balance`
- `Check all asset balances`
- `Send QORT payment`
- `Send asset transfer`
- `Save Qortium Home private-key wallet backup`

`Save Qortium Home private-key wallet backup` writes Qortium Home's version-3 wallet
format. It encrypts the configured 32-byte QORT private key and verifies that the key
derives the configured address.

The default filename follows Qortium Home's convention:

```text
<wallet-name>_<address>.json
```

Private-key wallets contain one QORT address. Unlike version-2 master-seed wallets created
by Qortium Home, they cannot derive additional addresses.

The backup password is required for restoration and is not stored by the CLI.

## 12) QDN APP Publishing And Resource Deletion

Choose `6) QDN Resources` from the main menu.

- `Publish APP` builds, signs, and submits an `ARBITRARY APP` transaction.
  - The registered name must be owned by the configured wallet.
  - Input can be a local folder or `.zip`.
  - `index.html` must be at the app root.
  - Metadata limits are 80 UTF-8 bytes for title, 240 UTF-8 bytes for description,
    and up to 5 tags of 20 characters each.
  - The Core APP service limit is 50 MiB.
- `Look up and delete a QDN resource` searches either:
  - resources published under names owned by the configured wallet, then continues
    directly to on-chain deletion
  - resources hosted by the configured node, then continues directly to local deletion
- Results display the exact `service / name / identifier` tuple, including `default`
  when the resource has no named identifier.
- Both deletion workflows can search and select a result or accept the tuple manually.
- `Delete resource on-chain` calls Qortium's QDN deletion transaction builder:
  - default identifier: `POST /arbitrary/resource/{service}/{name}/delete`
  - named identifier: `POST /arbitrary/resource/{service}/{name}/{identifier}/delete`
- `Delete local cached/hosted copy` calls:
  - `DELETE /arbitrary/resource/{service}/{name}/{identifier}`

On-chain deletion requires the configured wallet to own the registered name. It publishes an
`ARBITRARY DELETE` transaction, after which the resource can be published again later. Local
deletion affects only the current node and does not alter the on-chain resource.

## 13) Tests

```bash
python -m unittest discover -s tests -v
```
