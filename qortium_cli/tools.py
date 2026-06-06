from __future__ import annotations

import base64
import datetime
import hashlib
import json
import traceback
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List

import requests

from qortium_cli.constants import BOLD, CHAT_USER_COLORS, RESET
from qortium_cli.crypto import b58decode, b58encode, is_base58, to_base58_pubkey
from qortium_cli.models import AppContext, ToolPlugin
from qortium_cli.services import (
    build_chat,
    build_payment,
    build_raw_transaction,
    compute_transaction_nonce,
    compute_chat_nonce,
    fetch_node_snapshot,
    get_asset_balances,
    get_asset_info,
    get_chat_messages,
    get_last_reference,
    get_recommended_fee,
    get_qort_balance,
    get_timestamp,
    get_unconfirmed_chat_messages,
    is_nonce_or_pow_error,
    make_session,
    process_tx,
    request_text_or_json,
    sign_tx,
)
from qortium_cli.storage import write_chat_settings
from qortium_cli.ui import (
    error,
    ok,
    pause,
    print_banner,
    print_option,
    print_section,
    print_stat,
    prompt_decimal,
    prompt_int,
    prompt_str,
    prompt_yes_no,
    read_menu_choice,
    warn,
)
from qortium_cli.utils import d8, format_bool, format_sync_percent, format_uptime, pretty_exception
from qortium_cli.utils import qort_to_atomic
from qortium_cli.validators import is_placeholder, looks_like_qortal_address

CHAT_HISTORY_PAGE_SIZE = 200
CHAT_HISTORY_MAX_MESSAGES = 1000
ENABLE_WALLET_TOOL = True
ENABLE_SEND_PAYMENTS = True
APPROVAL_THRESHOLDS = ("NONE", "ONE", "PCT20", "PCT40", "PCT60", "PCT80", "PCT100")
ATOMIC_UNITS = Decimal("100000000")


def _chat_user_color(identity: str) -> str:
    key = (identity or "unknown").strip().lower()
    if not key:
        key = "unknown"

    digest = hashlib.sha256(key.encode("utf-8")).digest()
    index = int.from_bytes(digest[:2], "big") % len(CHAT_USER_COLORS)
    return CHAT_USER_COLORS[index]


def _colorize_chat_identity(label: str, identity: str) -> str:
    color = _chat_user_color(identity)
    return f"{color}{BOLD}{label}{RESET}"


def _is_node_unreachable_error(exc: Exception) -> bool:
    if isinstance(exc, (requests.exceptions.ConnectionError, requests.exceptions.Timeout)):
        return True

    message = str(exc).lower()
    markers = (
        "winerror 10061",
        "connection refused",
        "failed to establish a new connection",
        "max retries exceeded",
        "connection aborted",
        "timed out",
    )
    return any(marker in message for marker in markers)


def _print_node_unreachable_hint(ctx: AppContext) -> None:
    error(f"Node API is not reachable at {ctx.endpoint.base_url}")
    print("Start Qortium, wait for the API, then retry.")
    print("Preview quick check:")
    print("  preview\\start.bat")
    print("  preview\\status.bat --wait")


def _print_debug_traceback(ctx: AppContext, exc: Exception) -> None:
    if not ctx.debug:
        return

    # Request stack traces are noisy and rarely actionable for users.
    if isinstance(exc, requests.exceptions.RequestException):
        return

    traceback.print_exc()


def ensure_api_key(ctx: AppContext) -> None:
    if is_placeholder(ctx.account.api_key):
        raise RuntimeError("API key is missing or placeholder.")


def ensure_wallet_config_ready(ctx: AppContext) -> None:
    required = [
        ("ACCOUNT_ADDRESS", ctx.account.account_address),
        ("PUBLIC_KEY", ctx.account.public_key),
        ("PRIVATE_KEY", ctx.account.private_key),
        ("API_KEY", ctx.account.api_key),
    ]

    missing = [name for name, value in required if is_placeholder(value)]
    if missing:
        raise RuntimeError("Run setup/reconfigure first. Missing values: " + ", ".join(missing))
    if not looks_like_qortal_address(ctx.account.account_address):
        raise RuntimeError(f"ACCOUNT_ADDRESS does not look valid: {ctx.account.account_address}")


def _format_chat_timestamp(timestamp_ms: Any) -> str:
    try:
        timestamp = int(timestamp_ms) / 1000.0
        return datetime.datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return "Unknown"


def _extract_doc_text(node: Any) -> str:
    if isinstance(node, dict):
        node_type = str(node.get("type", ""))
        if node_type == "text":
            return str(node.get("text", ""))

        parts = []
        for child in node.get("content", []):
            parts.append(_extract_doc_text(child))

        if node_type == "paragraph":
            return "".join(parts) + "\n"
        return "".join(parts)

    if isinstance(node, list):
        return "".join(_extract_doc_text(child) for child in node)

    return ""


def _decode_chat_data(data: Any, encoding: Any) -> str:
    if not isinstance(data, str) or not data:
        return ""

    enc = str(encoding or "").upper()
    decoded_bytes = None

    if enc == "BASE64":
        try:
            decoded_bytes = base64.b64decode(data)
        except Exception:
            return data
    elif enc == "BASE58" or is_base58(data):
        try:
            decoded_bytes = b58decode(data)
        except Exception:
            return data

    if decoded_bytes is None:
        return data

    text = decoded_bytes.decode("utf-8", errors="replace")
    stripped = text.strip()

    if stripped.startswith("{") and stripped.endswith("}"):
        try:
            payload = json.loads(stripped)
            if isinstance(payload, dict):
                message_doc = payload.get("messageText")
                if isinstance(message_doc, dict):
                    doc_text = _extract_doc_text(message_doc).strip()
                    if doc_text:
                        return doc_text
        except Exception:
            pass

    return text


def _get_chat_fee_decimal(ctx: AppContext) -> Decimal:
    try:
        fee = Decimal(str(ctx.chat.fee).strip())
        if fee < 0:
            return Decimal("0")
        return fee
    except Exception:
        return Decimal("0")


def _extract_tx_signature(result: Any) -> str:
    if isinstance(result, dict):
        for key in ("signature", "transactionSignature", "sig"):
            value = result.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()

    if isinstance(result, str):
        text = result.strip()
        if text and text.lower() not in {"true", "false"}:
            return text

    return ""


def _is_insufficient_fee_error(exc: Exception) -> bool:
    if not isinstance(exc, requests.exceptions.HTTPError):
        return False
    if exc.response is None:
        return False

    detail = (exc.response.text or "").upper()
    return "INSUFFICIENT_FEE" in detail


def _is_invalid_signature_error(exc: Exception) -> bool:
    if not isinstance(exc, requests.exceptions.HTTPError):
        return False
    if exc.response is None:
        return False
    detail = (exc.response.text or "").lower()
    return "invalid signature" in detail or '"error":101' in detail


def _prompt_tx_common_inputs(default_fee: Decimal = Decimal("0")) -> tuple[str, int]:
    fee = prompt_decimal(f"Fee [{d8(default_fee)}]: ", default=default_fee)
    tx_group_id = prompt_int("txGroupId [0]: ", default=0, minimum=0)
    return d8(fee), int(tx_group_id)


def _submit_builder_transaction(
    ctx: AppContext,
    path: str,
    label: str,
    extra_payload: Dict[str, Any],
    fee: str,
    tx_group_id: int,
    auto_nonce: bool = True,
) -> None:
    ensure_wallet_config_ready(ctx)
    with make_session(ctx, include_api_key=True) as session:
        print("\\n[1/3] Building transaction...", flush=True)
        timestamp = get_timestamp(ctx, session)
        try:
            reference = get_last_reference(ctx, ctx.account.account_address, session)
        except RuntimeError as exc:
            if "No last reference found" not in str(exc):
                raise

            warn("No last reference found for this account.")
            warn("This account likely has no prior chain activity yet.")
            print("You can fund/activate the account first, or try zero-reference fallback now.")
            use_zero_reference = prompt_yes_no(
                "Try zero-reference fallback (64 zero bytes)?",
                default_yes=False,
            )
            if not use_zero_reference:
                raise RuntimeError(
                    "Cancelled because no last reference is available yet. "
                    "Fund/activate the account first, then retry."
                ) from exc

            reference = b58encode(bytes(64))
            warn("Using zero-reference fallback for this attempt.")

        payload = {
            "timestamp": timestamp,
            "reference": reference,
            "fee": fee,
            "txGroupId": tx_group_id,
        }
        payload.update(extra_payload)
        unsigned_tx = build_raw_transaction(ctx, path, payload, session)

        print("[2/3] Signing transaction...", flush=True)
        signed_tx = sign_tx(ctx, unsigned_tx, session)

        print("[3/3] Processing transaction...", flush=True)
        fee_retried = False
        nonce_retried = False
        while True:
            try:
                result = process_tx(ctx, signed_tx, session)
                break
            except Exception as exc:
                should_try_mempow = (
                    _is_insufficient_fee_error(exc)
                    or is_nonce_or_pow_error(exc)
                    or _is_invalid_signature_error(exc)
                )
                if auto_nonce and not nonce_retried and should_try_mempow:
                    try:
                        print("\\n[1/3] Computing nonce...", flush=True)
                        unsigned_tx, nonce_path = compute_transaction_nonce(ctx, unsigned_tx, session)
                        nonce_retried = True
                        warn(f"Computed mempow nonce via {nonce_path}.")
                        print("[2/3] Re-signing transaction...", flush=True)
                        signed_tx = sign_tx(ctx, unsigned_tx, session)
                        print("[3/3] Re-processing transaction...", flush=True)
                        continue
                    except Exception:
                        if not _is_insufficient_fee_error(exc):
                            raise

                if fee_retried or not _is_insufficient_fee_error(exc):
                    raise

                warn("Transaction rejected for insufficient fee.")
                try:
                    current_fee = Decimal(str(payload.get("fee", "0")))
                except (InvalidOperation, ValueError):
                    current_fee = Decimal("0")

                recommended_fee = get_recommended_fee(ctx, unsigned_tx, session)
                if recommended_fee <= current_fee:
                    raise RuntimeError(
                        f"Node reported INSUFFICIENT_FEE, but recommended fee ({recommended_fee}) "
                        f"is not greater than current fee ({current_fee})."
                    ) from exc

                payload["fee"] = d8(recommended_fee)
                fee_retried = True
                nonce_retried = False
                warn(f"Retrying with recommended fee: {payload['fee']}")

                print("\\n[1/3] Rebuilding transaction...", flush=True)
                unsigned_tx = build_raw_transaction(ctx, path, payload, session)
                print("[2/3] Re-signing transaction...", flush=True)
                signed_tx = sign_tx(ctx, unsigned_tx, session)
                print("[3/3] Re-processing transaction...", flush=True)

    signature = _extract_tx_signature(result)
    ok(f"{label} submitted.")
    if signature:
        print("Signature: " + signature)
    if ctx.debug:
        print("Process response: " + str(result))


def _format_asset_balance(balance_raw: Any, divisible: bool) -> str:
    try:
        atomic = Decimal(str(balance_raw))
    except Exception:
        atomic = Decimal("0")
    if divisible:
        return d8(atomic / ATOMIC_UNITS)
    return str(int(atomic))


def _fetch_chat_timeline(ctx: AppContext) -> List[Dict[str, Any]]:
    tx_group_id = int(ctx.chat.tx_group_id)

    with make_session(ctx, include_api_key=False) as session:
        confirmed: List[Dict[str, Any]] = []
        offset = 0

        while len(confirmed) < CHAT_HISTORY_MAX_MESSAGES:
            room_left = CHAT_HISTORY_MAX_MESSAGES - len(confirmed)
            page_limit = min(CHAT_HISTORY_PAGE_SIZE, room_left)
            chunk = get_chat_messages(
                ctx,
                session,
                tx_group_id=tx_group_id,
                limit=page_limit,
                offset=offset,
                reverse=False,
                encoding="BASE64",
            )
            if not chunk:
                break

            confirmed.extend(chunk)
            if len(chunk) < page_limit:
                break
            offset += len(chunk)

        unconfirmed = get_unconfirmed_chat_messages(
            ctx,
            session,
            tx_group_id=tx_group_id,
            limit=CHAT_HISTORY_PAGE_SIZE,
        )

    messages: List[Dict[str, Any]] = list(confirmed)
    seen_signatures = {
        str(row.get("signature") or "") for row in messages if str(row.get("signature") or "")
    }

    for row in unconfirmed:
        signature = str(row.get("signature") or "")
        if signature and signature in seen_signatures:
            continue
        messages.append(row)
        if signature:
            seen_signatures.add(signature)

    messages.sort(key=lambda item: int(item.get("timestamp") or 0))
    if len(messages) > CHAT_HISTORY_MAX_MESSAGES:
        messages = messages[-CHAT_HISTORY_MAX_MESSAGES:]

    return messages


def _print_chat_timeline(messages: List[Dict[str, Any]]) -> None:
    if not messages:
        warn("No messages found for this group.")
        return

    print_section(f"Chat Timeline ({len(messages)} messages)")
    print()

    for message in messages:
        timestamp = _format_chat_timestamp(message.get("timestamp"))
        sender_address = str(message.get("sender") or "").strip()
        sender_label = str(message.get("senderName") or sender_address or "Unknown").strip()
        sender = _colorize_chat_identity(sender_label, sender_address or sender_label)

        recipient = str(message.get("recipient") or "").strip()
        recipient_label = _colorize_chat_identity(recipient, recipient) if recipient else ""

        body = _decode_chat_data(message.get("data"), message.get("encoding"))
        is_encrypted = bool(message.get("isEncrypted", False))
        is_unconfirmed = bool(message.get("_unconfirmed", False))

        target_label = f" -> {recipient_label}" if recipient else ""
        encryption_label = " [enc]" if is_encrypted else ""
        unconfirmed_label = " [mempool]" if is_unconfirmed else ""
        print(f"[{timestamp}] {sender}{target_label}{encryption_label}{unconfirmed_label}")

        if body.strip():
            for line in body.splitlines():
                print(f"  {line}")
        else:
            print("  [no text payload]")

        print()


def _send_chat_message(ctx: AppContext, message: str) -> Any:
    ensure_wallet_config_ready(ctx)

    sender_pub = to_base58_pubkey(ctx.account.public_key)
    data_b58 = b58encode(message.encode("utf-8"))
    fee = _get_chat_fee_decimal(ctx)
    tx_group_id = int(ctx.chat.tx_group_id)

    with make_session(ctx, include_api_key=True) as session:
        print("\\n[1/4] Building chat transaction...", flush=True)
        timestamp = get_timestamp(ctx, session)
        payload = {
            "timestamp": timestamp,
            "fee": d8(fee),
            "txGroupId": tx_group_id,
            "senderPublicKey": sender_pub,
            "data": data_b58,
            "isText": 1,
            "isEncrypted": 0,
        }
        unsigned_tx = build_chat(ctx, payload, session)

        print("[2/4] Computing nonce (can take 10s-180s on lower-balance accounts)...", flush=True)
        try:
            unsigned_tx = compute_chat_nonce(ctx, unsigned_tx, session)
        except Exception as exc:
            if "timed out" in str(exc).lower():
                raise RuntimeError(
                    "Nonce computation timed out. This is often just slow mempow. "
                    "Try again, raise TIMEOUT_SECONDS in endpoint settings, or fund the account to reduce PoW difficulty."
                ) from exc
            raise

        print("[3/4] Signing transaction...", flush=True)
        signed_tx = sign_tx(ctx, unsigned_tx, session)

        print("[4/4] Processing transaction...", flush=True)
        result = process_tx(ctx, signed_tx, session)

    return result


def run_chat_room(ctx: AppContext) -> None:
    ensure_wallet_config_ready(ctx)

    while True:
        print_banner(ctx.endpoint.base_url, f"Chat Room (Group {ctx.chat.tx_group_id})")
        print_stat("Group", ctx.chat.tx_group_id)
        print_stat("Fee", d8(_get_chat_fee_decimal(ctx)))
        print()
        print("Type a message and press Enter to send.")
        print("Use /quit to leave chat. Empty input refreshes.")
        print()

        try:
            messages = _fetch_chat_timeline(ctx)
            _print_chat_timeline(messages)
        except Exception as exc:
            error("Failed to fetch chat timeline:")
            if _is_node_unreachable_error(exc):
                _print_node_unreachable_hint(ctx)
            else:
                print(pretty_exception(exc))
                _print_debug_traceback(ctx, exc)
            pause()
            return

        raw = prompt_str("message > ", "")
        if raw.strip() == "/quit":
            return
        if raw.strip() == "":
            continue

        try:
            result = _send_chat_message(ctx, raw)
            ok("Chat message submitted.")
            if ctx.debug:
                print("Process response: " + str(result))
            input("Press Enter to refresh chat...")
        except Exception as exc:
            error("Failed to send chat:")
            if _is_node_unreachable_error(exc):
                _print_node_unreachable_hint(ctx)
            else:
                print(pretty_exception(exc))
                _print_debug_traceback(ctx, exc)
            pause()


def tx_group_join(ctx: AppContext) -> None:
    ensure_wallet_config_ready(ctx)
    group_id = prompt_int("Group ID [1]: ", default=1, minimum=1)
    fee, tx_group_id = _prompt_tx_common_inputs(default_fee=Decimal("0"))
    sender_pub = to_base58_pubkey(ctx.account.public_key)

    _submit_builder_transaction(
        ctx,
        "/groups/join",
        "JOIN_GROUP",
        {
            "joinerPublicKey": sender_pub,
            "groupId": group_id,
        },
        fee,
        tx_group_id,
    )


def tx_group_create(ctx: AppContext) -> None:
    ensure_wallet_config_ready(ctx)
    group_name = prompt_str("Group name: ").strip()
    if not group_name:
        warn("Group name cannot be empty.")
        return

    description = prompt_str("Description: ").strip()
    if not description:
        warn("Description cannot be empty.")
        return

    threshold = prompt_str("Approval threshold [NONE]: ", "NONE").strip().upper()
    if threshold not in APPROVAL_THRESHOLDS:
        warn("Invalid approval threshold.")
        return

    min_block_delay = prompt_int("Minimum block delay [0]: ", default=0, minimum=0)
    max_block_delay = prompt_int("Maximum block delay [1440]: ", default=1440, minimum=1)
    if max_block_delay < min_block_delay:
        warn("Maximum block delay must be >= minimum block delay.")
        return

    open_group = prompt_yes_no("Open group?", default_yes=True)
    fee, tx_group_id = _prompt_tx_common_inputs(default_fee=Decimal("0"))
    sender_pub = to_base58_pubkey(ctx.account.public_key)

    _submit_builder_transaction(
        ctx,
        "/groups/create",
        "CREATE_GROUP",
        {
            "groupName": group_name,
            "description": description,
            "approvalThreshold": threshold,
            "minimumBlockDelay": min_block_delay,
            "maximumBlockDelay": max_block_delay,
            "open": open_group,
            "creatorPublicKey": sender_pub,
        },
        fee,
        tx_group_id,
    )


def tx_name_register(ctx: AppContext) -> None:
    ensure_wallet_config_ready(ctx)
    name = prompt_str("Name to register: ").strip()
    if not name:
        warn("Name cannot be empty.")
        return

    name_data = prompt_str("Name data [{}]: ", "{}")
    fee, tx_group_id = _prompt_tx_common_inputs(default_fee=Decimal("0"))
    sender_pub = to_base58_pubkey(ctx.account.public_key)

    _submit_builder_transaction(
        ctx,
        "/names/register",
        "REGISTER_NAME",
        {
            "registrantPublicKey": sender_pub,
            "name": name,
            "data": name_data,
        },
        fee,
        tx_group_id,
    )


def tool_chat_settings(ctx: AppContext) -> None:
    while True:
        print_banner(ctx.endpoint.base_url, "Chat Settings")
        print_stat("Current Group", ctx.chat.tx_group_id)
        print_stat("Current Fee", d8(_get_chat_fee_decimal(ctx)))
        print()
        print_option("1", "Set chat group ID")
        print_option("2", "Set chat fee")
        print_option("3", "Reset to defaults (group 0, fee 0)")
        print_option("0", "Back")
        choice = read_menu_choice("Choose an option: ")

        if choice == "0":
            return

        if choice == "1":
            new_group = prompt_int("Group ID [0]: ", default=int(ctx.chat.tx_group_id), minimum=0)
            ctx.chat.tx_group_id = int(new_group)
            write_chat_settings(ctx.settings_dir, ctx.chat)
            ok(f"Chat group set to {ctx.chat.tx_group_id}.")
            pause()
            continue

        if choice == "2":
            current_fee = _get_chat_fee_decimal(ctx)
            new_fee = prompt_decimal(f"Fee [{d8(current_fee)}]: ", default=current_fee)
            ctx.chat.fee = d8(new_fee)
            write_chat_settings(ctx.settings_dir, ctx.chat)
            ok(f"Chat fee set to {ctx.chat.fee}.")
            pause()
            continue

        if choice == "3":
            ctx.chat.tx_group_id = 0
            ctx.chat.fee = "0"
            write_chat_settings(ctx.settings_dir, ctx.chat)
            ok("Chat settings reset to defaults.")
            pause()
            continue

        warn("Unknown option.")
        pause()


def send_payment(ctx: AppContext) -> None:
    ensure_wallet_config_ready(ctx)
    recipient = prompt_str("Recipient Qortal address: ")
    if not looks_like_qortal_address(recipient):
        warn("That does not look like a valid Qortal address.")
        return

    amount = prompt_decimal("Amount QORT: ", default=Decimal("0"))
    if amount <= 0:
        warn("Amount must be greater than 0.")
        return

    fee = prompt_decimal("Fee [0.01]: ", default=Decimal("0.01"))
    tx_group_id = prompt_int("txGroupId [0]: ", default=0, minimum=0)
    sender_pub = to_base58_pubkey(ctx.account.public_key)

    with make_session(ctx, include_api_key=True) as session:
        timestamp = get_timestamp(ctx, session)
        payload = {
            "timestamp": timestamp,
            "fee": d8(fee),
            "txGroupId": tx_group_id,
            "recipient": recipient,
            "senderPublicKey": sender_pub,
            "amount": d8(amount),
        }

        unsigned_tx = build_payment(ctx, payload, session)
        signed_tx = sign_tx(ctx, unsigned_tx, session)
        result = process_tx(ctx, signed_tx, session)

    ok(f"Payment submitted: {d8(amount)} QORT -> {recipient}")
    if ctx.debug:
        print("Process response: " + str(result))


def send_asset_transfer(ctx: AppContext) -> None:
    ensure_wallet_config_ready(ctx)
    recipient = prompt_str("Recipient Qortal address: ").strip()
    if not looks_like_qortal_address(recipient):
        warn("That does not look like a valid Qortal address.")
        return

    asset_id = prompt_int("Asset ID (>0): ", minimum=1)
    tx_group_id = prompt_int("txGroupId [0]: ", default=0, minimum=0)
    fee = prompt_decimal("Fee [0.00000000]: ", default=Decimal("0"))
    sender_pub = to_base58_pubkey(ctx.account.public_key)

    with make_session(ctx, include_api_key=True) as session:
        asset_name = f"ASSET-{asset_id}"
        divisible = True
        try:
            asset_info = get_asset_info(ctx, session, asset_id=int(asset_id))
            asset_name = str(asset_info.get("name") or asset_name)
            divisible = bool(asset_info.get("divisible", True))
        except Exception:
            pass

        if divisible:
            amount_dec = prompt_decimal(f"Amount {asset_name}: ", default=Decimal("0"))
            if amount_dec <= 0:
                warn("Amount must be greater than 0.")
                return
            amount_atomic = qort_to_atomic(amount_dec)
            if amount_atomic <= 0:
                warn("Amount is too small for atomic units.")
                return
            amount_value = int(amount_atomic)
        else:
            amount_whole = prompt_int(f"Amount {asset_name} (whole units): ", default=1, minimum=1)
            amount_value = int(amount_whole)

        _submit_builder_transaction(
            ctx,
            "/assets/transfer",
            "TRANSFER_ASSET",
            {
                "recipient": recipient,
                "senderPublicKey": sender_pub,
                "amount": amount_value,
                "assetId": int(asset_id),
            },
            d8(fee),
            tx_group_id,
        )


def check_balance(ctx: AppContext) -> None:
    ensure_wallet_config_ready(ctx)
    with make_session(ctx, include_api_key=True) as session:
        balance = get_qort_balance(ctx, ctx.account.account_address, session)
    ok(f"Current balance: {d8(balance)} QORT")


def check_balances(ctx: AppContext) -> None:
    ensure_wallet_config_ready(ctx)

    with make_session(ctx, include_api_key=True) as session:
        rows = get_asset_balances(
            ctx,
            ctx.account.account_address,
            session,
            exclude_zero=True,
            limit=500,
            offset=0,
        )

        info_cache: Dict[int, Dict[str, Any]] = {}
        print_section("Asset Balances")

        if not rows:
            print("No non-zero balances found.")
            return

        for row in rows:
            try:
                asset_id = int(row.get("assetId"))
            except Exception:
                continue

            if asset_id not in info_cache and asset_id != 0:
                try:
                    info_cache[asset_id] = get_asset_info(ctx, session, asset_id=asset_id)
                except Exception:
                    info_cache[asset_id] = {}

            if asset_id == 0:
                asset_name = "QORT"
                divisible = True
            else:
                info = info_cache.get(asset_id, {})
                asset_name = str(row.get("assetName") or info.get("name") or f"ASSET-{asset_id}")
                divisible = bool(info.get("divisible", True))

            formatted = _format_asset_balance(row.get("balance", 0), divisible)
            suffix = "" if divisible else " units"
            print(f"- {asset_name} (ID {asset_id}): {formatted}{suffix}")


def run_admin_action(ctx: AppContext, path: str, label: str) -> None:
    ensure_api_key(ctx)
    if not prompt_yes_no(f"Confirm {label.lower()}?", default_yes=False):
        warn("Cancelled.")
        return

    with make_session(ctx, include_api_key=True) as session:
        result = request_text_or_json(ctx, session, "GET", path)
    ok(f"{label} request sent.")
    print("Response: " + str(result))


def tool_node(ctx: AppContext) -> None:
    while True:
        print_banner(ctx.endpoint.base_url, "Node")
        try:
            snapshot = fetch_node_snapshot(ctx)
            info = snapshot["info"] or {}
            status = snapshot["status"] or {}

            print_section("Node Information")
            print_stat("Version", info.get("buildVersion", "Unknown"))
            print_stat("Type", info.get("type", "Unknown"))
            print_stat("Testnet", format_bool(info.get("isTestNet", "Unknown")))
            print_stat("Uptime", format_uptime(info.get("uptime")))
            print()
            print_section("Node Status")
            print_stat("Height", status.get("height", "Unknown"))
            print_stat("Sync Percent", format_sync_percent(status.get("syncPercent", "Unknown")))
            print_stat("Synchronizing", format_bool(status.get("isSynchronizing", "Unknown")))
            print_stat("Minting Possible", format_bool(status.get("isMintingPossible", "Unknown")))
            print_stat("Connections", status.get("numberOfConnections", "Unknown"))
            print_stat("Data Connections", status.get("numberOfDataConnections", "Unknown"))
        except Exception as exc:
            error("Failed to fetch node stats:")
            print(pretty_exception(exc))

        print()
        print_option("1", "Refresh stats")
        print_option("2", "Stop node (/admin/stop)")
        print_option("3", "Restart node (/admin/restart)")
        print_option("4", "Bootstrap node (/admin/bootstrap)")
        print_option("0", "Back")
        choice = read_menu_choice("Choose an option: ")

        try:
            if choice == "0":
                return
            if choice == "1":
                continue
            if choice == "2":
                run_admin_action(ctx, "/admin/stop", "Stop")
                pause()
                continue
            if choice == "3":
                run_admin_action(ctx, "/admin/restart", "Restart")
                pause()
                continue
            if choice == "4":
                run_admin_action(ctx, "/admin/bootstrap", "Bootstrap")
                pause()
                continue
        except Exception as exc:
            error("Action failed:")
            if _is_node_unreachable_error(exc):
                _print_node_unreachable_hint(ctx)
            else:
                print(pretty_exception(exc))
                _print_debug_traceback(ctx, exc)
            pause()
            continue

        warn("Unknown option.")
        pause()


def tool_chat(ctx: AppContext) -> None:
    while True:
        print_banner(ctx.endpoint.base_url, f"Chat (Group {ctx.chat.tx_group_id})")
        print_option("1", "Chat")
        print_option("2", "Chat settings")
        print_option("0", "Back")
        choice = read_menu_choice("Choose an option: ")

        try:
            if choice == "0":
                return
            if choice == "1":
                run_chat_room(ctx)
                continue
            if choice == "2":
                tool_chat_settings(ctx)
                continue
        except Exception as exc:
            error("Action failed:")
            if _is_node_unreachable_error(exc):
                _print_node_unreachable_hint(ctx)
            else:
                print(pretty_exception(exc))
                _print_debug_traceback(ctx, exc)
            pause()
            continue

        warn("Unknown option.")
        pause()


def tool_transactions(ctx: AppContext) -> None:
    while True:
        print_banner(ctx.endpoint.base_url, "Transactions")
        print_stat("Account", ctx.account.account_address)
        print()
        print_option("1", "Join group (/groups/join)")
        print_option("2", "Create group (/groups/create)")
        print_option("3", "Register name (/names/register)")
        print_option("0", "Back")
        choice = read_menu_choice("Choose an option: ")

        try:
            if choice == "0":
                return
            if choice == "1":
                tx_group_join(ctx)
                pause()
                continue
            if choice == "2":
                tx_group_create(ctx)
                pause()
                continue
            if choice == "3":
                tx_name_register(ctx)
                pause()
                continue
        except Exception as exc:
            error("Action failed:")
            if _is_node_unreachable_error(exc):
                _print_node_unreachable_hint(ctx)
            else:
                print(pretty_exception(exc))
                _print_debug_traceback(ctx, exc)
            pause()
            continue

        warn("Unknown option.")
        pause()


def tool_wallet(ctx: AppContext) -> None:
    while True:
        print_banner(ctx.endpoint.base_url, "Wallet")
        print_stat("Account", ctx.account.account_address)
        print()
        print_option("1", "Check QORT balance")
        print_option("2", "Check all asset balances")
        if ENABLE_SEND_PAYMENTS:
            print_option("3", "Send QORT payment")
            print_option("4", "Send asset transfer")
        print_option("0", "Back")
        choice = read_menu_choice("Choose an option: ")

        try:
            if choice == "0":
                return
            if choice == "1":
                check_balance(ctx)
                pause()
                continue
            if choice == "2":
                check_balances(ctx)
                pause()
                continue
            if choice == "3" and ENABLE_SEND_PAYMENTS:
                send_payment(ctx)
                pause()
                continue
            if choice == "4" and ENABLE_SEND_PAYMENTS:
                send_asset_transfer(ctx)
                pause()
                continue
        except Exception as exc:
            error("Action failed:")
            if _is_node_unreachable_error(exc):
                _print_node_unreachable_hint(ctx)
            else:
                print(pretty_exception(exc))
                _print_debug_traceback(ctx, exc)
            pause()
            continue

        warn("Unknown option.")
        pause()


def build_tool_plugins() -> List[ToolPlugin]:
    tools = [
        ToolPlugin("1", "Node", "Node status and admin controls", tool_node),
        ToolPlugin("2", "Chat", "Chat room + settings", tool_chat),
        ToolPlugin("3", "Transactions", "Groups and names", tool_transactions),
    ]
    if ENABLE_WALLET_TOOL:
        wallet_key = str(len(tools) + 1)
        tools.append(ToolPlugin(wallet_key, "Wallet", "Balance and payments", tool_wallet))
    return tools
