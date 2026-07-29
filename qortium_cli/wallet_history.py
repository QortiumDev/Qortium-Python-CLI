"""Public wallet details and normalized transaction history."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from qortium_cli.foreign_wallets import derive_foreign_wallet
from qortium_cli.models import AppContext
from qortium_cli.qortal_bridge import fetch_qortal_json
from qortium_cli.utils import pretty_exception
from qortium_cli.wallet_portfolio import WalletBalance


@dataclass(frozen=True)
class WalletAddressInfo:
    address: str
    path: str = ""
    balance: Decimal | None = None
    transaction_count: int = 0
    spendable: bool = False


@dataclass(frozen=True)
class WalletPublicInfo:
    ticker: str
    display_name: str
    network: str
    primary_address: str
    xpub: str = ""
    addresses: tuple[WalletAddressInfo, ...] = ()
    error: str = ""


@dataclass(frozen=True)
class WalletTransaction:
    ticker: str
    timestamp: int | None
    tx_hash: str
    amount: Decimal
    fee: Decimal | None = None
    sender: str = ""
    recipient: str = ""
    inputs: tuple[WalletAddressInfo, ...] = ()
    outputs: tuple[WalletAddressInfo, ...] = ()

    @property
    def direction(self) -> str:
        return "received" if self.amount > 0 else "sent"


@dataclass(frozen=True)
class WalletHistory:
    transactions: tuple[WalletTransaction, ...]
    errors: dict[str, str]


def _decimal(value: object, default: Decimal = Decimal("0")) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return default
    return parsed if parsed.is_finite() else default


def _atomic(value: object, decimal_places: int) -> Decimal:
    return _decimal(value) / (Decimal(10) ** decimal_places)


def _foreign_address_rows(
    payload: object,
    decimal_places: int,
) -> tuple[WalletAddressInfo, ...]:
    if not isinstance(payload, list):
        return ()
    rows: list[WalletAddressInfo] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        address = str(item.get("address") or "").strip()
        if not address:
            continue
        rows.append(
            WalletAddressInfo(
                address=address,
                path=str(item.get("pathAsString") or "").strip(),
                balance=_atomic(item.get("value", 0), decimal_places),
                transaction_count=int(item.get("transactionCount") or 0),
                spendable=item.get("isSpendable") is True,
            )
        )
    return tuple(rows)


def load_wallet_public_info(
    ctx: AppContext,
    wallet: WalletBalance,
) -> WalletPublicInfo:
    if wallet.ticker == "QORT":
        return WalletPublicInfo(
            ticker="QORT",
            display_name="Qortal",
            network=wallet.active_network,
            primary_address=ctx.account.account_address,
            addresses=(
                WalletAddressInfo(
                    address=ctx.account.account_address,
                    balance=wallet.balance,
                    spendable=True,
                ),
            ),
        )

    from qortium_cli.services import build_api_url, make_session

    try:
        derived = derive_foreign_wallet(ctx.account.private_key, wallet.ticker)
        with make_session(ctx, include_api_key=True) as session:
            response = session.post(
                build_api_url(
                    ctx,
                    f"/crosschain/{wallet.ticker.lower()}/addressinfos",
                ),
                json={"xpub58": derived.xpub58},
                timeout=max(ctx.endpoint.timeout_seconds, 60),
            )
            response.raise_for_status()
            payload = response.json()
        addresses = _foreign_address_rows(payload, wallet.decimal_places)
        if not addresses:
            addresses = (
                WalletAddressInfo(
                    address=derived.address,
                    balance=wallet.balance,
                    spendable=True,
                ),
            )
        return WalletPublicInfo(
            ticker=wallet.ticker,
            display_name=wallet.display_name,
            network=wallet.active_network,
            primary_address=derived.address,
            xpub=derived.xpub58,
            addresses=addresses,
        )
    except Exception as exc:
        return WalletPublicInfo(
            ticker=wallet.ticker,
            display_name=wallet.display_name,
            network=wallet.active_network,
            primary_address=wallet.address,
            error=pretty_exception(exc),
        )


def _qort_history(ctx: AppContext, limit: int) -> tuple[WalletTransaction, ...]:
    result = fetch_qortal_json(
        "/transactions/search",
        ctx.endpoint.timeout_seconds,
        params={
            "txType": "PAYMENT",
            "address": ctx.account.account_address,
            "confirmationStatus": "CONFIRMED",
            "limit": max(1, min(int(limit), 100)),
            "reverse": "true",
        },
    )
    if not isinstance(result.payload, list):
        return ()

    rows: list[WalletTransaction] = []
    for item in result.payload:
        if not isinstance(item, dict):
            continue
        recipient = str(item.get("recipient") or "")
        incoming = recipient == ctx.account.account_address
        amount = _decimal(item.get("amount"))
        rows.append(
            WalletTransaction(
                ticker="QORT",
                timestamp=(
                    int(item["timestamp"])
                    if isinstance(item.get("timestamp"), (int, float))
                    else None
                ),
                tx_hash=str(item.get("signature") or ""),
                amount=amount if incoming else -amount,
                fee=_decimal(item.get("fee")),
                sender=(
                    str(item.get("creatorAddress") or "")
                    if incoming
                    else ctx.account.account_address
                ),
                recipient=recipient,
            )
        )
    return tuple(rows)


def _io_rows(payload: object, decimal_places: int) -> tuple[WalletAddressInfo, ...]:
    if not isinstance(payload, list):
        return ()
    rows: list[WalletAddressInfo] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        rows.append(
            WalletAddressInfo(
                address=str(item.get("address") or ""),
                balance=_atomic(item.get("amount", 0), decimal_places),
                spendable=item.get("addressInWallet") is True,
            )
        )
    return tuple(rows)


def _foreign_history(
    ctx: AppContext,
    wallet: WalletBalance,
) -> tuple[WalletTransaction, ...]:
    from qortium_cli.services import build_api_url, make_session

    derived = derive_foreign_wallet(ctx.account.private_key, wallet.ticker)
    with make_session(ctx, include_api_key=True) as session:
        response = session.post(
            build_api_url(
                ctx,
                f"/crosschain/{wallet.ticker.lower()}/wallettransactions",
            ),
            data=derived.xpub58,
            headers={"Content-Type": "text/plain"},
            timeout=max(ctx.endpoint.timeout_seconds, 300),
        )
        response.raise_for_status()
        payload = response.json()
    if not isinstance(payload, list):
        return ()

    rows: list[WalletTransaction] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        inputs = _io_rows(item.get("inputs"), wallet.decimal_places)
        outputs = _io_rows(item.get("outputs"), wallet.decimal_places)
        sender = next((row.address for row in inputs if not row.spendable), "")
        recipient = next((row.address for row in outputs if not row.spendable), "")
        rows.append(
            WalletTransaction(
                ticker=wallet.ticker,
                timestamp=(
                    int(item["timestamp"])
                    if isinstance(item.get("timestamp"), (int, float))
                    else None
                ),
                tx_hash=str(item.get("txHash") or ""),
                amount=_atomic(item.get("totalAmount", 0), wallet.decimal_places),
                fee=_atomic(item.get("feeAmount", 0), wallet.decimal_places),
                sender=sender,
                recipient=recipient,
                inputs=inputs,
                outputs=outputs,
            )
        )
    return tuple(rows)


def load_wallet_history(
    ctx: AppContext,
    wallet: WalletBalance,
    *,
    limit: int = 20,
) -> tuple[WalletTransaction, ...]:
    rows = (
        _qort_history(ctx, limit)
        if wallet.ticker == "QORT"
        else _foreign_history(ctx, wallet)
    )
    return tuple(
        sorted(
            rows,
            key=lambda row: row.timestamp if row.timestamp is not None else 2**63,
            reverse=True,
        )[: max(1, int(limit))]
    )


def load_combined_history(
    ctx: AppContext,
    wallets: tuple[WalletBalance, ...],
    *,
    limit_per_wallet: int = 20,
) -> WalletHistory:
    transactions: list[WalletTransaction] = []
    errors: dict[str, str] = {}
    with ThreadPoolExecutor(
        max_workers=min(8, max(1, len(wallets))),
        thread_name_prefix="qortium-history",
    ) as executor:
        futures = {
            executor.submit(
                load_wallet_history,
                ctx,
                wallet,
                limit=limit_per_wallet,
            ): wallet.ticker
            for wallet in wallets
        }
        for future in as_completed(futures):
            ticker = futures[future]
            try:
                transactions.extend(future.result())
            except Exception as exc:
                errors[ticker] = pretty_exception(exc)

    transactions.sort(
        key=lambda row: row.timestamp if row.timestamp is not None else 2**63,
        reverse=True,
    )
    return WalletHistory(tuple(transactions), errors)
