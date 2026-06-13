from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from qortium_cli.constants import C_TEXT, RESET
from qortium_cli.core_detection import detect_local_core_api_key
from qortium_cli.crypto import derive_private_key_from_seed_phrase
from qortium_cli.models import AccountSettings, AppContext, EndpointSettings
from qortium_cli.services import (
    check_node_connection,
    qortal_address_from_public,
    qortal_primary_name_for_address,
    qortal_public_key_from_private,
)
from qortium_cli.storage import write_config_file, write_endpoint_file
from qortium_cli.ui import (
    error,
    ok,
    pause,
    print_option,
    print_setup_banner,
    print_stat,
    prompt_int,
    prompt_secret,
    prompt_str,
    read_menu_choice,
    warn,
)
from qortium_cli.validators import is_placeholder, normalize_node_url
from qortium_cli.wallet_backup import private_key_from_wallet_file


def current_endpoint_values_ready(ctx: AppContext) -> bool:
    try:
        normalize_node_url(ctx.endpoint.base_url)
    except Exception:
        return False
    return ctx.endpoint.timeout_seconds > 0


def current_config_values_ready(ctx: AppContext) -> bool:
    required = [
        ctx.account.account_address,
        ctx.account.public_key,
        ctx.account.private_key,
        ctx.account.api_key,
    ]
    for value in required:
        if is_placeholder(value):
            return False
    return True


def _prompt_private_key() -> str:
    print()
    print_option("1", "Use private key")
    print_option("2", "Use seed phrase")
    print_option("3", "Use Qortium Home wallet file")
    mode = read_menu_choice("Choose key input mode [1/2/3]: ").strip() or "1"
    if mode not in {"1", "2", "3"}:
        mode = "1"

    if mode == "1":
        private_key = prompt_secret("Private key: ").strip()
    elif mode == "2":
        seed_phrase = prompt_secret("Seed phrase: ").strip()
        private_key = derive_private_key_from_seed_phrase(seed_phrase)
        ok("Derived private key from seed phrase.")
    else:
        wallet_path = prompt_str("Wallet file path: ").strip()
        if not wallet_path:
            raise RuntimeError("Wallet file path is empty.")
        wallet_password = prompt_secret("Wallet password: ")
        private_key = private_key_from_wallet_file(Path(wallet_path), wallet_password)
        ok("Unlocked Qortium Home wallet file.")

    if not private_key:
        raise RuntimeError("Private key is empty.")
    return private_key


def _account_from_private_key(ctx: AppContext, private_key: str, api_key: str) -> AccountSettings:
    public_key = qortal_public_key_from_private(
        ctx.endpoint.base_url,
        private_key,
        ctx.endpoint.timeout_seconds,
    )
    address = qortal_address_from_public(
        ctx.endpoint.base_url,
        public_key,
        ctx.endpoint.timeout_seconds,
    )
    primary_name = qortal_primary_name_for_address(
        ctx.endpoint.base_url,
        address,
        ctx.endpoint.timeout_seconds,
    )
    return AccountSettings(
        name=primary_name or address,
        account_address=address,
        public_key=public_key,
        private_key=private_key,
        api_key=api_key,
    )


def _confirm_endpoint_connection(base_url: str, timeout_seconds: int) -> bool:
    connected, detail = check_node_connection(base_url, timeout_seconds)
    if connected:
        ok(detail or "Connected to node API.")
        return True

    warn(f"Node is not connected at {base_url}.")
    if detail:
        warn(detail)

    while True:
        print()
        print_option("1", "Enter a different endpoint URL")
        print_option("2", "Continue with this endpoint anyway")
        choice = read_menu_choice("Choose an option: ").strip()

        if choice == "1":
            return False
        if choice == "2":
            warn("Continuing with endpoint even though the connection check failed.")
            return True

        warn("Unknown option.")


def _prompt_endpoint_url_with_connection_check(
    prompt: str,
    default_url: str,
    timeout_seconds: int,
) -> str:
    while True:
        raw_url = prompt_str(prompt, default_url)
        try:
            base_url = normalize_node_url(raw_url)
        except ValueError as exc:
            warn(str(exc))
            continue

        if _confirm_endpoint_connection(base_url, timeout_seconds):
            return base_url


def _detect_local_core_api_key(ctx: AppContext):
    suggestion = detect_local_core_api_key(ctx.endpoint.base_url)
    if suggestion:
        ok(f"Detected local Core API key at: {suggestion.api_key_path}")
    return suggestion


def _prompt_required_api_key(ctx: AppContext, existing_api_key: str = "") -> str:
    has_existing_api_key = bool(existing_api_key) and (not is_placeholder(existing_api_key))
    if has_existing_api_key:
        api_key = prompt_secret("API key (X-API-KEY) (press Enter to keep current): ").strip()
        return api_key or existing_api_key

    suggestion = _detect_local_core_api_key(ctx)
    if suggestion:
        api_key = prompt_secret(
            "API key (X-API-KEY) [detected local Core key] (press Enter to use): "
        ).strip()
        return api_key or suggestion.api_key

    return prompt_secret("API key (X-API-KEY): ").strip()


def configure_endpoint_url(ctx: AppContext) -> None:
    current_url = ctx.endpoint.base_url
    while True:
        raw_url = prompt_str(
            f"New endpoint URL [{current_url}] (press Enter to cancel): ",
            current_url,
        )
        try:
            base_url = normalize_node_url(raw_url)
        except ValueError as exc:
            warn(str(exc))
            continue

        if base_url == current_url:
            warn("Endpoint URL unchanged.")
            return

        if _confirm_endpoint_connection(base_url, ctx.endpoint.timeout_seconds):
            break

    ctx.endpoint = replace(ctx.endpoint, base_url=base_url)
    write_endpoint_file(ctx.settings_dir, ctx.endpoint)
    ok("Endpoint URL updated.")


def configure_timeout(ctx: AppContext) -> None:
    current_timeout = ctx.endpoint.timeout_seconds
    timeout = prompt_int(
        f"New timeout seconds [{current_timeout}]: ",
        default=current_timeout,
        minimum=1,
    )
    if timeout == current_timeout:
        warn("Timeout unchanged.")
        return

    ctx.endpoint = replace(ctx.endpoint, timeout_seconds=timeout)
    write_endpoint_file(ctx.settings_dir, ctx.endpoint)
    ok("Request timeout updated.")


def configure_api_key(ctx: AppContext) -> None:
    suggestion = _detect_local_core_api_key(ctx)
    if suggestion:
        api_key = prompt_secret(
            "New API key [detected local Core key] "
            "(press Enter to use, type /cancel to cancel): "
        ).strip()
        if not api_key:
            api_key = suggestion.api_key
        elif api_key.lower() == "/cancel":
            api_key = ""
    else:
        api_key = prompt_secret("New API key (press Enter to cancel): ").strip()

    if not api_key:
        warn("API key unchanged.")
        return

    ctx.account = replace(ctx.account, api_key=api_key)
    write_config_file(ctx.settings_dir, ctx.account)
    ok("API key updated. Wallet keys were not changed.")


def configure_wallet_identity(ctx: AppContext) -> None:
    private_key = _prompt_private_key()
    api_key = (ctx.account.api_key or "").strip()
    account = _account_from_private_key(ctx, private_key, api_key)
    write_config_file(ctx.settings_dir, account)
    ctx.account = account
    ok("Wallet identity updated.")
    print(C_TEXT + f"Account: {ctx.account.account_address}" + RESET)


def run_reconfigure_menu(ctx: AppContext) -> None:
    while True:
        print_setup_banner("Reconfigure")
        print_stat("Endpoint", ctx.endpoint.base_url)
        print_stat("Timeout", f"{ctx.endpoint.timeout_seconds} seconds")
        print_stat("Account", ctx.account.account_address)
        print_stat(
            "API Key",
            "Configured" if not is_placeholder(ctx.account.api_key) else "Missing",
        )
        print()
        print_option("1", "Change endpoint URL")
        print_option("2", "Change request timeout")
        print_option("3", "Change API key")
        print_option("4", "Change wallet / account")
        print_option("0", "Back")
        choice = read_menu_choice("Choose an option: ")

        if choice == "0":
            return

        try:
            if choice == "1":
                configure_endpoint_url(ctx)
                pause()
                continue
            if choice == "2":
                configure_timeout(ctx)
                pause()
                continue
            if choice == "3":
                configure_api_key(ctx)
                pause()
                continue
            if choice == "4":
                configure_wallet_identity(ctx)
                pause()
                continue
        except Exception as exc:
            error("Reconfiguration failed:")
            print(str(exc))
            pause()
            continue

        warn("Unknown option.")
        pause()


def configure_first_run_files(ctx: AppContext, force: bool = False) -> None:
    if force:
        run_reconfigure_menu(ctx)
        return

    if current_endpoint_values_ready(ctx) and current_config_values_ready(ctx):
        return

    print_setup_banner("First Run Setup")
    print(C_TEXT + "Let's create endpoint.py and config.py in:" + RESET)
    print(C_TEXT + f"  {ctx.settings_dir}" + RESET)
    print()

    current_url = ctx.endpoint.base_url
    current_timeout = ctx.endpoint.timeout_seconds

    base_url = _prompt_endpoint_url_with_connection_check(
        f"Endpoint URL [{current_url}] (press Enter to use default): ",
        current_url,
        current_timeout,
    )

    timeout = prompt_int(
        f"Timeout seconds [{current_timeout}] (press Enter to use default): ",
        default=current_timeout,
        minimum=1,
    )
    endpoint = EndpointSettings(base_url=base_url, timeout_seconds=timeout)
    write_endpoint_file(ctx.settings_dir, endpoint)
    ctx.endpoint = endpoint

    existing_api_key = (ctx.account.api_key or "").strip()
    api_key = _prompt_required_api_key(ctx, existing_api_key)

    if not api_key:
        raise RuntimeError("API key is required to continue setup.")

    private_key = _prompt_private_key()
    account = _account_from_private_key(ctx, private_key, api_key)
    write_config_file(ctx.settings_dir, account)
    ctx.account = account

    ok("Setup complete. endpoint.py and config.py have been created.")
    print(C_TEXT + f"Settings directory: {ctx.settings_dir}" + RESET)
    pause()
