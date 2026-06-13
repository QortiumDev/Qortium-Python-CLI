from __future__ import annotations

import datetime
import hashlib
import traceback
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, List

import requests

from qortium_cli.chat_format import (
    DEFAULT_REACTION_CATEGORIES,
    DEFAULT_REACTION_OPTIONS,
    MessageReactionSummary,
    MessageThread,
    build_chat_message_text,
    build_message_reaction_index,
    build_message_threads,
    build_reaction_message_text,
    decode_chat_message,
)
from qortium_cli.constants import BOLD, CHAT_USER_COLORS, C_TEXT, QDN_SERVICES, RESET
from qortium_cli.crypto import b58encode, to_base58_pubkey
from qortium_cli.models import AppContext, ToolPlugin
from qortium_cli.services import (
    build_arbitrary_delete,
    build_arbitrary_from_path,
    build_chat,
    build_payment,
    build_raw_transaction,
    delete_local_arbitrary_resource,
    compute_transaction_nonce,
    compute_chat_nonce,
    fetch_node_snapshot,
    get_asset_balances,
    get_asset_info,
    get_chat_messages,
    get_admin_group_join_requests,
    get_group_info,
    get_group_invites,
    get_hosted_arbitrary_resources,
    get_last_reference,
    get_account_names,
    get_name_info,
    get_recommended_fee,
    get_qort_balance,
    get_timestamp,
    get_unconfirmed_chat_messages,
    is_nonce_or_pow_error,
    make_session,
    process_tx,
    request_text_or_json,
    search_arbitrary_resources,
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
    prompt_secret,
    prompt_str,
    prompt_yes_no,
    read_menu_choice,
    warn,
)
from qortium_cli.utils import d8, format_bool, format_sync_percent, format_uptime, pretty_exception
from qortium_cli.utils import qort_to_atomic
from qortium_cli.validators import is_placeholder, looks_like_qortal_address
from qortium_cli.wallet_backup import (
    default_wallet_backup_path,
    generate_wallet_backup_from_private_key,
    write_wallet_backup,
)

CHAT_HISTORY_PAGE_SIZE = 200
CHAT_HISTORY_MAX_MESSAGES = 1000
ENABLE_WALLET_TOOL = True
ENABLE_SEND_PAYMENTS = True
APPROVAL_THRESHOLDS = ("NONE", "ONE", "PCT20", "PCT40", "PCT60", "PCT80", "PCT100")
ATOMIC_UNITS = Decimal("100000000")
QDN_RESOURCE_PAGE_SIZE = 10
WHATS_NEW_ENTRIES = (
    (
        "v0.3.0",
        (
            "Chat timeline now understands Qortium Chat reply, edit, and reaction envelopes.",
            "Chat commands added: /reply, /edit, /react, /help, and /?.",
            "Reply and reaction selection groups messages by sender to reduce long lists.",
            "Reaction picker supports add/remove flows and emoji categories.",
            "Setup can check endpoints, detect local Core API keys, import wallet files, "
            "and create encrypted wallet files.",
            "Register Name can list owned names and update an existing name.",
        ),
    ),
)


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


def _format_invite_expiry(expiry_ms: Any) -> str:
    if expiry_ms in (None, ""):
        return "Never"

    try:
        expiry = int(expiry_ms)
    except (TypeError, ValueError):
        return "Unknown"

    if expiry <= 0:
        return "Never"
    return _format_chat_timestamp(expiry)


def _chat_message_signature(message: Dict[str, Any] | MessageThread) -> str:
    if isinstance(message, MessageThread):
        message = dict(message.original)
    return str(message.get("signature") or "").strip()


def _chat_message_sender(message: Dict[str, Any]) -> str:
    return str(message.get("sender") or "").strip()


def _chat_sender_label(message: Dict[str, Any]) -> str:
    sender_address = _chat_message_sender(message)
    return str(message.get("senderName") or sender_address or "Unknown").strip()


def _chat_identity_display(message: Dict[str, Any]) -> str:
    sender_address = _chat_message_sender(message)
    sender_label = _chat_sender_label(message)
    return _colorize_chat_identity(sender_label, sender_address or sender_label)


def _chat_message_snippet(thread: MessageThread) -> str:
    decoded = decode_chat_message(thread.latest)
    for line in decoded.body.splitlines():
        clean = line.strip()
        if not clean:
            continue
        if len(clean) > 96:
            return clean[:93].rstrip() + "..."
        return clean
    return "[no text]"


def _chat_reply_reference(thread: MessageThread, threads_by_signature: Dict[str, MessageThread]) -> str:
    decoded = decode_chat_message(thread.latest)
    if decoded.replied_to:
        return decoded.replied_to

    original_decoded = decode_chat_message(thread.original)
    if original_decoded.replied_to:
        return original_decoded.replied_to

    reference = str(thread.original.get("chatReference") or "").strip()
    if not reference:
        return ""

    referenced_thread = threads_by_signature.get(reference)
    if not referenced_thread:
        return ""

    if _chat_message_sender(dict(referenced_thread.original)) == _chat_message_sender(dict(thread.original)):
        return ""

    return reference


def _format_chat_reactions(reactions: tuple[MessageReactionSummary, ...]) -> str:
    return "  Reactions: " + "  ".join(
        f"{reaction.content} {reaction.count}" for reaction in reactions
    )


def _normalize_chat_message_input(raw: str) -> str:
    if raw.startswith("//"):
        return raw[1:]
    return raw


def _print_chat_command_help() -> None:
    print_section("Chat Commands")
    print("/reply  Reply to a recent message.")
    print("/react  React to a recent message.")
    print("/edit   Edit one of your own recent text messages.")
    print("/help   Show this help.")
    print("/?      Show this help.")
    print("/quit   Leave chat.")
    print("//text  Send a message that starts with /.")


def _replyable_chat_threads(messages: List[Dict[str, Any]]) -> List[MessageThread]:
    replyable: List[MessageThread] = []
    for thread in build_message_threads(messages):
        original = dict(thread.original)
        if not _chat_message_signature(original):
            continue
        if bool(original.get("_unconfirmed", False)):
            continue
        replyable.append(thread)
    return replyable


def _chat_thread_timestamp(thread: MessageThread) -> int:
    try:
        return int(thread.original.get("timestamp") or 0)
    except (TypeError, ValueError):
        return 0


def _replyable_chat_user_groups(
    messages: List[Dict[str, Any]],
) -> List[tuple[str, str, List[MessageThread]]]:
    groups: Dict[str, List[MessageThread]] = {}
    labels: Dict[str, str] = {}

    for thread in _replyable_chat_threads(messages):
        original = dict(thread.original)
        key = _chat_message_sender(original) or _chat_sender_label(original)
        groups.setdefault(key, []).append(thread)
        labels.setdefault(key, _chat_sender_label(original))

    user_groups: List[tuple[str, str, List[MessageThread]]] = []
    for key, threads in groups.items():
        threads.sort(key=_chat_thread_timestamp, reverse=True)
        user_groups.append((key, labels[key], threads))

    user_groups.sort(key=lambda group: _chat_thread_timestamp(group[2][0]), reverse=True)
    return user_groups


def _format_replyable_chat_user(label: str, threads: List[MessageThread]) -> str:
    count = len(threads)
    count_label = "1 message" if count == 1 else f"{count} messages"
    return f"{label} ({count_label}) - latest: {_chat_message_snippet(threads[0])}"


def _format_replyable_chat_thread(thread: MessageThread) -> str:
    timestamp = _format_chat_timestamp(thread.original.get("timestamp"))
    snippet = _chat_message_snippet(thread)
    edited_label = " [edited]" if thread.revisions else ""
    return f"{timestamp} - {snippet}{edited_label}"


def _select_chat_thread_by_sender(
    messages: List[Dict[str, Any]],
    *,
    sender_section_title: str,
    sender_prompt: str,
    message_section_prefix: str,
    message_prompt: str,
    empty_warning: str,
) -> MessageThread | None:
    user_groups = _replyable_chat_user_groups(messages)
    if not user_groups:
        warn(empty_warning)
        return None

    while True:
        print_section(sender_section_title)
        for index, (_, label, threads) in enumerate(user_groups, start=1):
            print_option(str(index), _format_replyable_chat_user(label, threads))
        print_option("0", "Cancel")

        choice = read_menu_choice(sender_prompt)
        if choice == "0":
            return None
        try:
            selected_index = int(choice) - 1
            if selected_index < 0:
                raise IndexError
            _, label, sender_threads = user_groups[selected_index]
        except (ValueError, IndexError):
            warn("Unknown option.")
            continue

        print_section(f"{message_section_prefix} {label}")
        for index, thread in enumerate(sender_threads, start=1):
            print_option(str(index), _format_replyable_chat_thread(thread))
        print_option("0", "Back")

        while True:
            choice = read_menu_choice(message_prompt)
            if choice == "0":
                break
            try:
                selected_index = int(choice) - 1
                if selected_index < 0:
                    raise IndexError
                return sender_threads[selected_index]
            except (ValueError, IndexError):
                warn("Unknown option.")


def _select_replyable_chat_thread(messages: List[Dict[str, Any]]) -> MessageThread | None:
    return _select_chat_thread_by_sender(
        messages,
        sender_section_title="Reply Sender",
        sender_prompt="Choose sender to reply to: ",
        message_section_prefix="Messages From",
        message_prompt="Choose message to reply to: ",
        empty_warning="No replyable messages found in the current chat history.",
    )


def _select_reactable_chat_thread(messages: List[Dict[str, Any]]) -> MessageThread | None:
    return _select_chat_thread_by_sender(
        messages,
        sender_section_title="Reaction Sender",
        sender_prompt="Choose sender to react to: ",
        message_section_prefix="Messages From",
        message_prompt="Choose message to react to: ",
        empty_warning="No reactable messages found in the current chat history.",
    )


def _select_chat_reaction(
    reactions: tuple[MessageReactionSummary, ...],
) -> tuple[str, bool] | None:
    self_reactions = _self_reaction_contents(reactions)
    if self_reactions:
        action = _select_reaction_action(self_reactions)
        if action is None:
            return None
    else:
        action = "add"

    if action == "remove":
        reaction = _select_reaction_to_remove(self_reactions)
        return (reaction, False) if reaction else None

    reaction = _select_reaction_to_add(self_reactions)
    return (reaction, True) if reaction else None


def _self_reaction_contents(reactions: tuple[MessageReactionSummary, ...]) -> set[str]:
    return {reaction.content for reaction in reactions if reaction.reacted_by_self}


def _format_reaction_list(reactions: set[str]) -> str:
    return " ".join(sorted(reactions, key=_reaction_sort_key))


def _reaction_sort_key(reaction: str) -> tuple[int, str]:
    try:
        index = DEFAULT_REACTION_OPTIONS.index(reaction)
    except ValueError:
        index = len(DEFAULT_REACTION_OPTIONS)
    return index, reaction


def _select_reaction_action(self_reactions: set[str]) -> str | None:
    print_section("Reaction Action")
    print(f"Current reactions: {_format_reaction_list(self_reactions)}")
    print_option("1", "Add reaction")
    print_option("2", "Remove reaction")
    print_option("0", "Cancel")

    while True:
        choice = read_menu_choice("Choose reaction action: ")
        if choice == "0":
            return None
        if choice == "1":
            return "add"
        if choice == "2":
            return "remove"
        warn("Unknown option.")


def _reaction_categories_for_add(self_reactions: set[str]) -> list[tuple[str, tuple[str, ...]]]:
    return [
        (label, tuple(reaction for reaction in reactions if reaction not in self_reactions))
        for label, reactions in DEFAULT_REACTION_CATEGORIES
        if any(reaction not in self_reactions for reaction in reactions)
    ]


def _select_reaction_to_add(self_reactions: set[str]) -> str | None:
    categories = _reaction_categories_for_add(self_reactions)
    if not categories:
        warn("No additional reactions are available.")
        return None

    while True:
        print_section("Reaction Category")
        for index, (label, reactions) in enumerate(categories, start=1):
            print_option(str(index), f"{label} ({len(reactions)})")
        print_option("0", "Cancel")

        choice = read_menu_choice("Choose reaction category: ")
        if choice == "0":
            return None
        try:
            selected_index = int(choice) - 1
            if selected_index < 0:
                raise IndexError
            label, category_reactions = categories[selected_index]
        except (ValueError, IndexError):
            warn("Unknown option.")
            continue

        print_section(label)
        for index, reaction in enumerate(category_reactions, start=1):
            print_option(str(index), reaction)
        print_option("0", "Back")

        while True:
            choice = read_menu_choice("Choose reaction: ")
            if choice == "0":
                break
            try:
                selected_index = int(choice) - 1
                if selected_index < 0:
                    raise IndexError
                return category_reactions[selected_index]
            except (ValueError, IndexError):
                warn("Unknown option.")


def _select_reaction_to_remove(self_reactions: set[str]) -> str | None:
    removable_reactions = tuple(sorted(self_reactions, key=_reaction_sort_key))
    if not removable_reactions:
        warn("No reactions to remove.")
        return None

    print_section("Remove Reaction")
    for index, reaction in enumerate(removable_reactions, start=1):
        print_option(str(index), reaction)
    print_option("0", "Cancel")

    while True:
        choice = read_menu_choice("Choose reaction to remove: ")
        if choice == "0":
            return None
        try:
            selected_index = int(choice) - 1
            if selected_index < 0:
                raise IndexError
            return removable_reactions[selected_index]
        except (ValueError, IndexError):
            warn("Unknown option.")


def _editable_chat_threads(ctx: AppContext, messages: List[Dict[str, Any]]) -> List[MessageThread]:
    editable: List[MessageThread] = []
    for thread in build_message_threads(messages):
        original = dict(thread.original)
        latest = dict(thread.latest)
        if _chat_message_sender(original) != ctx.account.account_address:
            continue
        if not _chat_message_signature(original):
            continue
        if bool(original.get("_unconfirmed", False)):
            continue
        if decode_chat_message(latest).kind != "text":
            continue
        editable.append(thread)
    return editable


def _format_editable_chat_thread(thread: MessageThread) -> str:
    timestamp = _format_chat_timestamp(thread.original.get("timestamp"))
    snippet = _chat_message_snippet(thread)
    edited_label = " [edited]" if thread.revisions else ""
    return f"{timestamp} - {snippet}{edited_label}"


def _select_editable_chat_thread(ctx: AppContext, messages: List[Dict[str, Any]]) -> MessageThread | None:
    editable = _editable_chat_threads(ctx, messages)
    if not editable:
        warn("No editable messages found in the current chat history.")
        return None

    print_section("Editable Messages")
    for index, thread in enumerate(editable, start=1):
        print_option(str(index), _format_editable_chat_thread(thread))
    print_option("0", "Cancel")

    while True:
        choice = read_menu_choice("Choose message to edit: ")
        if choice == "0":
            return None
        try:
            selected_index = int(choice) - 1
            if selected_index < 0:
                raise IndexError
            return editable[selected_index]
        except (ValueError, IndexError):
            warn("Unknown option.")


def _run_chat_reply_command(ctx: AppContext, messages: List[Dict[str, Any]]) -> Any | None:
    thread = _select_replyable_chat_thread(messages)
    if not thread:
        return None

    print()
    print("Replying to:")
    print(f"  {_chat_sender_label(dict(thread.original))}: {_chat_message_snippet(thread)}")
    reply = prompt_str("Reply message (Enter to cancel): ", "").strip()
    if not reply:
        warn("Reply cancelled.")
        return None

    target_signature = _chat_message_signature(dict(thread.original))
    message_text = build_chat_message_text(
        _normalize_chat_message_input(reply),
        target_signature,
    )
    return _send_chat_message(ctx, message_text)


def _run_chat_reaction_command(ctx: AppContext, messages: List[Dict[str, Any]]) -> Any | None:
    thread = _select_reactable_chat_thread(messages)
    if not thread:
        return None

    target_signature = _chat_message_signature(dict(thread.original))
    reactions_by_signature = build_message_reaction_index(
        messages,
        self_address=ctx.account.account_address,
    )

    print()
    print("Reacting to:")
    print(f"  {_chat_sender_label(dict(thread.original))}: {_chat_message_snippet(thread)}")

    selection = _select_chat_reaction(reactions_by_signature.get(target_signature, ()))
    if not selection:
        warn("Reaction cancelled.")
        return None

    reaction, content_state = selection
    message_text = build_reaction_message_text(reaction, content_state)
    return _send_chat_message(ctx, message_text, chat_reference=target_signature)


def _run_chat_edit_command(ctx: AppContext, messages: List[Dict[str, Any]]) -> Any | None:
    thread = _select_editable_chat_thread(ctx, messages)
    if not thread:
        return None

    print()
    print("Current message:")
    print(f"  {_chat_message_snippet(thread)}")
    replacement = prompt_str("New message (Enter to cancel): ", "").strip()
    if not replacement:
        warn("Edit cancelled.")
        return None

    original = dict(thread.original)
    original_signature = _chat_message_signature(original)
    replied_to = decode_chat_message(original).replied_to
    message_text = build_chat_message_text(
        _normalize_chat_message_input(replacement),
        replied_to,
    )
    return _send_chat_message(ctx, message_text, chat_reference=original_signature)


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


def _parse_arbitrary_tags(raw_tags: str) -> list[str]:
    tags = [part.strip() for part in str(raw_tags or "").split(",") if part.strip()]
    if len(tags) > 5:
        raise RuntimeError("QDN supports at most 5 tags.")
    for tag in tags:
        if len(tag) > 20:
            raise RuntimeError(f"QDN tag exceeds 20 characters: {tag}")
    return tags


def _submit_arbitrary_publish_transaction(
    ctx: AppContext,
    *,
    service: str,
    name: str,
    identifier: str,
    local_path: str,
    title: str,
    description: str,
    tags: list[str],
    category: str,
    fee: Decimal,
    preview: bool = False,
    auto_nonce: bool = True,
) -> None:
    ensure_wallet_config_ready(ctx)
    ensure_api_key(ctx)

    source_path = Path(local_path).expanduser()
    if not source_path.exists():
        raise RuntimeError(f"Local path does not exist: {source_path}")
    if fee < 0:
        raise RuntimeError("Fee cannot be negative.")

    current_fee = fee
    with make_session(ctx, include_api_key=True) as session:
        name_info = get_name_info(ctx, name, session)
        owner = str(name_info.get("owner", "") or "").strip()
        if not owner:
            raise RuntimeError(f"Unable to determine owner for registered name: {name}")
        if owner != ctx.account.account_address:
            raise RuntimeError(
                f"Name '{name}' is owned by {owner}, not the configured wallet "
                f"{ctx.account.account_address}."
            )

        print("\n[1/3] Building ARBITRARY APP transaction...", flush=True)
        fee_atomic = qort_to_atomic(current_fee)
        unsigned_tx = build_arbitrary_from_path(
            ctx,
            session,
            service=service,
            name=name,
            identifier=identifier or None,
            local_path=str(source_path.resolve()),
            title=title or None,
            description=description or None,
            tags=tags or None,
            category=category or None,
            fee_atomic=fee_atomic if fee_atomic > 0 else None,
            preview=preview,
        )

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
                        print("\n[1/3] Computing arbitrary transaction nonce...", flush=True)
                        unsigned_tx, nonce_path = compute_transaction_nonce(
                            ctx,
                            unsigned_tx,
                            session,
                            compute_paths=("/arbitrary/compute",),
                        )
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

                recommended_fee = get_recommended_fee(ctx, unsigned_tx, session)
                if recommended_fee <= current_fee:
                    raise RuntimeError(
                        f"Node reported INSUFFICIENT_FEE, but recommended fee "
                        f"({recommended_fee}) is not greater than current fee ({current_fee})."
                    ) from exc

                current_fee = recommended_fee
                fee_retried = True
                nonce_retried = False
                warn(f"Retrying with recommended fee: {d8(current_fee)} QORT")

                print("\n[1/3] Rebuilding ARBITRARY APP transaction...", flush=True)
                unsigned_tx = build_arbitrary_from_path(
                    ctx,
                    session,
                    service=service,
                    name=name,
                    identifier=identifier or None,
                    local_path=str(source_path.resolve()),
                    title=title or None,
                    description=description or None,
                    tags=tags or None,
                    category=category or None,
                    fee_atomic=qort_to_atomic(current_fee),
                    preview=preview,
                )
                print("[2/3] Re-signing transaction...", flush=True)
                signed_tx = sign_tx(ctx, unsigned_tx, session)
                print("[3/3] Re-processing transaction...", flush=True)

    signature = _extract_tx_signature(result)
    ok(f"ARBITRARY {service} publish submitted.")
    if signature:
        print("Signature: " + signature)
    if ctx.debug:
        print("Process response: " + str(result))


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

    threads = build_message_threads(messages)
    reactions_by_signature = build_message_reaction_index(messages)
    if not threads:
        warn("No displayable chat messages found for this group.")
        return

    threads_by_signature = {
        _chat_message_signature(thread): thread
        for thread in threads
        if _chat_message_signature(thread)
    }

    print_section(f"Chat Timeline ({len(threads)} messages)")
    print()

    for thread in threads:
        original = dict(thread.original)
        latest = dict(thread.latest)
        decoded = decode_chat_message(latest)

        timestamp = _format_chat_timestamp(original.get("timestamp"))
        sender = _chat_identity_display(original)

        recipient = str(original.get("recipient") or "").strip()
        recipient_label = _colorize_chat_identity(recipient, recipient) if recipient else ""

        is_encrypted = bool(latest.get("isEncrypted", False)) or decoded.kind == "encrypted"
        is_unconfirmed = bool(latest.get("_unconfirmed", False) or original.get("_unconfirmed", False))

        target_label = f" -> {recipient_label}" if recipient else ""
        encryption_label = " [enc]" if is_encrypted else ""
        edited_label = " [edited]" if thread.revisions else ""
        unconfirmed_label = " [mempool]" if is_unconfirmed else ""
        print(
            f"[{timestamp}] {sender}{target_label}"
            f"{encryption_label}{edited_label}{unconfirmed_label}"
        )

        replied_to = _chat_reply_reference(thread, threads_by_signature)
        referenced_thread = threads_by_signature.get(replied_to)
        if referenced_thread:
            reply_sender = _chat_sender_label(dict(referenced_thread.original))
            print(f"  > reply to {reply_sender}: {_chat_message_snippet(referenced_thread)}")
        elif replied_to:
            print("  > reply to: unavailable")

        if decoded.body.strip():
            for line in decoded.body.splitlines():
                print(f"  {line}")
        else:
            print("  [no text payload]")

        signature = _chat_message_signature(thread)
        reactions = reactions_by_signature.get(signature, ())
        if reactions:
            print(_format_chat_reactions(reactions))

        print()


def _send_chat_message(ctx: AppContext, message: str, *, chat_reference: str = "") -> Any:
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
        if chat_reference:
            payload["chatReference"] = chat_reference

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

        print("/? for help")
        raw = prompt_str("message > ", "")
        stripped = raw.strip()
        command = stripped.lower()
        if stripped == "":
            continue
        if command == "/quit":
            return
        if command in {"/help", "/?"}:
            _print_chat_command_help()
            pause()
            continue
        if command == "/reply":
            try:
                result = _run_chat_reply_command(ctx, messages)
                if result is None:
                    pause()
                    continue
                ok("Chat reply submitted.")
                if ctx.debug:
                    print("Process response: " + str(result))
                input("Press Enter to refresh chat...")
            except Exception as exc:
                error("Failed to reply to chat message:")
                if _is_node_unreachable_error(exc):
                    _print_node_unreachable_hint(ctx)
                else:
                    print(pretty_exception(exc))
                    _print_debug_traceback(ctx, exc)
                pause()
            continue
        if command == "/react":
            try:
                result = _run_chat_reaction_command(ctx, messages)
                if result is None:
                    pause()
                    continue
                ok("Chat reaction submitted.")
                if ctx.debug:
                    print("Process response: " + str(result))
                input("Press Enter to refresh chat...")
            except Exception as exc:
                error("Failed to react to chat message:")
                if _is_node_unreachable_error(exc):
                    _print_node_unreachable_hint(ctx)
                else:
                    print(pretty_exception(exc))
                    _print_debug_traceback(ctx, exc)
                pause()
            continue
        if command == "/edit":
            try:
                result = _run_chat_edit_command(ctx, messages)
                if result is None:
                    pause()
                    continue
                ok("Chat edit submitted.")
                if ctx.debug:
                    print("Process response: " + str(result))
                input("Press Enter to refresh chat...")
            except Exception as exc:
                error("Failed to edit chat message:")
                if _is_node_unreachable_error(exc):
                    _print_node_unreachable_hint(ctx)
                else:
                    print(pretty_exception(exc))
                    _print_debug_traceback(ctx, exc)
                pause()
            continue
        if stripped.startswith("/") and not stripped.startswith("//"):
            warn("Unknown chat command. Type /help for commands, or use // to send a leading slash.")
            pause()
            continue

        try:
            result = _send_chat_message(ctx, _normalize_chat_message_input(stripped))
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


def _submit_group_join(ctx: AppContext, group_id: int) -> None:
    ensure_wallet_config_ready(ctx)
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


def tx_group_join(ctx: AppContext) -> None:
    group_id = prompt_int("Group ID [1]: ", default=1, minimum=1)
    _submit_group_join(ctx, group_id)


def tx_group_accept_invite(ctx: AppContext) -> None:
    ensure_wallet_config_ready(ctx)

    with make_session(ctx, include_api_key=False) as session:
        invites = get_group_invites(ctx, ctx.account.account_address, session)
        for invite in invites:
            try:
                group_id = int(invite.get("groupId", 0))
            except (TypeError, ValueError):
                continue
            if group_id <= 0:
                continue

            invite["groupId"] = group_id
            try:
                group_info = get_group_info(ctx, group_id, session)
            except requests.exceptions.RequestException:
                group_info = {}
            invite["_groupName"] = str(group_info.get("groupName", "") or "").strip()

    invites = [
        invite
        for invite in invites
        if isinstance(invite.get("groupId"), int) and invite["groupId"] > 0
    ]
    if not invites:
        warn("No pending group invites found.")
        pause()
        return

    while True:
        print_banner(ctx.endpoint.base_url, "Accept Group Invite")
        print_stat("Account", ctx.account.account_address)
        print()
        for index, invite in enumerate(invites, start=1):
            group_id = int(invite["groupId"])
            group_name = str(invite.get("_groupName", "") or f"Group {group_id}")
            inviter = str(invite.get("inviter", "") or "Unknown")
            expiry = _format_invite_expiry(invite.get("expiry"))
            print_option(
                str(index),
                f"{group_name} (ID {group_id}) - from {inviter} - expires {expiry}",
            )
        print_option("0", "Back")
        choice = read_menu_choice("Choose an invite: ")

        if choice == "0":
            return

        try:
            selected_index = int(choice) - 1
            if selected_index < 0:
                raise IndexError
            selected = invites[selected_index]
        except (ValueError, IndexError):
            warn("Unknown option.")
            continue

        group_id = int(selected["groupId"])
        group_name = str(selected.get("_groupName", "") or f"Group {group_id}")
        if not prompt_yes_no(
            f"Accept invite to {group_name} (ID {group_id})?",
            default_yes=False,
        ):
            continue

        _submit_group_join(ctx, group_id)
        pause()
        return


def _submit_group_join_request_approval(
    ctx: AppContext,
    group_id: int,
    joiner: str,
) -> None:
    ensure_wallet_config_ready(ctx)

    with make_session(ctx, include_api_key=False) as session:
        current_requests = get_admin_group_join_requests(
            ctx,
            ctx.account.account_address,
            session,
        )
    still_pending = any(
        int(request.get("groupId", 0)) == group_id
        and str(request.get("joiner", "") or "").strip() == joiner
        for request in current_requests
    )
    if not still_pending:
        raise RuntimeError(
            "This join request is no longer pending. Refresh the request list and try again."
        )

    fee = prompt_decimal("Fee [0.00000000]: ", default=Decimal("0"))
    tx_group_id = prompt_int(
        f"txGroupId [{group_id}]: ",
        default=group_id,
        minimum=0,
    )
    sender_pub = to_base58_pubkey(ctx.account.public_key)

    _submit_builder_transaction(
        ctx,
        "/groups/invite",
        "GROUP_INVITE join approval",
        {
            "adminPublicKey": sender_pub,
            "groupId": group_id,
            "invitee": joiner,
            "timeToLive": 0,
        },
        d8(fee),
        tx_group_id,
    )


def tx_group_review_join_requests(ctx: AppContext) -> None:
    ensure_wallet_config_ready(ctx)

    with make_session(ctx, include_api_key=False) as session:
        join_requests = get_admin_group_join_requests(
            ctx,
            ctx.account.account_address,
            session,
        )

    if not join_requests:
        warn("No pending join requests found for groups you can approve.")
        pause()
        return

    while True:
        print_banner(ctx.endpoint.base_url, "Pending Group Join Requests")
        print_stat("Approver", ctx.account.account_address)
        print()
        for index, join_request in enumerate(join_requests, start=1):
            group_id = int(join_request["groupId"])
            group_name = str(
                join_request.get("groupName", "") or f"Group {group_id}"
            ).strip()
            joiner = str(join_request.get("joiner", "") or "").strip()
            print_option(
                str(index),
                f"{group_name} (ID {group_id}) - applicant {joiner}",
            )
        print_option("0", "Back")
        choice = read_menu_choice("Choose a join request: ")

        if choice == "0":
            return

        try:
            selected_index = int(choice) - 1
            if selected_index < 0:
                raise IndexError
            selected = join_requests[selected_index]
        except (ValueError, IndexError):
            warn("Unknown option.")
            continue

        group_id = int(selected["groupId"])
        group_name = str(selected.get("groupName", "") or f"Group {group_id}").strip()
        joiner = str(selected.get("joiner", "") or "").strip()
        if not prompt_yes_no(
            f"Approve {joiner} to join {group_name} (ID {group_id})?",
            default_yes=False,
        ):
            continue

        _submit_group_join_request_approval(ctx, group_id, joiner)
        pause()
        return


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
    name = prompt_str("Name to register (Enter to cancel): ").strip()
    if not name:
        warn("Name registration cancelled.")
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


def _select_owned_name_for_update(owned_names: List[str]) -> str | None:
    print()
    print_section("Choose Name")
    for index, name in enumerate(owned_names, start=1):
        print_option(str(index), name)
    print_option("0", "Cancel")
    choice = read_menu_choice("Choose a name: ")
    if choice == "0":
        warn("Name update cancelled.")
        return None

    try:
        selected_index = int(choice) - 1
        return owned_names[selected_index]
    except (ValueError, IndexError):
        warn("Unknown option.")
        return None


def tx_name_update(ctx: AppContext, owned_names: List[str]) -> None:
    ensure_wallet_config_ready(ctx)
    selected_name = _select_owned_name_for_update(owned_names)
    if not selected_name:
        return

    new_name = prompt_str(
        f"New name for '{selected_name}' [keep current]: ",
        "",
    )

    new_data = prompt_str(
        "New name data [keep current]: ",
        "",
    )

    fee, tx_group_id = _prompt_tx_common_inputs(default_fee=Decimal("0"))
    sender_pub = to_base58_pubkey(ctx.account.public_key)

    _submit_builder_transaction(
        ctx,
        "/names/update",
        "UPDATE_NAME",
        {
            "ownerPublicKey": sender_pub,
            "name": selected_name,
            "newName": new_name.strip(),
            "newData": new_data,
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


def tool_groups(ctx: AppContext) -> None:
    while True:
        print_banner(ctx.endpoint.base_url, "Groups")
        print_stat("Account", ctx.account.account_address)
        print()
        print_option("1", "Join group (/groups/join)")
        print_option("2", "Create group (/groups/create)")
        print_option("3", "View / accept invites sent to this account")
        print_option("4", "Review join requests for groups you manage")
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
                tx_group_accept_invite(ctx)
                continue
            if choice == "4":
                tx_group_review_join_requests(ctx)
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


def tool_register_name(ctx: AppContext) -> None:
    ensure_wallet_config_ready(ctx)
    print_banner(ctx.endpoint.base_url, "Register Name")
    print_stat("Account", ctx.account.account_address)
    print()

    with make_session(ctx, include_api_key=False) as session:
        owned_names = get_account_names(
            ctx,
            ctx.account.account_address,
            session,
            limit=500,
        )

    if not owned_names:
        tx_name_register(ctx)
        pause()
        return

    print_section("Registered Names")
    for name in owned_names:
        print(C_TEXT + f"- {name}" + RESET)
    print()
    print_option("1", "Update name")
    print_option("2", "New name")
    print_option("0", "Back")

    choice = read_menu_choice("Choose an option: ")
    if choice == "0":
        return
    if choice == "1":
        tx_name_update(ctx, owned_names)
        pause()
        return
    if choice == "2":
        tx_name_register(ctx)
        pause()
        return

    warn("Unknown option.")
    pause()


def _prompt_qdn_resource(ctx: AppContext) -> tuple[str, str, str]:
    while True:
        service = prompt_str("Service [APP]: ", "APP").strip().upper()
        if service in QDN_SERVICES:
            break
        warn(f"Unknown QDN service: {service}")
        print("Supported services:")
        print(", ".join(QDN_SERVICES))

    suggested_name = (ctx.account.name or "").strip()
    if is_placeholder(suggested_name) or looks_like_qortal_address(suggested_name):
        suggested_name = ""

    if suggested_name:
        name = prompt_str(f"Registered name [{suggested_name}]: ", suggested_name).strip()
    else:
        name = prompt_str("Registered name: ").strip()
    if not name:
        raise RuntimeError("Registered name cannot be empty.")

    identifier = prompt_str("Identifier [default]: ", "default").strip()
    if not identifier:
        identifier = "default"
    return service, name, identifier


def _qdn_resource_tuple(resource: Dict[str, Any]) -> tuple[str, str, str] | None:
    service = str(resource.get("service", "") or "").strip().upper()
    name = str(resource.get("name", "") or "").strip()
    identifier = str(resource.get("identifier", "") or "default").strip() or "default"
    if service not in QDN_SERVICES or not name:
        return None
    return service, name, identifier


def _qdn_resource_detail(resource: Dict[str, Any]) -> str:
    details: List[str] = []
    status = resource.get("status")
    if isinstance(status, dict):
        status_label = str(
            status.get("title") or status.get("status") or status.get("id") or ""
        ).strip()
        if status_label:
            details.append(status_label)

    metadata = resource.get("metadata")
    if isinstance(metadata, dict):
        title = str(metadata.get("title", "") or "").strip()
        if title:
            details.append(title)

    return " - ".join(details)


def select_qdn_resource(
    ctx: AppContext,
    *,
    hosted_only: bool,
) -> tuple[str, str, str] | None:
    query = prompt_str("Search name or identifier [all]: ", "").strip()
    while True:
        service = prompt_str("Service [any]: ", "").strip().upper()
        if not service or service in QDN_SERVICES:
            break
        warn(f"Unknown QDN service: {service}")

    owned_names: List[str] | None = None
    if not hosted_only:
        with make_session(ctx, include_api_key=False) as session:
            owned_names = get_account_names(
                ctx,
                ctx.account.account_address,
                session,
                limit=500,
            )
        if not owned_names:
            warn("No registered names owned by the configured wallet were found.")
            return None

    offset = 0
    while True:
        with make_session(ctx, include_api_key=hosted_only) as session:
            if hosted_only:
                all_rows = get_hosted_arbitrary_resources(
                    ctx,
                    session,
                    query=query,
                    limit=500,
                    offset=0,
                )
                if service:
                    all_rows = [
                        row
                        for row in all_rows
                        if str(row.get("service", "") or "").upper() == service
                    ]
                rows = all_rows[offset : offset + QDN_RESOURCE_PAGE_SIZE]
                has_next_page = offset + QDN_RESOURCE_PAGE_SIZE < len(all_rows)
            else:
                rows = search_arbitrary_resources(
                    ctx,
                    session,
                    query=query,
                    service=service,
                    names=owned_names,
                    limit=QDN_RESOURCE_PAGE_SIZE,
                    offset=offset,
                )
                has_next_page = len(rows) == QDN_RESOURCE_PAGE_SIZE

        resources = [
            (row, resource_tuple)
            for row in rows
            if (resource_tuple := _qdn_resource_tuple(row)) is not None
        ]

        print_banner(
            ctx.endpoint.base_url,
            "Hosted QDN Resources" if hosted_only else "Owned QDN Resources",
        )
        print_stat("Search", query or "All")
        print_stat("Service", service or "Any")
        print_stat("Offset", offset)
        print()

        if not resources:
            warn("No matching resources found on this page.")
        else:
            for index, (row, resource_tuple) in enumerate(resources, start=1):
                resource_service, resource_name, resource_identifier = resource_tuple
                label = f"{resource_service} / {resource_name} / {resource_identifier}"
                detail = _qdn_resource_detail(row)
                if detail:
                    label += f" - {detail}"
                print_option(str(index), label)

        if has_next_page:
            print_option("n", "Next page")
        if offset > 0:
            print_option("p", "Previous page")
        print_option("0", "Cancel")
        choice = read_menu_choice("Choose a resource: ").lower()

        if choice == "0":
            return None
        if choice == "n" and has_next_page:
            offset += QDN_RESOURCE_PAGE_SIZE
            continue
        if choice == "p" and offset > 0:
            offset = max(0, offset - QDN_RESOURCE_PAGE_SIZE)
            continue

        try:
            selected_index = int(choice) - 1
            if selected_index < 0:
                raise IndexError
            return resources[selected_index][1]
        except (ValueError, IndexError):
            warn("Unknown option.")


def choose_qdn_resource(
    ctx: AppContext,
    *,
    hosted_only: bool,
) -> tuple[str, str, str] | None:
    print_option("1", "Search and select a resource")
    print_option("2", "Enter service/name/identifier manually")
    print_option("0", "Cancel")
    choice = read_menu_choice("Choose resource input: ")
    if choice == "0":
        return None
    if choice == "1":
        return select_qdn_resource(ctx, hosted_only=hosted_only)
    if choice == "2":
        return _prompt_qdn_resource(ctx)
    warn("Unknown option.")
    return None


def browse_qdn_resources(ctx: AppContext) -> None:
    print_option("1", "Find an owned resource to delete on-chain")
    print_option("2", "Find a hosted resource to delete from this node")
    print_option("0", "Back")
    choice = read_menu_choice("Choose a lookup scope: ")
    if choice == "0":
        return
    if choice not in {"1", "2"}:
        warn("Unknown option.")
        return

    hosted_only = choice == "2"
    if hosted_only:
        ensure_api_key(ctx)

    selected = select_qdn_resource(ctx, hosted_only=hosted_only)
    if selected is None:
        return

    if hosted_only:
        _delete_selected_qdn_resource_locally(ctx, selected)
    else:
        _delete_selected_qdn_resource_on_chain(ctx, selected)


def _submit_arbitrary_delete_transaction(
    ctx: AppContext,
    service: str,
    name: str,
    identifier: str,
    fee: Decimal,
) -> None:
    ensure_wallet_config_ready(ctx)
    normalized_identifier = None if identifier.lower() == "default" else identifier
    fee_atomic = qort_to_atomic(fee)

    with make_session(ctx, include_api_key=True) as session:
        name_info = get_name_info(ctx, name, session)
        owner = str(name_info.get("owner", "") or "").strip()
        if not owner:
            raise RuntimeError(f"Unable to determine owner for registered name: {name}")
        if owner != ctx.account.account_address:
            raise RuntimeError(
                f"Name '{name}' is owned by {owner}, not the configured wallet "
                f"{ctx.account.account_address}."
            )

        print("\n[1/3] Building ARBITRARY DELETE transaction...", flush=True)
        unsigned_tx = build_arbitrary_delete(
            ctx,
            service,
            name,
            normalized_identifier,
            fee_atomic,
            session,
        )
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
                if not nonce_retried and should_try_mempow:
                    try:
                        print("\n[1/3] Computing arbitrary transaction nonce...", flush=True)
                        unsigned_tx, nonce_path = compute_transaction_nonce(
                            ctx,
                            unsigned_tx,
                            session,
                            compute_paths=("/arbitrary/compute",),
                        )
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

                recommended_fee = get_recommended_fee(ctx, unsigned_tx, session)
                if recommended_fee <= fee:
                    raise RuntimeError(
                        f"Node reported INSUFFICIENT_FEE, but recommended fee "
                        f"({recommended_fee}) is not greater than current fee ({fee})."
                    ) from exc

                fee = recommended_fee
                fee_atomic = qort_to_atomic(fee)
                fee_retried = True
                nonce_retried = False
                warn(f"Retrying with recommended fee: {d8(fee)} QORT")

                print("\n[1/3] Rebuilding ARBITRARY DELETE transaction...", flush=True)
                unsigned_tx = build_arbitrary_delete(
                    ctx,
                    service,
                    name,
                    normalized_identifier,
                    fee_atomic,
                    session,
                )
                print("[2/3] Re-signing transaction...", flush=True)
                signed_tx = sign_tx(ctx, unsigned_tx, session)
                print("[3/3] Re-processing transaction...", flush=True)

    signature = _extract_tx_signature(result)
    ok("ARBITRARY DELETE transaction submitted.")
    if signature:
        print("Signature: " + signature)


def _delete_selected_qdn_resource_on_chain(
    ctx: AppContext,
    selected: tuple[str, str, str],
) -> None:
    service, name, identifier = selected
    fee = prompt_decimal("Fee [0.00000000]: ", default=Decimal("0"))

    print()
    print_stat("Service", service)
    print_stat("Name", name)
    print_stat("Identifier", identifier)
    print_stat("Fee", f"{d8(fee)} QORT")
    warn("This publishes a network-visible deletion transaction.")
    print("The resource can be published again later, but the deletion remains in history.")
    if not prompt_yes_no("Publish this QDN resource deletion?", default_yes=False):
        warn("Cancelled.")
        return

    _submit_arbitrary_delete_transaction(ctx, service, name, identifier, fee)


def delete_qdn_resource_on_chain(ctx: AppContext) -> None:
    selected = choose_qdn_resource(ctx, hosted_only=False)
    if selected is None:
        warn("Cancelled.")
        return
    _delete_selected_qdn_resource_on_chain(ctx, selected)


def _delete_selected_qdn_resource_locally(
    ctx: AppContext,
    selected: tuple[str, str, str],
) -> None:
    service, name, identifier = selected

    print()
    print_stat("Service", service)
    print_stat("Name", name)
    print_stat("Identifier", identifier)
    warn("This removes only this node's cached/hosted copy.")
    print("The resource remains on-chain and can be downloaded again.")
    if not prompt_yes_no("Delete the local QDN resource data?", default_yes=False):
        warn("Cancelled.")
        return

    with make_session(ctx, include_api_key=True) as session:
        deleted = delete_local_arbitrary_resource(
            ctx,
            service,
            name,
            identifier,
            session,
        )

    if deleted:
        ok("Local cached/hosted resource data deleted.")
    else:
        warn("The node reported that no local resource data was deleted.")


def delete_qdn_resource_locally(ctx: AppContext) -> None:
    ensure_api_key(ctx)
    selected = choose_qdn_resource(ctx, hosted_only=True)
    if selected is None:
        warn("Cancelled.")
        return
    _delete_selected_qdn_resource_locally(ctx, selected)


def publish_qdn_app(ctx: AppContext) -> None:
    suggested_name = (ctx.account.name or "").strip()
    if is_placeholder(suggested_name) or looks_like_qortal_address(suggested_name):
        suggested_name = ""

    if suggested_name:
        name = prompt_str(f"Registered name [{suggested_name}]: ", suggested_name).strip()
    else:
        name = prompt_str("Registered name: ").strip()
    if not name:
        raise RuntimeError("Registered name cannot be empty.")

    identifier = prompt_str("Identifier [default]: ", "default").strip()
    if identifier.lower() in {"none", "null"}:
        identifier = ""
    elif not identifier:
        identifier = "default"
    elif identifier.lower() != "default":
        warn("Non-default APP identifiers may fail to open in some Qortium Home builds.")

    local_path = prompt_str("Local app path (folder or zip): ").strip()
    if not local_path:
        raise RuntimeError("Local app path cannot be empty.")

    title = prompt_str("Title [optional]: ", "").strip()
    description = prompt_str("Description [optional]: ", "").strip()
    tags = _parse_arbitrary_tags(prompt_str("Tags CSV [optional]: ", ""))
    category = prompt_str("Category [UNCATEGORIZED]: ", "UNCATEGORIZED").strip().upper()
    fee = prompt_decimal("Fee [0.00000000]: ", default=Decimal("0"))
    preview = prompt_yes_no("Preview mode?", default_yes=False)

    print()
    print_stat("Service", "APP")
    print_stat("Name", name)
    print_stat("Identifier", identifier or "(none)")
    print_stat("Path", str(Path(local_path).expanduser()))
    print_stat("Fee", f"{d8(fee)} QORT")
    if not prompt_yes_no("Publish this APP to QDN?", default_yes=False):
        warn("Cancelled.")
        return

    _submit_arbitrary_publish_transaction(
        ctx,
        service="APP",
        name=name,
        identifier=identifier,
        local_path=local_path,
        title=title,
        description=description,
        tags=tags,
        category=category,
        fee=fee,
        preview=preview,
    )


def tool_qdn_resources(ctx: AppContext) -> None:
    while True:
        print_banner(ctx.endpoint.base_url, "QDN Resources")
        print_option("1", "Look up and delete a QDN resource")
        print_option("2", "Delete resource on-chain")
        print_option("3", "Delete local cached/hosted copy")
        print_option("4", "Publish APP")
        print_option("0", "Back")
        choice = read_menu_choice("Choose an option: ")

        try:
            if choice == "0":
                return
            if choice == "1":
                browse_qdn_resources(ctx)
                pause()
                continue
            if choice == "2":
                delete_qdn_resource_on_chain(ctx)
                pause()
                continue
            if choice == "3":
                delete_qdn_resource_locally(ctx)
                pause()
                continue
            if choice == "4":
                publish_qdn_app(ctx)
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


def export_wallet_backup(ctx: AppContext) -> None:
    if is_placeholder(ctx.account.private_key):
        raise RuntimeError("Private key is missing. Run setup/reconfigure first.")
    if not looks_like_qortal_address(ctx.account.account_address):
        raise RuntimeError(
            f"ACCOUNT_ADDRESS does not look valid: {ctx.account.account_address}"
        )

    print()
    print(
        "This creates a Qortium Home version-3 wallet backup from the configured "
        "private key."
    )
    print(
        "Private-key wallets contain one QORT address and cannot derive additional "
        "addresses."
    )

    suggested_wallet_name = (ctx.account.name or "").strip()
    if is_placeholder(suggested_wallet_name) or looks_like_qortal_address(
        suggested_wallet_name
    ):
        suggested_wallet_name = "wallet"
    wallet_name = prompt_str(
        f"Wallet name [{suggested_wallet_name}]: ",
        suggested_wallet_name,
    ).strip()
    if not wallet_name:
        wallet_name = "wallet"

    warn("The backup password is required to restore this wallet.")
    password = prompt_secret("Backup password: ")
    if not password:
        warn("Wallet backup cancelled.")
        return

    confirmation = prompt_secret("Confirm backup password: ")
    if password != confirmation:
        warn("Passwords do not match.")
        return

    default_path = default_wallet_backup_path(
        ctx.account.account_address,
        wallet_name=wallet_name,
    )
    raw_path = prompt_str(
        f"Save path [{default_path}]: ",
        str(default_path),
    ).strip()
    output_path = Path(raw_path).expanduser()

    if output_path.exists() and not prompt_yes_no(
        f"{output_path} already exists. Overwrite?",
        default_yes=False,
    ):
        warn("Wallet backup cancelled.")
        return

    print("Encrypting Qortium Home private-key wallet backup...", flush=True)
    backup = generate_wallet_backup_from_private_key(
        ctx.account.private_key,
        ctx.account.account_address,
        password,
    )
    saved_path = write_wallet_backup(output_path, backup)
    ok("Qortium Home-compatible account backup saved.")
    print(f"File: {saved_path}")
    warn("Store this file and its password securely. Neither can replace the other.")


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
        print_option("5", "Save Qortium Home private-key wallet backup")
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
            if choice == "5":
                export_wallet_backup(ctx)
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


def _print_whats_new_entry(version: str, bullets: tuple[str, ...]) -> None:
    print_section(version)
    for bullet in bullets:
        print(C_TEXT + f"- {bullet}" + RESET)


def _tool_whats_new(ctx: AppContext) -> None:
    while True:
        print_banner(ctx.endpoint.base_url, "What's New?")
        for index, (version, _) in enumerate(WHATS_NEW_ENTRIES, start=1):
            print_option(str(index), version)
        print_option("0", "Back")

        choice = read_menu_choice("Choose a version: ")
        if choice == "0":
            return

        try:
            selected_index = int(choice) - 1
            if selected_index < 0:
                raise IndexError
            version, bullets = WHATS_NEW_ENTRIES[selected_index]
        except (ValueError, IndexError):
            warn("Unknown option.")
            pause()
            continue

        print_banner(ctx.endpoint.base_url, f"What's New? {version}")
        _print_whats_new_entry(version, bullets)
        pause()


def tool_help_info(ctx: AppContext) -> None:
    while True:
        print_banner(ctx.endpoint.base_url, "Help/Info")
        print_option("1", "What's New?")
        print_option("0", "Back")

        choice = read_menu_choice("Choose an option: ")
        if choice == "0":
            return
        if choice == "1":
            _tool_whats_new(ctx)
            continue

        warn("Unknown option.")
        pause()


def build_tool_plugins() -> List[ToolPlugin]:
    tools = [
        ToolPlugin("1", "Node", "Node status and admin controls", tool_node),
        ToolPlugin("2", "Chat", "Chat room + settings", tool_chat),
        ToolPlugin("3", "Groups", "Join, create, and accept invites", tool_groups),
        ToolPlugin("4", "Register Name", "Register a Qortal name", tool_register_name),
    ]
    if ENABLE_WALLET_TOOL:
        tools.append(ToolPlugin("5", "Wallet", "Balance and payments", tool_wallet))
    tools.append(
        ToolPlugin(
            "6",
            "QDN Resources",
            "Publish APPs or delete arbitrary resources",
            tool_qdn_resources,
        )
    )
    tools.append(
        ToolPlugin(
            "8",
            "Help/Info",
            "Documentation and changelog",
            tool_help_info,
        )
    )
    return tools
