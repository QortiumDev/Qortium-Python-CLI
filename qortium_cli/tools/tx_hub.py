"""Universal TX Hub — build, sign, and broadcast any transaction type."""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, List

from qortium_cli.models import AppContext
from qortium_cli.ui import (
    ok,
    pause,
    print_banner,
    prompt_decimal,
    prompt_int,
    prompt_str,
    prompt_yes_no,
    read_menu_choice,
    warn,
)
from qortium_cli.ui.banner import tool_header
from qortium_cli.ui.theme import console
from qortium_cli.ui.widgets import (
    TxPipeline,
    error_panel,
    json_panel,
    ok_panel,
    spinner,
    warn_panel,
)
from qortium_cli.utils import d8, pretty_exception
from qortium_cli.validators import is_placeholder, looks_like_qortal_address

# ---------------------------------------------------------------------------
# Transaction catalog
# ---------------------------------------------------------------------------

TX_CATALOG: List[Dict[str, Any]] = [
    # Groups
    {
        "key": "G1",
        "label": "JOIN_GROUP",
        "category": "Groups",
        "path": "/groups/join",
        "needs_pow": True,
        "fields": [
            {"name": "joinerPublicKey", "label": "Joiner Public Key", "auto": "pubkey"},
            {"name": "groupId", "label": "Group ID", "type": "int", "min": 1},
        ],
    },
    {
        "key": "G2",
        "label": "LEAVE_GROUP",
        "category": "Groups",
        "path": "/groups/leave",
        "needs_pow": True,
        "fields": [
            {"name": "leaverPublicKey", "label": "Leaver Public Key", "auto": "pubkey"},
            {"name": "groupId", "label": "Group ID", "type": "int", "min": 1},
        ],
    },
    {
        "key": "G3",
        "label": "GROUP_INVITE",
        "category": "Groups",
        "path": "/groups/invite",
        "needs_pow": True,
        "fields": [
            {"name": "adminPublicKey", "label": "Admin Public Key", "auto": "pubkey"},
            {"name": "groupId", "label": "Group ID", "type": "int", "min": 1},
            {"name": "invitee", "label": "Invitee Address", "type": "address"},
            {"name": "timeToLive", "label": "Time to Live (0=never)", "type": "int", "default": 0, "min": 0},
        ],
    },
    {
        "key": "G4",
        "label": "CREATE_GROUP",
        "category": "Groups",
        "path": "/groups/create",
        "needs_pow": True,
        "fields": [
            {"name": "creatorPublicKey", "label": "Creator Public Key", "auto": "pubkey"},
            {"name": "groupName", "label": "Group Name"},
            {"name": "description", "label": "Description"},
            {"name": "isOpen", "label": "Open Group?", "type": "bool", "default": True},
            {"name": "approvalThreshold", "label": "Approval Threshold (NONE/ONE/PCT20/...)", "default": "NONE"},
            {"name": "minimumBlockDelay", "label": "Min Block Delay", "type": "int", "default": 0, "min": 0},
            {"name": "maximumBlockDelay", "label": "Max Block Delay", "type": "int", "default": 1440, "min": 1},
        ],
    },
    # Names
    {
        "key": "N1",
        "label": "REGISTER_NAME",
        "category": "Names",
        "path": "/names/register",
        "needs_pow": True,
        "fields": [
            {"name": "registrantPublicKey", "label": "Registrant Public Key", "auto": "pubkey"},
            {"name": "name", "label": "Name"},
            {"name": "data", "label": "Name Data", "default": "{}"},
        ],
    },
    {
        "key": "N2",
        "label": "UPDATE_NAME",
        "category": "Names",
        "path": "/names/update",
        "needs_pow": True,
        "fields": [
            {"name": "ownerPublicKey", "label": "Owner Public Key", "auto": "pubkey"},
            {"name": "name", "label": "Existing Name"},
            {"name": "newName", "label": "New Name (blank = keep)"},
            {"name": "newData", "label": "New Data (blank = keep)"},
        ],
    },
    {
        "key": "N3",
        "label": "SELL_NAME",
        "category": "Names",
        "path": "/names/sell",
        "needs_pow": True,
        "fields": [
            {"name": "ownerPublicKey", "label": "Owner Public Key", "auto": "pubkey"},
            {"name": "name", "label": "Name"},
            {"name": "salePrice", "label": "Sale Price (QORT)", "type": "decimal", "default": Decimal("0")},
        ],
    },
    {
        "key": "N4",
        "label": "CANCEL_SELL_NAME",
        "category": "Names",
        "path": "/names/cancelSell",
        "needs_pow": True,
        "fields": [
            {"name": "ownerPublicKey", "label": "Owner Public Key", "auto": "pubkey"},
            {"name": "name", "label": "Name"},
        ],
    },
    {
        "key": "N5",
        "label": "BUY_NAME",
        "category": "Names",
        "path": "/names/buy",
        "needs_pow": True,
        "fields": [
            {"name": "buyerPublicKey", "label": "Buyer Public Key", "auto": "pubkey"},
            {"name": "name", "label": "Name"},
            {"name": "seller", "label": "Seller Address", "type": "address"},
        ],
    },
    # Payments
    {
        "key": "P1",
        "label": "PAYMENT",
        "category": "Payments",
        "path": "/payments/pay",
        "needs_pow": False,
        "fields": [
            {"name": "senderPublicKey", "label": "Sender Public Key", "auto": "pubkey"},
            {"name": "recipient", "label": "Recipient Address", "type": "address"},
            {"name": "amount", "label": "Amount (QORT)", "type": "decimal", "default": Decimal("0")},
        ],
    },
    # Minting
    {
        "key": "M1",
        "label": "REWARD_SHARE",
        "category": "Minting",
        "path": "/addresses/rewardshare",
        "needs_pow": False,
        "fields": [
            {"name": "minterPublicKey", "label": "Minter Public Key", "auto": "pubkey"},
            {"name": "recipient", "label": "Recipient Address", "type": "address", "auto": "address"},
            {"name": "rewardSharePublicKey", "label": "Reward Share Public Key"},
            {"name": "sharePercent", "label": "Share Percent (0=self)", "type": "int", "default": 0, "min": 0},
        ],
    },
    # Chat
    {
        "key": "C1",
        "label": "CHAT",
        "category": "Chat",
        "path": "/chat",
        "needs_pow": True,
        "fields": [
            {"name": "senderPublicKey", "label": "Sender Public Key", "auto": "pubkey"},
            {"name": "txGroupId", "label": "Group ID", "type": "int", "default": 0, "min": 0},
            {"name": "data", "label": "Message (will be Base58 encoded)"},
        ],
    },
]

_CATEGORIES = sorted({tx["category"] for tx in TX_CATALOG})


# ---------------------------------------------------------------------------
# Form builder
# ---------------------------------------------------------------------------

def _auto_fill(field: Dict, ctx: AppContext) -> str | None:
    auto = field.get("auto")
    if auto == "pubkey":
        from qortium_cli.crypto import to_base58_pubkey
        try:
            return to_base58_pubkey(ctx.account.public_key)
        except Exception:
            return None
    if auto == "address":
        addr = ctx.account.account_address
        return addr if not is_placeholder(addr) else None
    return None


def _prompt_field(field: Dict, ctx: AppContext) -> Any:
    auto = _auto_fill(field, ctx)
    name = field["name"]
    label = field["label"]
    ftype = field.get("type", "str")
    default = field.get("default", "")

    if auto is not None:
        display = str(auto)[:30] + ("…" if len(str(auto)) > 30 else "")
        console.print(f"[dim]{label}:[/] [qort.accent]{display}[/] [dim](auto)[/]")
        return auto

    if ftype == "int":
        min_val = field.get("min", 0)
        default_int = int(default) if default != "" else 0
        return prompt_int(f"{label} [{default_int}]: ", default=default_int, minimum=min_val)

    if ftype == "decimal":
        default_dec = Decimal(str(default)) if default != "" else Decimal("0")
        return d8(prompt_decimal(f"{label} [{d8(default_dec)}]: ", default=default_dec))

    if ftype == "bool":
        default_bool = bool(default) if isinstance(default, bool) else True
        return prompt_yes_no(f"{label}", default_yes=default_bool)

    if ftype == "address":
        while True:
            val = prompt_str(f"{label}: ", str(default)).strip()
            if not val and default:
                return default
            if looks_like_qortal_address(val):
                return val
            warn("That doesn't look like a valid Qortium address.")

    return prompt_str(f"{label} [{default}]: ", str(default)).strip() or str(default)


def _build_payload(tx_def: Dict, ctx: AppContext) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    for field in tx_def["fields"]:
        value = _prompt_field(field, ctx)
        payload[field["name"]] = value

    # Special handling: CHAT — Base58 encode message data
    if tx_def["label"] == "CHAT" and "data" in payload:
        from qortium_cli.crypto import b58encode
        payload["data"] = b58encode(str(payload["data"]).encode("utf-8"))
        payload["isText"] = 1
        payload["isEncrypted"] = 0

    return payload


# ---------------------------------------------------------------------------
# Transaction runner
# ---------------------------------------------------------------------------

def _run_transaction(
    ctx: AppContext,
    tx_def: Dict,
    payload: Dict[str, Any],
    fee: str,
    tx_group_id: int,
    nerd_mode: bool,
) -> None:
    from qortium_cli.services import (
        make_session,
        build_raw_transaction,
        compute_transaction_nonce,
        sign_tx,
        process_tx,
        get_timestamp,
        get_last_reference,
        is_nonce_or_pow_error,
    )
    from qortium_cli.crypto import b58encode

    def _is_insufficient_fee(exc: Exception) -> bool:
        import requests
        if not isinstance(exc, requests.exceptions.HTTPError):
            return False
        detail = ((exc.response.text if exc.response else "") or "").upper()
        return "INSUFFICIENT_FEE" in detail

    path = tx_def["path"]
    needs_pow = tx_def["needs_pow"]
    label = tx_def["label"]

    with TxPipeline(label).run() as pipeline:
        # Step 1: Build
        pipeline.start(0)
        with make_session(ctx, include_api_key=True) as session:
            timestamp = get_timestamp(ctx, session)
            try:
                reference = get_last_reference(ctx, ctx.account.account_address, session)
            except RuntimeError:
                reference = b58encode(bytes(64))

            full_payload = {
                "timestamp": timestamp,
                "reference": reference,
                "fee": fee,
                "txGroupId": tx_group_id,
                **payload,
            }

            if nerd_mode:
                console.print()
                json_panel(full_payload, "Payload")

            unsigned_tx = build_raw_transaction(ctx, path, full_payload, session)
        pipeline.finish(0)

        if nerd_mode:
            console.print(f"\n[dim]Unsigned bytes:[/] [qort.muted]{str(unsigned_tx)[:80]}…[/]")

        # Step 2: PoW
        pipeline.start(1)
        if needs_pow:
            with make_session(ctx, include_api_key=True) as session:
                unsigned_tx, nonce_path = compute_transaction_nonce(ctx, unsigned_tx, session)
        pipeline.finish(1)

        # Step 3: Sign
        pipeline.start(2)
        with make_session(ctx, include_api_key=True) as session:
            signed_tx = sign_tx(ctx, unsigned_tx, session)
        pipeline.finish(2)

        if nerd_mode:
            console.print(f"\n[dim]Signed bytes:[/] [qort.muted]{str(signed_tx)[:80]}…[/]")

        # Step 4: Broadcast
        pipeline.start(3)
        with make_session(ctx, include_api_key=True) as session:
            result = process_tx(ctx, signed_tx, session)
        pipeline.finish(3)

    # Extract signature
    sig = ""
    if isinstance(result, dict):
        sig = str(result.get("signature", result.get("transactionSignature", "")) or "")
    elif isinstance(result, str) and len(result) > 10:
        sig = result.strip()

    ok_panel(f"Transaction submitted{chr(10)}TX: {sig}" if sig else "Transaction submitted.", title="✓ Success")

    if nerd_mode and result:
        json_panel(result if isinstance(result, dict) else {"result": str(result)}, "Node Response")


# ---------------------------------------------------------------------------
# TX Hub main entry
# ---------------------------------------------------------------------------

def tool_tx_hub(ctx: AppContext) -> None:
    if is_placeholder(ctx.account.private_key) or is_placeholder(ctx.account.api_key):
        error_panel("Wallet not configured. Run reconfigure first.", hint="Press 9 from main menu to reconfigure.")
        pause()
        return

    nerd_mode = False
    while True:
        print_banner(ctx.endpoint.base_url, "TX Hub")
        tool_header("Universal TX Hub", "✦")

        console.print("[qort.dim]Build, sign, and broadcast any transaction type.[/]")
        console.print("[qort.dim]Auto-fills your public key, address, timestamp, and fee=0.[/]\n")

        # Category menu
        console.print("[qort.heading]Categories:[/]")
        for i, cat in enumerate(_CATEGORIES, start=1):
            txs_in_cat = [tx for tx in TX_CATALOG if tx["category"] == cat]
            console.print(f"  [qort.key]{i})[/] [white]{cat}[/] [dim]({len(txs_in_cat)} types)[/]")
        nerd_label = "[bold yellow]⚡ ON[/]" if nerd_mode else "[dim]off[/]"
        console.print(f"  [qort.key]N)[/] [dim]Nerd mode[/] {nerd_label}")
        console.print(f"  [qort.key]0)[/] [dim]Back[/]")
        console.print()

        choice = read_menu_choice("").upper()
        if choice == "0":
            return

        if choice == "N":
            nerd_mode = not nerd_mode
            state = "⚡ ON — raw bytes and full JSON will be shown." if nerd_mode else "off."
            console.print(f"[qort.warn]Nerd mode {state}[/]\n")
            continue

        try:
            cat_idx = int(choice) - 1
            if cat_idx < 0 or cat_idx >= len(_CATEGORIES):
                warn("Unknown option.")
                pause()
                continue
            selected_category = _CATEGORIES[cat_idx]
        except ValueError:
            if choice != "N":
                warn("Unknown option.")
                pause()
            continue

        # TX type menu within category
        cat_txs = [tx for tx in TX_CATALOG if tx["category"] == selected_category]
        console.print(f"\n[qort.heading]{selected_category} Transactions:[/]")
        for j, tx in enumerate(cat_txs, start=1):
            pow_label = "[dim](PoW)[/]" if tx["needs_pow"] else ""
            console.print(f"  [qort.key]{j})[/] [white]{tx['label']}[/] {pow_label}")
        console.print(f"  [qort.key]0)[/] [dim]Back[/]")
        console.print()

        tx_choice = read_menu_choice("")
        if tx_choice == "0":
            continue
        try:
            tx_idx = int(tx_choice) - 1
            if tx_idx < 0 or tx_idx >= len(cat_txs):
                warn("Unknown option.")
                pause()
                continue
            tx_def = cat_txs[tx_idx]
        except ValueError:
            warn("Unknown option.")
            pause()
            continue

        # Field collection
        console.print(f"\n[qort.heading]Build: {tx_def['label']}[/]")
        if tx_def.get("needs_pow"):
            console.print("[qort.warn]This transaction requires PoW computation (may take 5-60s).[/]")
        console.print()

        try:
            payload = _build_payload(tx_def, ctx)
        except KeyboardInterrupt:
            warn("Cancelled.")
            pause()
            continue

        # Common fields
        console.print()
        fee = d8(prompt_decimal("Fee [0.00000000]: ", default=Decimal("0")))
        tx_group_id = prompt_int("txGroupId [0]: ", default=0, minimum=0)

        # Confirm
        console.print()
        json_panel({**payload, "fee": fee, "txGroupId": tx_group_id}, "Transaction Preview")
        if not prompt_yes_no("\nSubmit this transaction?", default_yes=False):
            warn("Cancelled.")
            pause()
            continue

        console.print()
        try:
            _run_transaction(ctx, tx_def, payload, fee, tx_group_id, nerd_mode)
        except KeyboardInterrupt:
            warn_panel("Transaction cancelled by user.")
        except Exception as exc:
            error_panel(pretty_exception(exc), hint="Check node connection and API key.")

        pause()
