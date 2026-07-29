"""Automatic QORT and foreign-wallet discovery for the wallet workspace."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Any

from qortium_cli.foreign_wallets import (
    FOREIGN_WALLET_SPECS,
    SUPPORTED_FOREIGN_WALLET_CODES,
    derive_foreign_wallet,
)
from qortium_cli.models import AppContext
from qortium_cli.utils import pretty_exception


@dataclass(frozen=True)
class WalletNetwork:
    code: str
    display_name: str
    active_network: str
    decimal_places: int


@dataclass(frozen=True)
class WalletBalance:
    ticker: str
    display_name: str
    active_network: str
    decimal_places: int
    balance: Decimal | None = None
    address: str = ""
    error: str = ""
    unit_price: Decimal | None = None
    fiat_value: Decimal | None = None
    change_24h: Decimal | None = None


@dataclass(frozen=True)
class WalletPortfolio:
    balances: tuple[WalletBalance, ...]
    all_balances: tuple[WalletBalance, ...] = ()
    discovery_error: str = ""
    currency: str = "usd"
    total_fiat: Decimal | None = None
    market_error: str = ""
    market_stale: bool = False
    sort_mode: str = "default"
    hide_zero: bool = False


def parse_wallet_networks(payload: Any) -> list[WalletNetwork]:
    """Return enabled chains that Qortium Home can derive for this account."""

    if not isinstance(payload, list):
        return []

    by_code: dict[str, WalletNetwork] = {}
    for item in payload:
        if not isinstance(item, dict) or not item.get("walletEnabled"):
            continue
        code = str(item.get("currencyCode") or "").strip().upper()
        if code not in FOREIGN_WALLET_SPECS:
            continue
        try:
            decimals = int(item.get("decimalPlaces", 8))
        except (TypeError, ValueError):
            decimals = 8
        by_code[code] = WalletNetwork(
            code=code,
            display_name=str(
                item.get("displayName")
                or FOREIGN_WALLET_SPECS[code].display_name
            ).strip(),
            active_network=str(item.get("activeNetwork") or "MAIN").strip().upper(),
            decimal_places=max(0, min(decimals, 18)),
        )

    return [
        by_code[code]
        for code in SUPPORTED_FOREIGN_WALLET_CODES
        if code in by_code
    ]


def _qortal_qort_balance(ctx: AppContext) -> WalletBalance:
    from qortium_cli.qortal_bridge import fetch_qort_balance

    try:
        result = fetch_qort_balance(
            ctx.account.account_address,
            ctx.endpoint.timeout_seconds,
        )
        return WalletBalance(
            ticker="QORT",
            display_name="Qortal",
            active_network=f"QORTAL {result.node_source.upper()}",
            decimal_places=8,
            balance=result.amount,
            address=ctx.account.account_address,
        )
    except Exception as exc:
        return WalletBalance(
            ticker="QORT",
            display_name="Qortal",
            active_network="QORTAL",
            decimal_places=8,
            address=ctx.account.account_address,
            error=pretty_exception(exc),
        )


def _foreign_balance(ctx: AppContext, network: WalletNetwork) -> WalletBalance:
    from qortium_cli.services import build_api_url, make_session

    try:
        wallet = derive_foreign_wallet(ctx.account.private_key, network.code)
        with make_session(ctx, include_api_key=True) as session:
            response = session.post(
                build_api_url(
                    ctx,
                    f"/crosschain/{network.code.lower()}/walletbalance",
                ),
                data=wallet.xpub58,
                headers={"Content-Type": "text/plain"},
                timeout=max(ctx.endpoint.timeout_seconds, 30),
            )
            response.raise_for_status()
            atomic_balance = int((response.text or "0").strip().strip('"'))
        balance = Decimal(atomic_balance) / (Decimal(10) ** network.decimal_places)
        return WalletBalance(
            ticker=network.code,
            display_name=network.display_name,
            active_network=network.active_network,
            decimal_places=network.decimal_places,
            balance=balance,
            address=wallet.address,
        )
    except Exception as exc:
        return WalletBalance(
            ticker=network.code,
            display_name=network.display_name,
            active_network=network.active_network,
            decimal_places=network.decimal_places,
            error=pretty_exception(exc),
        )


def sort_wallet_balances(
    balances: tuple[WalletBalance, ...],
    sort_mode: str,
) -> tuple[WalletBalance, ...]:
    if sort_mode == "name-asc":
        return tuple(sorted(balances, key=lambda wallet: wallet.display_name.lower()))
    if sort_mode == "name-desc":
        return tuple(
            sorted(
                balances,
                key=lambda wallet: wallet.display_name.lower(),
                reverse=True,
            )
        )
    if sort_mode in {"value-asc", "value-desc"}:
        available = [wallet for wallet in balances if wallet.fiat_value is not None]
        unavailable = [wallet for wallet in balances if wallet.fiat_value is None]
        available.sort(
            key=lambda wallet: wallet.fiat_value or Decimal("0"),
            reverse=sort_mode == "value-desc",
        )
        return tuple((*available, *unavailable))
    return balances


def _add_market_values(
    balances: tuple[WalletBalance, ...],
    currency: str,
    *,
    force: bool,
    timeout_seconds: int,
) -> tuple[tuple[WalletBalance, ...], Decimal | None, str, bool]:
    from qortium_cli.market_prices import fetch_market_prices

    market = fetch_market_prices(
        (wallet.ticker for wallet in balances if wallet.ticker != "QORT"),
        currency,
        force=force,
        timeout_seconds=timeout_seconds,
    )
    enriched: list[WalletBalance] = []
    total = Decimal("0")
    has_total = False
    for wallet in balances:
        quote = market.quotes.get(wallet.ticker)
        fiat_value = (
            wallet.balance * quote.price
            if wallet.balance is not None and quote is not None
            else None
        )
        if fiat_value is not None:
            total += fiat_value
            has_total = True
        enriched.append(
            replace(
                wallet,
                unit_price=quote.price if quote else None,
                fiat_value=fiat_value,
                change_24h=quote.change_24h if quote else None,
            )
        )
    return (
        tuple(enriched),
        total if has_total else None,
        market.error,
        market.stale,
    )


def load_wallet_portfolio(
    ctx: AppContext,
    *,
    force_market: bool = False,
) -> WalletPortfolio:
    """Discover enabled Qortium wallets and load their balances concurrently."""

    from qortium_cli.services import make_session, request_json
    from qortium_cli.wallet_preferences import load_wallet_preferences

    qort = _qortal_qort_balance(ctx)
    preferences = load_wallet_preferences(ctx.settings_dir)
    try:
        with make_session(ctx, include_api_key=False) as session:
            payload = request_json(
                ctx,
                session,
                "GET",
                "/crosschain/blockchains",
            )
        networks = parse_wallet_networks(payload)
    except Exception as exc:
        return WalletPortfolio(
            balances=(qort,),
            all_balances=(qort,),
            discovery_error=pretty_exception(exc),
            currency=preferences.currency,
            sort_mode=preferences.sort_mode,
            hide_zero=preferences.hide_zero,
        )

    if not networks:
        return WalletPortfolio(
            balances=(qort,),
            all_balances=(qort,),
            currency=preferences.currency,
            sort_mode=preferences.sort_mode,
            hide_zero=preferences.hide_zero,
        )

    results: dict[str, WalletBalance] = {}
    worker_count = min(8, len(networks))
    with ThreadPoolExecutor(
        max_workers=worker_count,
        thread_name_prefix="qortium-wallet",
    ) as executor:
        futures = {
            executor.submit(_foreign_balance, ctx, network): network.code
            for network in networks
        }
        for future in as_completed(futures):
            code = futures[future]
            try:
                results[code] = future.result()
            except Exception as exc:
                network = next(item for item in networks if item.code == code)
                results[code] = WalletBalance(
                    ticker=network.code,
                    display_name=network.display_name,
                    active_network=network.active_network,
                    decimal_places=network.decimal_places,
                    error=pretty_exception(exc),
                )

    ordered = tuple(results[network.code] for network in networks)
    enriched, total, market_error, market_stale = _add_market_values(
        (qort, *ordered),
        preferences.currency,
        force=force_market,
        timeout_seconds=ctx.endpoint.timeout_seconds,
    )
    visible = tuple(
        wallet
        for wallet in enriched
        if not preferences.hide_zero
        or wallet.balance is None
        or wallet.balance != 0
    )
    return WalletPortfolio(
        balances=sort_wallet_balances(visible, preferences.sort_mode),
        all_balances=enriched,
        currency=preferences.currency,
        total_fiat=total,
        market_error=market_error,
        market_stale=market_stale,
        sort_mode=preferences.sort_mode,
        hide_zero=preferences.hide_zero,
    )
