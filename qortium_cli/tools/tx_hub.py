"""Guided builder for the transaction types supported by this CLI."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import requests

from qortium_cli.models import AppContext
from qortium_cli.ui import (
    pause,
    prompt_decimal,
    prompt_int,
    prompt_str,
    prompt_yes_no,
    read_menu_choice,
    warn,
)
from qortium_cli.ui.menu import MenuOption, render_header, render_options
from qortium_cli.ui.theme import console
from qortium_cli.ui.widgets import TxPipeline, error_panel, json_panel, ok_panel
from qortium_cli.utils import d8, pretty_exception
from qortium_cli.validators import is_placeholder, looks_like_qortal_address


@dataclass(frozen=True)
class Field:
    name: str
    label: str
    kind: str = "text"
    default: Any = ""
    minimum: Decimal | int | None = None
    maximum: Decimal | int | None = None
    optional: bool = False
    auto: str | None = None
    choices: tuple[str, ...] = ()


@dataclass(frozen=True)
class Transaction:
    key: str
    code: str
    label: str
    description: str
    category: str
    path: str
    fields: tuple[Field, ...]
    needs_pow: bool = True


TX_CATALOG: tuple[Transaction, ...] = (
    Transaction(
        "1",
        "JOIN_GROUP",
        "Join a group",
        "Request membership in an open group",
        "Groups",
        "/groups/join",
        (
            Field("joinerPublicKey", "Joiner public key", auto="public_key"),
            Field("groupId", "Group ID", "integer", 1, minimum=1),
        ),
    ),
    Transaction(
        "2",
        "LEAVE_GROUP",
        "Leave a group",
        "End this account's membership",
        "Groups",
        "/groups/leave",
        (
            Field("leaverPublicKey", "Leaver public key", auto="public_key"),
            Field("groupId", "Group ID", "integer", 1, minimum=1),
        ),
    ),
    Transaction(
        "3",
        "GROUP_INVITE",
        "Invite a group member",
        "Send an invitation as a group administrator",
        "Groups",
        "/groups/invite",
        (
            Field("adminPublicKey", "Administrator public key", auto="public_key"),
            Field("groupId", "Group ID", "integer", 1, minimum=1),
            Field("invitee", "Invitee address", "address"),
            Field("timeToLive", "Invitation lifetime in seconds (0 never expires)", "integer", 0, minimum=0),
        ),
    ),
    Transaction(
        "4",
        "CREATE_GROUP",
        "Create a group",
        "Create an open or invitation-only group",
        "Groups",
        "/groups/create",
        (
            Field("creatorPublicKey", "Creator public key", auto="public_key"),
            Field("groupName", "Group name"),
            Field("description", "Description"),
            Field("open", "Open group", "boolean", True),
            Field(
                "approvalThreshold",
                "Approval threshold",
                default="NONE",
                choices=("NONE", "ONE", "PCT20", "PCT40", "PCT60", "PCT80", "PCT100"),
            ),
            Field("minimumBlockDelay", "Minimum approval delay (blocks)", "integer", 0, minimum=0),
            Field("maximumBlockDelay", "Maximum approval delay (blocks)", "integer", 1440, minimum=1),
        ),
    ),
    Transaction(
        "1",
        "REGISTER_NAME",
        "Register a name",
        "Register a new name to this account",
        "Names",
        "/names/register",
        (
            Field("registrantPublicKey", "Registrant public key", auto="public_key"),
            Field("name", "Name"),
            Field("data", "Name data", default="{}"),
        ),
    ),
    Transaction(
        "2",
        "UPDATE_NAME",
        "Update a name",
        "Rename it, change its data, or both",
        "Names",
        "/names/update",
        (
            Field("ownerPublicKey", "Owner public key", auto="public_key"),
            Field("name", "Current name"),
            Field("newName", "New name (blank keeps current)", optional=True),
            Field("newData", "New data (blank keeps current)", optional=True),
        ),
    ),
    Transaction(
        "3",
        "SELL_NAME",
        "List a name for sale",
        "Set the requested sale price",
        "Names",
        "/names/sell",
        (
            Field("ownerPublicKey", "Owner public key", auto="public_key"),
            Field("name", "Name"),
            Field("salePrice", "Sale price (QORT)", "decimal", Decimal("1"), minimum=Decimal("0.00000001")),
        ),
    ),
    Transaction(
        "4",
        "CANCEL_SELL_NAME",
        "Cancel a name sale",
        "Remove an owned name from sale",
        "Names",
        "/names/sell/cancel",
        (
            Field("ownerPublicKey", "Owner public key", auto="public_key"),
            Field("name", "Name"),
        ),
    ),
    Transaction(
        "5",
        "BUY_NAME",
        "Buy a name",
        "Buy a listed name from its seller",
        "Names",
        "/names/buy",
        (
            Field("buyerPublicKey", "Buyer public key", auto="public_key"),
            Field("name", "Name"),
            Field("amount", "Listed price (QORT)", "decimal", Decimal("1"), minimum=Decimal("0.00000001")),
            Field("seller", "Seller address", "address"),
        ),
    ),
    Transaction(
        "1",
        "PAYMENT",
        "Send QORT",
        "Send a QORT payment to an address",
        "Payments",
        "/payments/pay",
        (
            Field("senderPublicKey", "Sender public key", auto="public_key"),
            Field("recipient", "Recipient address", "address"),
            Field("amount", "Amount (QORT)", "decimal", Decimal("1"), minimum=Decimal("0.00000001")),
        ),
        needs_pow=False,
    ),
)

CATEGORY_ORDER = ("Payments", "Groups", "Names")


def _auto_value(field: Field, ctx: AppContext) -> str | None:
    if field.auto == "public_key":
        from qortium_cli.crypto import to_base58_pubkey

        try:
            return to_base58_pubkey(ctx.account.public_key)
        except Exception:
            return None
    return None


def _prompt_field(field: Field, ctx: AppContext) -> Any:
    automatic = _auto_value(field, ctx)
    if automatic is not None:
        shortened = automatic if len(automatic) <= 36 else f"{automatic[:18]}…{automatic[-10:]}"
        console.print(f"[qort.dim]{field.label}:[/] [qort.accent]{shortened}[/] [dim](account)[/]")
        return automatic

    if field.kind == "boolean":
        return prompt_yes_no(field.label, default_yes=bool(field.default))

    if field.kind == "integer":
        return prompt_int(
            f"{field.label} [{field.default}]: ",
            default=int(field.default),
            minimum=int(field.minimum or 0),
        )

    if field.kind == "decimal":
        while True:
            value = prompt_decimal(
                f"{field.label} [{d8(Decimal(str(field.default)))}]: ",
                default=Decimal(str(field.default)),
            )
            if field.minimum is not None and value < Decimal(str(field.minimum)):
                warn(f"{field.label} must be at least {field.minimum}.")
                continue
            if field.maximum is not None and value > Decimal(str(field.maximum)):
                warn(f"{field.label} must not exceed {field.maximum}.")
                continue
            return d8(value)

    if field.kind == "address":
        while True:
            value = prompt_str(f"{field.label}: ").strip()
            if looks_like_qortal_address(value):
                return value
            warn("That does not look like a valid Qortium address.")

    while True:
        default = str(field.default)
        suffix = f" [{default}]" if default else ""
        value = prompt_str(f"{field.label}{suffix}: ", default).strip()
        if not value and not field.optional:
            warn(f"{field.label} cannot be blank.")
            continue
        if field.choices and value.upper() not in field.choices:
            warn(f"Choose one of: {', '.join(field.choices)}.")
            continue
        return value.upper() if field.choices else value


def _validate_payload(transaction: Transaction, payload: dict[str, Any]) -> None:
    if transaction.code == "CREATE_GROUP":
        if int(payload["maximumBlockDelay"]) < int(payload["minimumBlockDelay"]):
            raise ValueError("Maximum approval delay must be at least the minimum delay.")
    if transaction.code == "UPDATE_NAME":
        if not str(payload["newName"]).strip() and not str(payload["newData"]).strip():
            raise ValueError("Enter a new name, new data, or both.")


def _build_payload(transaction: Transaction, ctx: AppContext) -> dict[str, Any]:
    payload = {field.name: _prompt_field(field, ctx) for field in transaction.fields}
    _validate_payload(transaction, payload)
    return payload


def _is_insufficient_fee(exc: Exception) -> bool:
    return (
        isinstance(exc, requests.exceptions.HTTPError)
        and exc.response is not None
        and "INSUFFICIENT_FEE" in (exc.response.text or "").upper()
    )


def _extract_signature(result: Any) -> str:
    if isinstance(result, dict):
        for key in ("signature", "transactionSignature", "sig"):
            value = result.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    if isinstance(result, str):
        value = result.strip()
        if value and value.lower() not in {"true", "false"}:
            return value
    return ""


def _run_transaction(
    ctx: AppContext,
    transaction: Transaction,
    payload: dict[str, Any],
    fee: str,
    tx_group_id: int,
) -> None:
    from qortium_cli.services import (
        build_raw_transaction,
        compute_transaction_nonce,
        get_last_reference,
        get_recommended_fee,
        get_timestamp,
        make_session,
        process_tx,
        sign_tx,
    )

    with make_session(ctx, include_api_key=True) as session:
        reference = get_last_reference(ctx, ctx.account.account_address, session)
        full_payload = {
            "timestamp": get_timestamp(ctx, session),
            "reference": reference,
            "fee": fee,
            "txGroupId": tx_group_id,
            **payload,
        }

        fee_retried = False
        while True:
            with TxPipeline(transaction.code).run() as pipeline:
                pipeline.start(0)
                unsigned = build_raw_transaction(ctx, transaction.path, full_payload, session)
                pipeline.finish(0)

                pipeline.start(1)
                if transaction.needs_pow:
                    unsigned, _ = compute_transaction_nonce(ctx, unsigned, session)
                pipeline.finish(1)

                pipeline.start(2)
                signed = sign_tx(ctx, unsigned, session)
                pipeline.finish(2)

                pipeline.start(3)
                try:
                    result = process_tx(ctx, signed, session)
                except Exception as exc:
                    pipeline.finish(3, ok=False)
                    if fee_retried or not _is_insufficient_fee(exc):
                        raise
                    recommended = get_recommended_fee(ctx, unsigned, session)
                    if recommended <= Decimal(str(full_payload["fee"])):
                        raise
                    full_payload["fee"] = d8(recommended)
                    fee_retried = True
                    warn(f"Node requires a fee. Retrying with {d8(recommended)} QORT.")
                    continue
                pipeline.finish(3)
            break

    signature = _extract_signature(result)
    message = "Transaction submitted."
    if signature:
        message += f"\nSignature: {signature}"
    ok_panel(message)
    if ctx.debug:
        json_panel(result if isinstance(result, dict) else {"result": str(result)}, "Node response")


def _account_is_ready(ctx: AppContext) -> bool:
    return not any(
        is_placeholder(value)
        for value in (
            ctx.account.account_address,
            ctx.account.public_key,
            ctx.account.private_key,
            ctx.account.api_key,
        )
    )


def _choose_category(ctx: AppContext) -> str | None:
    render_header(
        ctx,
        "Guided Transaction Builder",
        "Home  >  Advanced Tools  >  Transactions",
    )
    console.print(
        "[#b9afd4]Advanced guided forms for supported transaction types. "
        "Everyday chat, group, name, and wallet tasks also have dedicated screens.[/]\n"
    )
    options = tuple(
        MenuOption(
            str(index),
            category,
            f"{sum(item.category == category for item in TX_CATALOG)} supported actions",
            lambda _: None,
        )
        for index, category in enumerate(CATEGORY_ORDER, start=1)
    )
    render_options(options, zero_description="Return to Advanced Tools")
    choice = read_menu_choice("\nChoose: ").strip()
    if choice == "0":
        return None
    try:
        index = int(choice) - 1
        if index < 0:
            raise IndexError
        return CATEGORY_ORDER[index]
    except (ValueError, IndexError):
        warn("That number is not available here.")
        pause()
        return ""


def _choose_transaction(ctx: AppContext, category: str) -> Transaction | None:
    transactions = tuple(item for item in TX_CATALOG if item.category == category)
    render_header(
        ctx,
        f"{category} Transactions",
        f"Home  >  Advanced Tools  >  Transactions  >  {category}",
    )
    options = tuple(
        MenuOption(item.key, item.label, f"{item.description} · {item.code}", lambda _: None)
        for item in transactions
    )
    render_options(options, zero_description="Return to transaction categories")
    choice = read_menu_choice("\nChoose: ").strip()
    if choice == "0":
        return None
    selected = next((item for item in transactions if item.key == choice), None)
    if selected is None:
        warn("That number is not available here.")
        pause()
    return selected


def tool_tx_hub(ctx: AppContext) -> None:
    if not _account_is_ready(ctx):
        error_panel(
            "The active account is not ready to sign transactions.",
            hint="Open Settings from the main menu and configure the account and node API key.",
        )
        pause()
        return

    while True:
        category = _choose_category(ctx)
        if category is None:
            return
        if not category:
            continue

        transaction = _choose_transaction(ctx, category)
        if transaction is None:
            continue

        render_header(
            ctx,
            transaction.label,
            f"Home  >  Advanced Tools  >  Transactions  >  {category}  >  {transaction.label}",
        )
        console.print(f"[qort.dim]{transaction.description}[/]")
        console.print(f"[qort.dim]Core builder: POST {transaction.path}[/]\n")

        try:
            payload = _build_payload(transaction, ctx)
            fee = d8(prompt_decimal("Fee [0.00000000]: ", default=Decimal("0")))
            tx_group_id = prompt_int("Transaction group ID [0]: ", default=0, minimum=0)
        except (KeyboardInterrupt, ValueError) as exc:
            warn(str(exc) or "Transaction cancelled.")
            pause()
            continue

        preview = {
            "type": transaction.code,
            "endpoint": transaction.path,
            **payload,
            "fee": fee,
            "txGroupId": tx_group_id,
        }
        console.print()
        json_panel(preview, "Review transaction")
        if not prompt_yes_no("\nSign and submit this transaction?", default_yes=False):
            warn("Transaction cancelled.")
            pause()
            continue

        try:
            _run_transaction(ctx, transaction, payload, fee, tx_group_id)
        except KeyboardInterrupt:
            warn("Transaction cancelled.")
        except Exception as exc:
            error_panel(
                pretty_exception(exc),
                hint="No transaction was reported as submitted. Check the account, node, and entered values.",
            )
        pause()
