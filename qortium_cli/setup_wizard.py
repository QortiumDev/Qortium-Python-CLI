from __future__ import annotations

from qortium_cli.constants import C_TEXT, RESET
from qortium_cli.crypto import derive_private_key_from_seed_phrase
from qortium_cli.models import AccountSettings, AppContext, EndpointSettings
from qortium_cli.services import (
    qortal_address_from_public,
    qortal_primary_name_for_address,
    qortal_public_key_from_private,
)
from qortium_cli.storage import write_config_file, write_endpoint_file
from qortium_cli.ui import (
    ok,
    pause,
    print_option,
    print_setup_banner,
    prompt_int,
    prompt_secret,
    prompt_str,
    read_menu_choice,
    warn,
)
from qortium_cli.validators import is_placeholder, normalize_node_url


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


def configure_first_run_files(ctx: AppContext, force: bool = False) -> None:
    if (not force) and current_endpoint_values_ready(ctx) and current_config_values_ready(ctx):
        return

    print_setup_banner("First Run Setup" if not force else "Reconfigure")
    print(C_TEXT + "Let's create endpoint.py and config.py in:" + RESET)
    print(C_TEXT + f"  {ctx.settings_dir}" + RESET)
    print()

    current_url = ctx.endpoint.base_url
    current_timeout = ctx.endpoint.timeout_seconds

    while True:
        raw_url = prompt_str(
            f"Endpoint URL [{current_url}] (press Enter to use default): ",
            current_url,
        )
        try:
            base_url = normalize_node_url(raw_url)
            break
        except ValueError as exc:
            warn(str(exc))

    timeout = prompt_int(
        f"Timeout seconds [{current_timeout}] (press Enter to use default): ",
        default=current_timeout,
        minimum=1,
    )
    endpoint = EndpointSettings(base_url=base_url, timeout_seconds=timeout)
    write_endpoint_file(ctx.settings_dir, endpoint)
    ctx.endpoint = endpoint

    existing_api_key = (ctx.account.api_key or "").strip()
    has_existing_api_key = bool(existing_api_key) and (not is_placeholder(existing_api_key))
    if has_existing_api_key:
        api_key = prompt_secret("API key (X-API-KEY) (press Enter to keep current): ").strip()
        if not api_key:
            api_key = existing_api_key
    else:
        api_key = prompt_secret("API key (X-API-KEY): ").strip()

    if not api_key:
        raise RuntimeError("API key is required to continue setup.")

    print()
    print_option("1", "Use private key")
    print_option("2", "Use seed phrase")
    mode = read_menu_choice("Choose key input mode [1/2]: ").strip() or "1"
    if mode not in {"1", "2"}:
        mode = "1"

    if mode == "1":
        private_key = prompt_secret("Private key: ")
    else:
        seed_phrase = prompt_secret("Seed phrase: ")
        private_key = derive_private_key_from_seed_phrase(seed_phrase)
        ok("Derived private key from seed phrase.")

    if not private_key:
        raise RuntimeError("Private key is empty.")

    public_key = qortal_public_key_from_private(base_url, private_key, timeout)
    address = qortal_address_from_public(base_url, public_key, timeout)
    primary_name = qortal_primary_name_for_address(base_url, address, timeout)
    display_name = primary_name or address

    account = AccountSettings(
        name=display_name,
        account_address=address,
        public_key=public_key,
        private_key=private_key,
        api_key=api_key,
    )
    write_config_file(ctx.settings_dir, account)
    ctx.account = account

    ok("Setup complete. endpoint.py and config.py have been created.")
    print(C_TEXT + f"Settings directory: {ctx.settings_dir}" + RESET)
    pause()
