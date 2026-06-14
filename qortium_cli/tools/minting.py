"""Minting Manager — self-share setup, minting account management."""
from __future__ import annotations

from qortium_cli.models import AppContext
from qortium_cli.ui import (
    error,
    ok,
    pause,
    print_banner,
    prompt_str,
    prompt_yes_no,
    read_menu_choice,
    warn,
)
from qortium_cli.ui.banner import tool_header
from qortium_cli.ui.theme import console
from qortium_cli.ui.widgets import (
    TxPipeline,
    bool_str,
    error_panel,
    height_str,
    ok_panel,
    spinner,
    stat_table,
    warn_panel,
)
from qortium_cli.utils import pretty_exception
from qortium_cli.validators import is_placeholder


def _ensure_ready(ctx: AppContext) -> None:
    if is_placeholder(ctx.account.api_key):
        raise RuntimeError("API key is missing. Run reconfigure first.")
    if is_placeholder(ctx.account.private_key):
        raise RuntimeError("Private key is missing. Run reconfigure first.")


def _tool_minting_status(ctx: AppContext) -> None:
    from qortium_cli.services import make_session, request_text_or_json, fetch_node_snapshot

    tool_header("Minting Status", "◈")
    try:
        with spinner("Fetching node status..."):
            snapshot = fetch_node_snapshot(ctx)
        status = snapshot.get("status") or {}
        info = snapshot.get("info") or {}

        minting = bool(status.get("isMintingPossible", False))
        syncing = bool(status.get("isSynchronizing", False))

        rows = [
            ("Status", "[bold green]● MINTING[/]" if minting else "[bold red]○ NOT MINTING[/]"),
            ("Sync",   "[bold green]● Synced[/]" if not syncing else "[bold yellow]⟳ Syncing[/]"),
            ("Height", height_str(status.get("height", "?"))),
            ("Connections", str(status.get("numberOfConnections", "?"))),
            ("Build Version", str(info.get("buildVersion", "?"))),
        ]
        console.print(stat_table(rows))
    except Exception as exc:
        error_panel(pretty_exception(exc), title="Status Unavailable")
    pause()


def _tool_minting_accounts(ctx: AppContext) -> None:
    from qortium_cli.services import make_session, request_text_or_json
    from qortium_cli.ui.widgets import data_table

    tool_header("Loaded Minting Accounts", "◈")
    _ensure_ready(ctx)
    try:
        with spinner("Fetching minting accounts..."):
            with make_session(ctx, include_api_key=True) as session:
                accounts = request_text_or_json(ctx, session, "GET", "/admin/mintingaccounts")

        if not accounts:
            warn_panel("No minting accounts currently loaded.")
            pause()
            return

        if isinstance(accounts, list):
            rows = []
            for i, acct in enumerate(accounts, start=1):
                mint_addr = str(acct.get("mintingAccount", acct) if isinstance(acct, dict) else acct)
                recv_addr = str(acct.get("recipientAccount", "") if isinstance(acct, dict) else "")
                rows.append([str(i), mint_addr[:40] + ("…" if len(mint_addr) > 40 else ""), recv_addr[:30]])
            t = data_table(["#", "Minting Account", "Recipient"], rows)
            console.print(t)
        else:
            from qortium_cli.ui.widgets import json_panel
            json_panel(str(accounts), "Minting Accounts")
    except Exception as exc:
        error_panel(pretty_exception(exc), hint="Requires API key.")
    pause()


def _tool_minting_add_key(ctx: AppContext) -> None:
    from qortium_cli.services import make_session, request_text_or_json

    tool_header("Add Minting Key", "◈")
    _ensure_ready(ctx)
    minting_key = prompt_str("Minting private key (Base58): ").strip()
    if not minting_key:
        warn("Cancelled.")
        return

    if not prompt_yes_no("Load this minting key into the node?", default_yes=False):
        warn("Cancelled.")
        return

    try:
        with spinner("Adding minting key..."):
            with make_session(ctx, include_api_key=True) as session:
                result = session.post(
                    ctx.endpoint.base_url + "/admin/mintingaccounts",
                    data=minting_key.encode(),
                    headers={"Content-Type": "text/plain"},
                    timeout=ctx.endpoint.timeout_seconds,
                )
                result.raise_for_status()
        ok_panel("Minting key loaded successfully.")
    except Exception as exc:
        error_panel(pretty_exception(exc), hint="Check that the key is valid Base58.")
    pause()


def _tool_minting_setup_self_share(ctx: AppContext) -> None:
    from decimal import Decimal
    from qortium_cli.services import (
        make_session,
        request_text_or_json,
        build_raw_transaction,
        sign_tx,
        process_tx,
        get_timestamp,
    )
    from qortium_cli.crypto import to_base58_pubkey
    from qortium_cli.utils import d8

    tool_header("Self-Share Setup (Minting)", "◈")
    _ensure_ready(ctx)

    console.print("[qort.dim]This sets up a self-minting reward share (0%, self as recipient).[/]")
    console.print("[qort.dim]Required before your node can mint on your account.[/]\n")

    if not prompt_yes_no("Proceed with self-share setup?", default_yes=False):
        warn("Cancelled.")
        return

    try:
        sender_pub = to_base58_pubkey(ctx.account.public_key)

        # Step 1: Derive minting key pair
        with spinner("Deriving minting key pair..."):
            with make_session(ctx, include_api_key=True) as session:
                # POST /addresses/rewardsharekey
                resp = session.post(
                    ctx.endpoint.base_url + "/addresses/rewardsharekey",
                    json={
                        "mintingAccountPrivateKey": ctx.account.private_key,
                        "recipientAccountPublicKey": sender_pub,
                    },
                    timeout=ctx.endpoint.timeout_seconds,
                )
                resp.raise_for_status()
                minting_private_key = resp.text.strip().strip('"')

                # Derive minting public key
                pub_resp = session.post(
                    ctx.endpoint.base_url + "/utils/publickey",
                    data=minting_private_key.encode(),
                    headers={"Content-Type": "text/plain"},
                    timeout=ctx.endpoint.timeout_seconds,
                )
                pub_resp.raise_for_status()
                minting_public_key = pub_resp.text.strip().strip('"')

        console.print(f"\n[qort.dim]Minting public key:[/] [white]{minting_public_key[:40]}…[/]\n")

        # Step 2: Build + sign + process REWARD_SHARE (no PoW needed)
        with TxPipeline("REWARD_SHARE (self-share)").run() as pipeline:
            pipeline.start(0)
            with make_session(ctx, include_api_key=True) as session:
                timestamp = get_timestamp(ctx, session)
                payload = {
                    "timestamp": timestamp,
                    "fee": "0.00000000",
                    "txGroupId": 0,
                    "minterPublicKey": sender_pub,
                    "recipient": ctx.account.account_address,
                    "rewardSharePublicKey": minting_public_key,
                    "sharePercent": 0,
                }
                unsigned_tx = build_raw_transaction(ctx, "/addresses/rewardshare", payload, session)
            pipeline.finish(0)

            pipeline.start(1)
            # REWARD_SHARE does not need PoW — mark PoW as done immediately
            pipeline.finish(1)

            pipeline.start(2)
            with make_session(ctx, include_api_key=True) as session:
                signed_tx = sign_tx(ctx, unsigned_tx, session)
            pipeline.finish(2)

            pipeline.start(3)
            with make_session(ctx, include_api_key=True) as session:
                process_tx(ctx, signed_tx, session)
            pipeline.finish(3)

        ok_panel(
            "Self-share transaction submitted.\n"
            "Wait for confirmation (1-2 blocks), then load your minting key.",
            title="Reward Share Submitted",
        )

        if prompt_yes_no("\nLoad minting key now?", default_yes=True):
            with spinner("Loading minting key..."):
                with make_session(ctx, include_api_key=True) as session:
                    resp = session.post(
                        ctx.endpoint.base_url + "/admin/mintingaccounts",
                        data=minting_private_key.encode(),
                        headers={"Content-Type": "text/plain"},
                        timeout=ctx.endpoint.timeout_seconds,
                    )
                    resp.raise_for_status()
            ok_panel("Minting key loaded. Your node is now minting!")

    except Exception as exc:
        error_panel(pretty_exception(exc), hint="Check node connection and API key.")

    pause()


def tool_minting(ctx: AppContext) -> None:
    while True:
        print_banner(ctx.endpoint.base_url, "Minting Manager")
        tool_header("Minting Manager", "◈")
        console.print("[qort.key]1)[/] [white]Minting status[/]")
        console.print("[qort.key]2)[/] [white]View loaded minting accounts[/]")
        console.print("[qort.key]3)[/] [white]Set up self-share (new minting account)[/]")
        console.print("[qort.key]4)[/] [white]Add existing minting key[/]")
        console.print("[qort.key]0)[/] [dim]Back[/]")
        console.print()
        choice = read_menu_choice("").lower()

        if choice == "0":
            return
        if choice == "1":
            _tool_minting_status(ctx)
        elif choice == "2":
            _tool_minting_accounts(ctx)
        elif choice == "3":
            _tool_minting_setup_self_share(ctx)
        elif choice == "4":
            _tool_minting_add_key(ctx)
        else:
            warn("Unknown option.")
            pause()
