"""Qortal QORT and Qortium-supported external wallet workflows."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
from urllib.parse import quote

from rich import box
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table

from qortium_cli.models import AppContext
from qortium_cli.ui import data_table, pause, prompt_secret, read_menu_choice, warn
from qortium_cli.ui.menu import MenuOption, render_header, render_options
from qortium_cli.ui.theme import console
from qortium_cli.ui.widgets import error_panel, spinner
from qortium_cli.utils import pretty_exception
from qortium_cli.wallet_history import (
    WalletPublicInfo,
    WalletTransaction,
    load_combined_history,
    load_wallet_history,
    load_wallet_public_info,
)
from qortium_cli.wallet_preferences import (
    FIAT_CURRENCIES,
    SORT_MODES,
    WalletPreferences,
    load_wallet_preferences,
    write_wallet_preferences,
)
from qortium_cli.wallet_portfolio import WalletBalance, WalletPortfolio


def _qortium_asset_balances(ctx: AppContext) -> None:
    from qortium_cli.tools import check_balances

    check_balances(ctx)
    pause()


def _wallet_backup(ctx: AppContext) -> None:
    from qortium_cli.tools import export_wallet_backup

    export_wallet_backup(ctx)
    pause()


def _refresh(_: AppContext) -> None:
    """Return to the wallet workspace loop, which reloads live balances."""


def _external_wallets(ctx: AppContext) -> None:
    networks = _supported_wallet_networks(ctx)

    rows: list[list[str]] = [
        ["Qortal", "QORT", "MAIN", "Separate Qortal bridge"],
    ]
    for network in networks:
        rows.append(
            [
                str(network.get("displayName") or network.get("name") or "Unknown"),
                str(network.get("currencyCode") or "—"),
                str(network.get("activeNetwork") or "—"),
                "Enabled" if network.get("walletEnabled") else "Available",
            ]
        )
    if rows:
        console.print(data_table(["Network", "Code", "Chain", "Node status"], rows))
    else:
        console.print("[qort.muted]This node did not report any external wallet networks.[/]")
    console.print(
        "\n[qort.dim]External wallet secrets are requested only for the operation that needs them; "
        "they are not added to the CLI configuration.[/]"
    )
    pause()


def _supported_wallet_networks(ctx: AppContext) -> list[dict]:
    from qortium_cli.services import make_session, request_json

    with spinner("Loading supported wallet networks..."):
        with make_session(ctx, include_api_key=False) as session:
            payload = request_json(ctx, session, "GET", "/crosschain/blockchains")
    if not isinstance(payload, list):
        return []
    return [
        item
        for item in payload
        if isinstance(item, dict) and item.get("supportsWallet")
    ]


def _external_wallet_balance(ctx: AppContext) -> None:
    from qortium_cli.services import build_api_url, make_session

    networks = _supported_wallet_networks(ctx)
    if not networks:
        warn("This node did not report any external wallet networks.")
        pause()
        return

    print()
    for index, network in enumerate(networks, start=1):
        name = network.get("displayName") or network.get("name") or "Unknown"
        code = network.get("currencyCode") or "?"
        state = "enabled" if network.get("walletEnabled") else "disabled"
        print(f"{index}) {name} ({code}) — {state}")
    print("0) Cancel")
    raw_choice = read_menu_choice("Network: ")
    if raw_choice == "0":
        return
    try:
        selected = networks[int(raw_choice) - 1]
    except (ValueError, IndexError):
        warn("Unknown network.")
        pause()
        return
    if not selected.get("walletEnabled"):
        warn("That wallet network is disabled in this node's settings.")
        pause()
        return

    key = prompt_secret("Extended public/private wallet key: ")
    if not key:
        warn("Balance lookup cancelled.")
        return

    blockchain = str(selected.get("name") or "").strip().upper()
    with spinner(f"Checking {blockchain} wallet balance..."):
        with make_session(ctx, include_api_key=True) as session:
            response = session.post(
                build_api_url(
                    ctx,
                    f"/crosschain/{quote(blockchain, safe='')}/walletbalance",
                ),
                data=key,
                headers={"Content-Type": "text/plain"},
                timeout=max(ctx.endpoint.timeout_seconds, 60),
            )
            response.raise_for_status()
            atomic = int((response.text or "0").strip().strip('"'))

    decimals = int(selected.get("decimalPlaces") or 8)
    amount = Decimal(atomic) / (Decimal(10) ** decimals)
    code = str(selected.get("currencyCode") or blockchain)
    console.print(f"\n[bold green]{amount:,.{decimals}f} {code}[/]")
    console.print("[qort.dim]The wallet key was used for this request only and was not saved.[/]")
    pause()


def wallet_actions() -> tuple[MenuOption, ...]:
    return (
        MenuOption(
            "20",
            "All transactions",
            "Combined Qortal and external-wallet history",
            _refresh,
        ),
        MenuOption(
            "21",
            "Sort & display",
            "Ordering, fiat currency, and zero-balance visibility",
            _refresh,
        ),
        MenuOption(
            "22",
            "Copy all addresses",
            "Copy one labeled address list to the clipboard",
            _refresh,
        ),
        MenuOption(
            "23",
            "Refresh everything",
            "Balances, enabled networks, and market prices",
            _refresh,
        ),
        MenuOption(
            "24",
            "Qortium assets",
            "Inspect non-coin assets held by this account",
            _qortium_asset_balances,
        ),
        MenuOption(
            "25",
            "Network details",
            "Inspect the Qortal bridge and Core wallet networks",
            _external_wallets,
        ),
        MenuOption(
            "26",
            "Back up account",
            "Create an encrypted Qortium Home-compatible account backup",
            _wallet_backup,
        ),
    )


def _load_portfolio(
    ctx: AppContext,
    *,
    force_market: bool = False,
) -> WalletPortfolio:
    from qortium_cli.wallet_portfolio import load_wallet_portfolio

    with spinner("Loading wallets, balances, and market prices..."):
        return load_wallet_portfolio(ctx, force_market=force_market)


def _balance_text(wallet: WalletBalance) -> str:
    if wallet.balance is None:
        return "[bold red]UNAVAILABLE[/]"
    amount = f"{wallet.balance:,.{wallet.decimal_places}f}"
    style = "bold green" if wallet.balance else "dim"
    return f"[{style}]{amount}[/]"


def _format_fiat(value: Decimal | None, currency: str) -> str:
    if value is None:
        return "—"
    code = currency.upper()
    symbols = {
        "USD": "$",
        "EUR": "€",
        "GBP": "£",
        "JPY": "¥",
        "CNY": "¥",
        "KRW": "₩",
        "INR": "₹",
    }
    decimals = 0 if code in {"JPY", "KRW"} else 2
    prefix = symbols.get(code, f"{code} ")
    return f"{prefix}{value:,.{decimals}f}"


def _portfolio_panel(portfolio: WalletPortfolio) -> Panel:
    compact = console.width < 72
    wide = console.width >= 106
    table = Table(
        box=None,
        expand=True,
        show_header=True,
        header_style="bold #c9a7ff",
        padding=(0, 1),
    )
    table.add_column("#", style="bold yellow", no_wrap=True, width=3)
    table.add_column("COIN", style="bold #5ee7ff", no_wrap=True, width=7)
    if wide:
        table.add_column("WALLET", style="white", ratio=2)
    table.add_column("BALANCE", justify="right", ratio=2, no_wrap=True)
    if wide:
        table.add_column("PRICE", justify="right", no_wrap=True)
    table.add_column("VALUE", justify="right", no_wrap=True)
    if not compact:
        table.add_column("24H", justify="right", no_wrap=True)

    for index, wallet in enumerate(portfolio.balances, start=1):
        row = [str(index), escape(wallet.ticker)]
        if wide:
            row.append(escape(wallet.display_name))
        row.append(_balance_text(wallet))
        if wide:
            row.append(_format_fiat(wallet.unit_price, portfolio.currency))
        row.append(_format_fiat(wallet.fiat_value, portfolio.currency))
        if not compact:
            change = wallet.change_24h
            if change is None:
                row.append("—")
            else:
                style = "green" if change >= 0 else "red"
                arrow = "▲" if change >= 0 else "▼"
                row.append(f"[{style}]{arrow}{abs(change):.2f}%[/]")
        table.add_row(*row)

    notes: list[str] = []
    if portfolio.discovery_error:
        notes.append(
            "[amber1]Qortium wallet discovery is unavailable; "
            "Qortal QORT is checked separately.[/]"
        )
    failed = sum(
        1
        for wallet in (portfolio.all_balances or portfolio.balances)
        if wallet.error
    )
    if failed:
        noun = "balance" if failed == 1 else "balances"
        notes.append(
            f"[amber1]{failed} {noun} could not be loaded from wallet services.[/]"
        )
    if portfolio.market_error:
        state = "stale prices shown" if portfolio.market_stale else "fiat values unavailable"
        notes.append(f"[amber1]Market data issue; {state}.[/]")
    if notes:
        table.add_section()
        table.add_row(*([f"{' '.join(notes)}"] + [""] * (len(table.columns) - 1)))

    return Panel(
        table,
        title="[bold #5ee7ff] WALLET BALANCES [/]",
        subtitle=(
            f"[dim] {len(portfolio.balances)} shown · "
            f"total {_format_fiat(portfolio.total_fiat, portfolio.currency)} [/]"
        ),
        box=box.SQUARE,
        border_style="#376c78",
    )


def _identity_panel(ctx: AppContext) -> Panel:
    grid = Table.grid(padding=(0, 2), expand=True)
    grid.add_column(style="#8f86a4", no_wrap=True)
    grid.add_column(style="white", overflow="fold")
    grid.add_row("ACCOUNT", escape(ctx.account.name or "Unnamed"))
    grid.add_row("ADDRESS", escape(ctx.account.account_address))
    grid.add_row("SOURCE", "[bold green]CURRENT CLI LOGIN[/]")
    grid.add_row(
        "PRIVACY",
        "QORT uses a Qortal node; foreign balances use xpubs. Private keys stay local.",
    )
    return Panel(
        grid,
        title="[bold #c9a7ff] ACTIVE WALLET IDENTITY [/]",
        box=box.SQUARE,
        border_style="#604b82",
    )


def render_wallet_hub(
    ctx: AppContext,
    portfolio: WalletPortfolio,
    options: tuple[MenuOption, ...] | None = None,
) -> None:
    render_header(ctx, "Wallets & Payments", "Home  >  Wallets & Payments")
    console.print(_identity_panel(ctx))
    console.print(_portfolio_panel(portfolio))
    console.print(
        "[qort.dim]Choose a wallet number for its address, public information, "
        "and transaction history.[/]\n"
    )
    console.print("[bold #8d6bff] WALLET & PAYMENT ACTIONS [/]\n")
    render_options(options or wallet_actions())


def _primary_address(ctx: AppContext, wallet: WalletBalance) -> str:
    if wallet.address:
        return wallet.address
    if wallet.ticker == "QORT":
        return ctx.account.account_address
    from qortium_cli.foreign_wallets import derive_foreign_wallet

    return derive_foreign_wallet(ctx.account.private_key, wallet.ticker).address


def _copy_or_print(value: str, label: str) -> None:
    from qortium_cli.clipboard import copy_text

    if copy_text(value):
        console.print(f"\n[bold green]✓ {escape(label)} copied to the clipboard.[/]")
    else:
        console.print(
            "\n[amber1]Clipboard integration is unavailable in this terminal. "
            "Copy the value below:[/]"
        )
        console.print(Panel(escape(value), border_style="#604b82"))
    pause()


def _copy_all_addresses(ctx: AppContext, portfolio: WalletPortfolio) -> None:
    lines: list[str] = []
    for wallet in portfolio.all_balances or portfolio.balances:
        try:
            address = _primary_address(ctx, wallet)
        except Exception:
            continue
        if address:
            lines.append(f"{wallet.ticker} - {address}")
    if not lines:
        warn("No wallet addresses are available to copy.")
        pause()
        return
    _copy_or_print("\n".join(lines), "Wallet addresses")


def _public_info_text(info: WalletPublicInfo) -> str:
    lines = [
        f"Ticker: {info.ticker}",
        f"Wallet: {info.display_name}",
        f"Network: {info.network}",
        f"Primary address: {info.primary_address}",
    ]
    if info.xpub:
        lines.append(f"Extended public key: {info.xpub}")
    for index, row in enumerate(info.addresses, start=1):
        fields = [f"Address {index}: {row.address}"]
        if row.path:
            fields.append(f"path {row.path}")
        if row.balance is not None:
            fields.append(f"balance {row.balance}")
        fields.append(f"transactions {row.transaction_count}")
        lines.append(" | ".join(fields))
    return "\n".join(lines)


def _show_wallet_info(ctx: AppContext, wallet: WalletBalance) -> None:
    with spinner(f"Loading {wallet.ticker} public wallet information..."):
        info = load_wallet_public_info(ctx, wallet)

    while True:
        render_header(
            ctx,
            f"{wallet.ticker} Public Wallet Information",
            f"Wallets  >  {wallet.ticker}  >  Public information",
        )
        grid = Table.grid(padding=(0, 2), expand=True)
        grid.add_column(style="#8f86a4", no_wrap=True)
        grid.add_column(style="white", overflow="fold")
        grid.add_row("WALLET", escape(info.display_name))
        grid.add_row("TICKER", escape(info.ticker))
        grid.add_row("NETWORK", escape(info.network))
        grid.add_row("PRIMARY", escape(info.primary_address or "Unavailable"))
        if info.xpub:
            grid.add_row("XPUB", escape(info.xpub))
        console.print(
            Panel(
                grid,
                title="[bold #5ee7ff] PUBLIC WALLET DATA [/]",
                subtitle="[dim] No private keys are displayed or copied [/]",
                box=box.SQUARE,
                border_style="#376c78",
            )
        )
        if info.error:
            console.print(f"[amber1]{escape(info.error)}[/]\n")
        if info.addresses:
            rows = Table(
                "#",
                "ADDRESS",
                "PATH",
                "BALANCE",
                "TXS",
                box=box.SIMPLE,
                expand=True,
            )
            for index, address in enumerate(info.addresses[:50], start=1):
                rows.add_row(
                    str(index),
                    escape(address.address),
                    escape(address.path or "—"),
                    (
                        f"{address.balance:,.{wallet.decimal_places}f}"
                        if address.balance is not None
                        else "—"
                    ),
                    str(address.transaction_count),
                )
            console.print(rows)
        console.print("\n[bold yellow]1)[/] Copy primary address")
        if info.xpub:
            console.print("[bold yellow]2)[/] Copy extended public key")
        console.print("[bold yellow]3)[/] Copy all public wallet information")
        console.print("[bold yellow]0)[/] Back")
        choice = read_menu_choice("\nChoose: ")
        if choice == "0":
            return
        if choice == "1" and info.primary_address:
            _copy_or_print(info.primary_address, f"{info.ticker} address")
        elif choice == "2" and info.xpub:
            _copy_or_print(info.xpub, f"{info.ticker} extended public key")
        elif choice == "3":
            _copy_or_print(_public_info_text(info), f"{info.ticker} public information")
        else:
            warn("That number is not available here.")
            pause()


def _relative_time(timestamp: int | None) -> str:
    if timestamp is None:
        return "unconfirmed"
    seconds = max(
        0,
        int(
            datetime.now(timezone.utc).timestamp()
            - datetime.fromtimestamp(timestamp / 1000, timezone.utc).timestamp()
        ),
    )
    if seconds < 60:
        return f"{seconds}s ago"
    if seconds < 3600:
        return f"{seconds // 60}m ago"
    if seconds < 86400:
        return f"{seconds // 3600}h ago"
    return f"{seconds // 86400}d ago"


def _counterparty(transaction: WalletTransaction) -> str:
    return (
        transaction.sender
        if transaction.direction == "received"
        else transaction.recipient
    )


def _short(value: str, maximum: int = 18) -> str:
    if len(value) <= maximum:
        return value or "—"
    return f"{value[:8]}…{value[-6:]}"


def _transaction_detail(
    ctx: AppContext,
    transaction: WalletTransaction,
) -> None:
    while True:
        render_header(
            ctx,
            f"{transaction.ticker} Transaction",
            "Wallets  >  Transactions  >  Detail",
        )
        table = Table.grid(padding=(0, 2), expand=True)
        table.add_column(style="#8f86a4", no_wrap=True)
        table.add_column(style="white", overflow="fold")
        table.add_row("DIRECTION", transaction.direction.upper())
        table.add_row("AMOUNT", f"{transaction.amount:+f} {transaction.ticker}")
        if transaction.fee is not None:
            table.add_row("FEE", f"{transaction.fee:f} {transaction.ticker}")
        table.add_row(
            "DATE",
            (
                datetime.fromtimestamp(
                    transaction.timestamp / 1000,
                    timezone.utc,
                ).astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
                if transaction.timestamp is not None
                else "Unconfirmed"
            ),
        )
        table.add_row("FROM", escape(transaction.sender or "—"))
        table.add_row("TO", escape(transaction.recipient or "—"))
        table.add_row("HASH", escape(transaction.tx_hash or "—"))
        console.print(Panel(table, box=box.SQUARE, border_style="#376c78"))
        if transaction.inputs or transaction.outputs:
            for label, rows in (
                ("INPUTS", transaction.inputs),
                ("OUTPUTS", transaction.outputs),
            ):
                if not rows:
                    continue
                io_table = Table(
                    "ADDRESS",
                    "AMOUNT",
                    "OWNER",
                    box=box.SIMPLE,
                    expand=True,
                    header_style="bold #c9a7ff",
                )
                for row in rows:
                    io_table.add_row(
                        escape(row.address or "—"),
                        (
                            f"{row.balance:f} {transaction.ticker}"
                            if row.balance is not None
                            else "—"
                        ),
                        "THIS WALLET" if row.spendable else "EXTERNAL",
                    )
                console.print(
                    Panel(
                        io_table,
                        title=f"[bold #5ee7ff] {label} [/]",
                        box=box.SQUARE,
                        border_style="#376c78",
                    )
                )
        console.print("[bold yellow]1)[/] Copy transaction hash")
        if _counterparty(transaction):
            console.print("[bold yellow]2)[/] Copy counterparty address")
        console.print("[bold yellow]0)[/] Back")
        choice = read_menu_choice("\nChoose: ")
        if choice == "0":
            return
        if choice == "1" and transaction.tx_hash:
            _copy_or_print(transaction.tx_hash, "Transaction hash")
        elif choice == "2" and _counterparty(transaction):
            _copy_or_print(_counterparty(transaction), "Counterparty address")
        else:
            warn("That number is not available here.")
            pause()


def _history_workspace(
    ctx: AppContext,
    wallets: tuple[WalletBalance, ...],
    *,
    combined: bool,
) -> None:
    def load() -> tuple[tuple[WalletTransaction, ...], dict[str, str]]:
        label = "combined transaction history" if combined else f"{wallets[0].ticker} history"
        with spinner(f"Loading {label}..."):
            if combined:
                history = load_combined_history(ctx, wallets)
                return history.transactions, history.errors
            return load_wallet_history(ctx, wallets[0]), {}

    try:
        transactions, errors = load()
    except Exception as exc:
        error_panel(
            pretty_exception(exc),
            hint="The wallet service may still be synchronizing. Try again shortly.",
        )
        pause()
        return

    active_filter = "all"
    page = 0
    page_size = 15
    while True:
        filtered = tuple(
            row
            for row in transactions
            if active_filter == "all" or row.direction == active_filter
        )
        page_count = max(1, (len(filtered) + page_size - 1) // page_size)
        page = max(0, min(page, page_count - 1))
        visible = filtered[page * page_size : (page + 1) * page_size]

        title = "All Transactions" if combined else f"{wallets[0].ticker} Transactions"
        render_header(ctx, title, f"Wallets  >  {title}")
        if errors:
            console.print(
                f"[amber1]Unavailable: {escape(', '.join(sorted(errors)))}[/]\n"
            )
        table = Table(
            "#",
            "WHEN",
            "COIN",
            "FLOW",
            "AMOUNT",
            "COUNTERPARTY",
            box=box.SIMPLE,
            expand=True,
            header_style="bold #c9a7ff",
        )
        for index, transaction in enumerate(visible, start=1):
            positive = transaction.amount > 0
            table.add_row(
                str(index),
                _relative_time(transaction.timestamp),
                transaction.ticker,
                "[green]IN[/]" if positive else "[red]OUT[/]",
                f"{transaction.amount:+f}",
                escape(_short(_counterparty(transaction))),
            )
        console.print(table)
        console.print(
            f"[qort.dim]{len(filtered)} matching transactions · "
            f"page {page + 1}/{page_count} · filter {active_filter}[/]\n"
        )
        console.print("[bold yellow]1-15)[/] Open transaction shown on this page")
        console.print("[bold yellow]90)[/] Previous page")
        console.print("[bold yellow]91)[/] Next page")
        console.print("[bold yellow]92)[/] Show all")
        console.print("[bold yellow]93)[/] Received only")
        console.print("[bold yellow]94)[/] Sent only")
        console.print("[bold yellow]95)[/] Refresh history")
        console.print("[bold yellow]0)[/] Back")
        choice = read_menu_choice("\nChoose: ")
        if choice == "0":
            return
        if choice == "90":
            page = max(0, page - 1)
        elif choice == "91":
            page = min(page_count - 1, page + 1)
        elif choice == "92":
            active_filter, page = "all", 0
        elif choice == "93":
            active_filter, page = "received", 0
        elif choice == "94":
            active_filter, page = "sent", 0
        elif choice == "95":
            try:
                transactions, errors = load()
                page = 0
            except Exception as exc:
                error_panel(pretty_exception(exc))
                pause()
        else:
            try:
                selected = visible[int(choice) - 1]
            except (ValueError, IndexError):
                warn("That number is not available here.")
                pause()
            else:
                _transaction_detail(ctx, selected)


def _wallet_detail(
    ctx: AppContext,
    wallet: WalletBalance,
    currency: str,
) -> bool:
    """Return True when the caller should reload the full portfolio."""

    while True:
        render_header(
            ctx,
            f"{wallet.display_name} Wallet",
            f"Wallets  >  {wallet.ticker}",
        )
        grid = Table.grid(padding=(0, 2), expand=True)
        grid.add_column(style="#8f86a4", no_wrap=True)
        grid.add_column(style="white", overflow="fold")
        grid.add_row("TICKER", wallet.ticker)
        grid.add_row("NETWORK", wallet.active_network)
        grid.add_row("ADDRESS", escape(_primary_address(ctx, wallet)))
        grid.add_row("BALANCE", _balance_text(wallet))
        grid.add_row("UNIT PRICE", _format_fiat(wallet.unit_price, currency))
        grid.add_row("FIAT VALUE", _format_fiat(wallet.fiat_value, currency))
        if wallet.change_24h is not None:
            grid.add_row("24H CHANGE", f"{wallet.change_24h:+.2f}%")
        console.print(
            Panel(
                grid,
                title=f"[bold #5ee7ff] {wallet.ticker} WALLET [/]",
                box=box.SQUARE,
                border_style="#376c78",
            )
        )
        console.print("[bold yellow]1)[/] Transaction history")
        console.print("[bold yellow]2)[/] Full public wallet information")
        console.print("[bold yellow]3)[/] Copy wallet address")
        console.print("[bold yellow]4)[/] Copy all public wallet information")
        console.print("[bold yellow]5)[/] Refresh portfolio")
        console.print("[bold yellow]0)[/] Back")
        choice = read_menu_choice("\nChoose: ")
        if choice == "0":
            return False
        if choice == "1":
            _history_workspace(ctx, (wallet,), combined=False)
        elif choice == "2":
            _show_wallet_info(ctx, wallet)
        elif choice == "3":
            _copy_or_print(_primary_address(ctx, wallet), f"{wallet.ticker} address")
        elif choice == "4":
            with spinner(f"Loading {wallet.ticker} public information..."):
                info = load_wallet_public_info(ctx, wallet)
            _copy_or_print(
                _public_info_text(info),
                f"{wallet.ticker} public wallet information",
            )
        elif choice == "5":
            return True
        else:
            warn("That number is not available here.")
            pause()


def _choose_currency(current: str) -> str:
    console.print("\n[bold #c9a7ff]FIAT CURRENCY[/]\n")
    for index, (code, label) in enumerate(FIAT_CURRENCIES, start=1):
        marker = "  ← current" if code == current else ""
        console.print(f"[bold yellow]{index})[/] {escape(label)}{marker}")
    raw = read_menu_choice("\nCurrency [0 cancels]: ")
    if raw == "0":
        return current
    try:
        return FIAT_CURRENCIES[int(raw) - 1][0]
    except (ValueError, IndexError):
        warn("Unknown currency.")
        pause()
        return current


def _configure_wallet_display(ctx: AppContext) -> bool:
    preferences = load_wallet_preferences(ctx.settings_dir)
    changed = False
    while True:
        render_header(
            ctx,
            "Wallet Sort & Display",
            "Wallets  >  Sort & Display",
        )
        sort_label = dict(SORT_MODES).get(preferences.sort_mode, preferences.sort_mode)
        console.print(f"[qort.dim]Sort:[/] {escape(sort_label)}")
        console.print(f"[qort.dim]Fiat:[/] {preferences.currency.upper()}")
        console.print(
            f"[qort.dim]Zero balances:[/] "
            f"{'hidden' if preferences.hide_zero else 'shown'}\n"
        )
        console.print("[bold yellow]1)[/] Change wallet sorting")
        console.print("[bold yellow]2)[/] Change fiat currency")
        console.print("[bold yellow]3)[/] Toggle zero-balance wallets")
        console.print("[bold yellow]0)[/] Back")
        choice = read_menu_choice("\nChoose: ")
        if choice == "0":
            if changed:
                write_wallet_preferences(ctx.settings_dir, preferences)
            return changed
        if choice == "1":
            console.print()
            for index, (_, label) in enumerate(SORT_MODES, start=1):
                console.print(f"[bold yellow]{index})[/] {escape(label)}")
            selected = read_menu_choice("\nSort mode [0 cancels]: ")
            if selected != "0":
                try:
                    preferences = replace(
                        preferences,
                        sort_mode=SORT_MODES[int(selected) - 1][0],
                    )
                    changed = True
                except (ValueError, IndexError):
                    warn("Unknown sort mode.")
                    pause()
        elif choice == "2":
            currency = _choose_currency(preferences.currency)
            if currency != preferences.currency:
                preferences = replace(preferences, currency=currency)
                changed = True
        elif choice == "3":
            preferences = replace(preferences, hide_zero=not preferences.hide_zero)
            changed = True
        else:
            warn("That number is not available here.")
            pause()


def open_wallet_hub(ctx: AppContext) -> None:
    options = wallet_actions()
    portfolio = _load_portfolio(ctx)

    while True:
        render_wallet_hub(ctx, portfolio, options)
        choice = read_menu_choice("\nChoose: ").strip()
        if choice == "0":
            return

        try:
            selected_index = int(choice) - 1
        except ValueError:
            selected_index = -1

        if 0 <= selected_index < len(portfolio.balances):
            try:
                if _wallet_detail(
                    ctx,
                    portfolio.balances[selected_index],
                    portfolio.currency,
                ):
                    portfolio = _load_portfolio(ctx, force_market=True)
            except Exception as exc:
                error_panel(pretty_exception(exc))
                pause()
            continue

        try:
            if choice == "20":
                _history_workspace(
                    ctx,
                    portfolio.all_balances or portfolio.balances,
                    combined=True,
                )
            elif choice == "21":
                if _configure_wallet_display(ctx):
                    portfolio = _load_portfolio(ctx, force_market=True)
            elif choice == "22":
                _copy_all_addresses(ctx, portfolio)
            elif choice == "23":
                portfolio = _load_portfolio(ctx, force_market=True)
            elif choice == "24":
                _qortium_asset_balances(ctx)
                portfolio = _load_portfolio(ctx)
            elif choice == "25":
                _external_wallets(ctx)
            elif choice == "26":
                _wallet_backup(ctx)
            else:
                warn("That number is not available here.")
                pause()
        except KeyboardInterrupt:
            warn("Cancelled.")
            pause()
        except Exception as exc:
            error_panel(
                pretty_exception(exc),
                hint="Check the node connection and try again.",
            )
            pause()
