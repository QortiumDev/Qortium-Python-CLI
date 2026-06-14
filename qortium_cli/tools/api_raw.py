"""Raw API Explorer — browse and call any Qortium node endpoint."""
from __future__ import annotations

import json as _json
from typing import Any, Dict, List, Tuple

from qortium_cli.models import AppContext
from qortium_cli.ui import (
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
    error_panel,
    json_panel,
    ok_panel,
    spinner,
    warn_panel,
)
from qortium_cli.utils import pretty_exception
from qortium_cli.validators import is_placeholder

# ---------------------------------------------------------------------------
# Endpoint catalog
# ---------------------------------------------------------------------------

# Each entry: (path_template, method, label, params, requires_key, is_write_tx)
# params: list of (name, description, auto)  — auto can be "address", "pubkey", or None
ENDPOINT_CATALOG: Dict[str, List[Tuple]] = {
    "Account": [
        ("GET", "/addresses/{address}", "Account data", [("address", "Qortium address", "address")], False, False),
        ("GET", "/addresses/balance/{address}", "QORT balance", [("address", "Qortium address", "address")], False, False),
        ("GET", "/addresses/convert/{pubkey}", "Pubkey → Address", [("pubkey", "Base58 public key", "pubkey")], False, False),
        ("GET", "/addresses/lastreference/{address}", "Last transaction reference", [("address", "Qortium address", "address")], True, False),
        ("GET", "/assets/balances?addresses={address}&includeZeroBalances=true", "All asset balances", [("address", "Qortium address", "address")], True, False),
    ],
    "Names": [
        ("GET", "/names/{name}", "Name info", [("name", "Registered name", None)], False, False),
        ("GET", "/names/primary/{address}", "Primary name for address", [("address", "Qortium address", "address")], False, False),
        ("GET", "/names/address/{address}", "Names owned by address", [("address", "Qortium address", "address")], False, False),
        ("GET", "/names/search?query={query}&limit=20", "Search names", [("query", "Search term", None)], False, False),
    ],
    "Groups": [
        ("GET", "/groups/{groupId}", "Group info", [("groupId", "Group ID (integer)", None)], False, False),
        ("GET", "/groups/members/{groupId}", "Group members", [("groupId", "Group ID", None)], False, False),
        ("GET", "/groups/invites/{address}", "Pending invites for address", [("address", "Qortium address", "address")], False, False),
        ("GET", "/groups/joinrequests/admin/{address}", "Join requests for groups you manage", [("address", "Qortium address", "address")], True, False),
        ("GET", "/groups?limit=20&offset=0", "List groups", [], False, False),
    ],
    "Blocks": [
        ("GET", "/blocks/last", "Last block", [], False, False),
        ("GET", "/blocks/byheight/{height}", "Block by height", [("height", "Block height (integer)", None)], False, False),
        ("GET", "/blocks/summaries?count=10", "Recent block summaries", [], False, False),
        ("GET", "/blocks/signature/{signature}/transactions", "Transactions in block", [("signature", "Block signature (Base58)", None)], False, False),
    ],
    "Transactions": [
        ("GET", "/transactions/unconfirmed?limit=20", "Unconfirmed transactions", [], False, False),
        ("GET", "/transactions/address/{address}?limit=20", "Transactions for address", [("address", "Qortium address", "address")], False, False),
        ("GET", "/transactions/search?txType={txType}&limit=20", "Search transactions by type", [("txType", "TX type (e.g. PAYMENT, CHAT, JOIN_GROUP)", None)], False, False),
        ("GET", "/utils/timestamp", "Current node timestamp (ms)", [], False, False),
    ],
    "Chat": [
        ("GET", "/chat/messages?txGroupId={groupId}&limit=20&reverse=true", "Chat messages in group", [("groupId", "Group ID", None)], False, False),
        ("GET", "/chat/messages?involving={address}&limit=20", "Chat messages involving address", [("address", "Qortium address", "address")], False, False),
    ],
    "QDN": [
        ("GET", "/arbitrary/resources/search?service={service}&query={query}&limit=20", "Search QDN resources", [("service", "Service type (e.g. APP)", None), ("query", "Search term", None)], False, False),
        ("GET", "/arbitrary/hosted/resources", "Locally hosted resources", [], True, False),
        ("GET", "/arbitrary/{service}/{name}", "Fetch QDN resource metadata", [("service", "Service type", None), ("name", "Resource name", None)], False, False),
    ],
    "Admin": [
        ("GET", "/admin/status", "Node sync status", [], True, False),
        ("GET", "/admin/info", "Node build info", [], True, False),
        ("GET", "/admin/mintingaccounts", "Loaded minting accounts", [], True, False),
        ("GET", "/peers/summary", "Peer summary", [], True, False),
        ("GET", "/stats/supply/circulating", "Circulating QORT supply", [], False, False),
    ],
}

_CATEGORIES = list(ENDPOINT_CATALOG.keys())


# ---------------------------------------------------------------------------
# Request helpers
# ---------------------------------------------------------------------------

def _fill_path(path_template: str, params: List[Tuple], ctx: AppContext) -> str | None:
    path = path_template
    for name, description, auto in params:
        if "{" + name + "}" not in path and "=" + "{" + name + "}" not in path:
            continue
        # Try auto-fill
        auto_val = None
        if auto == "address":
            addr = ctx.account.account_address
            auto_val = addr if not is_placeholder(addr) else None
        elif auto == "pubkey":
            from qortium_cli.crypto import to_base58_pubkey
            try:
                auto_val = to_base58_pubkey(ctx.account.public_key)
            except Exception:
                pass

        if auto_val:
            display = str(auto_val)[:30] + ("…" if len(str(auto_val)) > 30 else "")
            console.print(f"  [dim]{description}:[/] [qort.accent]{display}[/] [dim](auto)[/]")
            value = auto_val
        else:
            value = prompt_str(f"  {description}: ", "").strip()
            if not value:
                return None

        path = path.replace("{" + name + "}", str(value))

    return path


def _make_request(ctx: AppContext, method: str, path: str, requires_key: bool) -> Any:
    from qortium_cli.services import make_session

    with make_session(ctx, include_api_key=requires_key) as session:
        url = ctx.endpoint.base_url.rstrip("/") + path
        if method == "GET":
            resp = session.get(url, timeout=ctx.endpoint.timeout_seconds)
        elif method == "POST":
            body_raw = prompt_str("  Request body (JSON, blank for empty): ", "").strip()
            body = _json.loads(body_raw) if body_raw else {}
            resp = session.post(url, json=body, timeout=ctx.endpoint.timeout_seconds)
        else:
            raise ValueError(f"Unsupported method: {method}")
        resp.raise_for_status()
        try:
            return resp.json()
        except Exception:
            return resp.text


# ---------------------------------------------------------------------------
# API Explorer main entry
# ---------------------------------------------------------------------------

def tool_api_explorer(ctx: AppContext) -> None:
    while True:
        print_banner(ctx.endpoint.base_url, "API Explorer")
        tool_header("Raw API Explorer", "⬢")

        console.print("[qort.dim]Browse all Qortium endpoints. Auto-fills your address and public key.[/]\n")
        console.print("[qort.heading]Categories:[/]")
        for i, cat in enumerate(_CATEGORIES, start=1):
            count = len(ENDPOINT_CATALOG[cat])
            console.print(f"  [qort.key]{i})[/] [white]{cat}[/] [dim]({count} endpoints)[/]")
        console.print(f"  [qort.key]R)[/] [dim]Raw request (enter path manually)[/]")
        console.print(f"  [qort.key]0)[/] [dim]Back[/]")
        console.print()

        choice = read_menu_choice("").upper()
        if choice == "0":
            return

        if choice == "R":
            _raw_request_mode(ctx)
            continue

        try:
            cat_idx = int(choice) - 1
            if cat_idx < 0 or cat_idx >= len(_CATEGORIES):
                warn("Unknown option.")
                pause()
                continue
            selected_category = _CATEGORIES[cat_idx]
        except ValueError:
            warn("Unknown option.")
            pause()
            continue

        endpoints = ENDPOINT_CATALOG[selected_category]
        console.print(f"\n[qort.heading]{selected_category} Endpoints:[/]")
        for j, (method, path_tpl, label, _, req_key, _) in enumerate(endpoints, start=1):
            key_label = "[dim](key)[/]" if req_key else ""
            console.print(
                f"  [qort.key]{j})[/] [bold]{method}[/] [white]{label}[/] {key_label}"
            )
            console.print(f"       [qort.muted]{path_tpl}[/]")
        console.print(f"  [qort.key]0)[/] [dim]Back[/]")
        console.print()

        ep_choice = read_menu_choice("")
        if ep_choice == "0":
            continue
        try:
            ep_idx = int(ep_choice) - 1
            if ep_idx < 0 or ep_idx >= len(endpoints):
                warn("Unknown option.")
                pause()
                continue
            method, path_tpl, label, params, req_key, is_write_tx = endpoints[ep_idx]
        except ValueError:
            warn("Unknown option.")
            pause()
            continue

        console.print(f"\n[qort.heading]{method} {label}[/]")
        if params:
            console.print("[qort.dim]Fill in parameters (auto-filled fields shown automatically):[/]\n")

        filled_path = _fill_path(path_tpl, params, ctx)
        if filled_path is None:
            warn("Cancelled — required parameter missing.")
            pause()
            continue

        console.print(f"\n[dim]Request:[/] [white]{method} {ctx.endpoint.base_url}{filled_path}[/]\n")

        try:
            with spinner(f"{method} {filled_path[:60]}..."):
                result = _make_request(ctx, method, filled_path, req_key)
        except Exception as exc:
            error_panel(pretty_exception(exc), hint="Check node connection and API key.")
            pause()
            continue

        json_panel(
            result if isinstance(result, (dict, list)) else {"response": str(result)},
            title=f"{method} {label}",
        )
        pause()


def _raw_request_mode(ctx: AppContext) -> None:
    console.print("\n[qort.heading]Raw Request Mode[/]")
    console.print("[qort.dim]Enter a path like /admin/status or /names/{name}[/]\n")

    method = prompt_str("Method [GET]: ", "GET").strip().upper() or "GET"
    path = prompt_str("Path: ", "").strip()
    if not path:
        warn("Cancelled.")
        pause()
        return
    if not path.startswith("/"):
        path = "/" + path

    requires_key = prompt_yes_no("Include API key header?", default_yes=True)

    console.print(f"\n[dim]Request:[/] [white]{method} {ctx.endpoint.base_url}{path}[/]\n")

    try:
        with spinner(f"{method} {path}..."):
            result = _make_request(ctx, method, path, requires_key)
    except Exception as exc:
        error_panel(pretty_exception(exc))
        pause()
        return

    json_panel(
        result if isinstance(result, (dict, list)) else {"response": str(result)},
        title=f"{method} {path}",
    )
    pause()
