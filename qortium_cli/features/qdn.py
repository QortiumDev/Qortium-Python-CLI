"""QDN discovery, publishing, downloading, and local storage workflows."""

from __future__ import annotations

from pathlib import Path
from decimal import Decimal
from urllib.parse import quote

from qortium_cli.constants import QDN_SERVICES
from qortium_cli.models import AppContext
from qortium_cli.ui import (
    ok,
    pause,
    prompt_decimal,
    prompt_str,
    prompt_yes_no,
    warn,
)
from qortium_cli.ui.menu import MenuOption, run_menu
from qortium_cli.ui.widgets import spinner


def _safe_filename(value: str) -> str:
    cleaned = "".join(char if char.isalnum() or char in "._-" else "-" for char in value)
    return cleaned.strip(".-") or "qdn-download.bin"


def download_qdn_file(ctx: AppContext) -> None:
    """Download one file from an exact QDN resource tuple."""

    from qortium_cli.services import build_api_url, make_session

    service = prompt_str("Service [FILE]: ", "FILE").strip().upper()
    if service not in QDN_SERVICES:
        raise RuntimeError(f"Unsupported QDN service: {service}")
    name = prompt_str("Registered name: ").strip()
    if not name:
        warn("Download cancelled.")
        return
    identifier = prompt_str("Identifier [default]: ", "default").strip() or "default"
    filepath = prompt_str("File inside resource [automatic]: ", "").strip()

    suggested_bits = [name, identifier]
    if filepath:
        suggested_bits.append(Path(filepath).name)
    suggested = _safe_filename("-".join(suggested_bits))
    output = Path(prompt_str(f"Save as [{suggested}]: ", suggested)).expanduser()
    if output.exists() and not prompt_yes_no(f"{output} exists. Overwrite?", default_yes=False):
        warn("Download cancelled.")
        return
    partial = output.with_name(output.name + ".part")

    path = f"/arbitrary/{quote(service, safe='')}/{quote(name, safe='')}"
    if identifier.lower() != "default":
        path += f"/{quote(identifier, safe='')}"
    params: dict[str, object] = {"attachment": "true", "attempts": 5}
    if filepath:
        params["filepath"] = filepath

    try:
        with spinner("Requesting and downloading QDN data..."):
            with make_session(ctx, include_api_key=True) as session:
                response = session.get(
                    build_api_url(ctx, path),
                    params=params,
                    timeout=max(ctx.endpoint.timeout_seconds, 300),
                    stream=True,
                )
                response.raise_for_status()
                output.parent.mkdir(parents=True, exist_ok=True)
                with partial.open("wb") as destination:
                    for chunk in response.iter_content(chunk_size=1024 * 128):
                        if chunk:
                            destination.write(chunk)
                partial.replace(output)
    except Exception:
        partial.unlink(missing_ok=True)
        raise
    ok(f"Saved QDN file to {output.resolve()}")
    pause()


def _browse(ctx: AppContext) -> None:
    from qortium_cli.tools import browse_qdn_resources

    browse_qdn_resources(ctx)
    pause()


def _publish_app(ctx: AppContext) -> None:
    from qortium_cli.tools import publish_qdn_app

    publish_qdn_app(ctx)
    pause()


def _publish_file_or_folder(ctx: AppContext) -> None:
    from qortium_cli.tools import _parse_arbitrary_tags, _submit_arbitrary_publish_transaction
    from qortium_cli.validators import is_placeholder, looks_like_qortal_address

    service = prompt_str("QDN service [FILE]: ", "FILE").strip().upper()
    if service not in QDN_SERVICES:
        raise RuntimeError(f"Unsupported QDN service: {service}")
    if service == "APP":
        warn("Use Publish an app so the APP structure is validated first.")
        return

    suggested_name = (ctx.account.name or "").strip()
    if is_placeholder(suggested_name) or looks_like_qortal_address(suggested_name):
        suggested_name = ""
    prompt = f"Registered name [{suggested_name}]: " if suggested_name else "Registered name: "
    name = prompt_str(prompt, suggested_name).strip()
    if not name:
        warn("Publish cancelled.")
        return

    identifier = prompt_str("Identifier [default]: ", "default").strip() or "default"
    local_path = prompt_str("Local file or folder: ").strip()
    if not local_path:
        warn("Publish cancelled.")
        return
    source = Path(local_path).expanduser()
    if not source.exists():
        raise RuntimeError(f"Local path does not exist: {source}")

    title = prompt_str("Title [optional]: ", "").strip()
    description = prompt_str("Description [optional]: ", "").strip()
    tags = _parse_arbitrary_tags(prompt_str("Tags, comma separated [optional]: ", ""))
    category = prompt_str("Category [UNCATEGORIZED]: ", "UNCATEGORIZED").strip().upper()
    fee = prompt_decimal("Fee [0.00000000]: ", default=Decimal("0"))

    print()
    print(f"Service:    {service}")
    print(f"Name:       {name}")
    print(f"Identifier: {identifier}")
    print(f"Source:     {source}")
    if not prompt_yes_no("Sign and publish this QDN resource?", default_yes=False):
        warn("Publish cancelled.")
        return

    _submit_arbitrary_publish_transaction(
        ctx,
        service=service,
        name=name,
        identifier="" if identifier.lower() == "default" else identifier,
        local_path=str(source),
        title=title,
        description=description,
        tags=tags,
        category=category,
        fee=fee,
    )
    pause()


def _manage(ctx: AppContext) -> None:
    from qortium_cli.tools import tool_qdn_resources

    tool_qdn_resources(ctx)


def open_qdn_hub(ctx: AppContext) -> None:
    run_menu(
        ctx,
        title="QDN Files & Apps",
        subtitle="Find the resource, then choose whether to download, publish, or manage it.",
        options=(
            MenuOption("1", "Browse resources", "Search by service, name, identifier, or text", _browse),
            MenuOption("2", "Download a file", "Save an exact QDN resource file to this computer", download_qdn_file),
            MenuOption("3", "Publish a file or folder", "Sign and publish with the appropriate QDN service", _publish_file_or_folder),
            MenuOption("4", "Publish an app", "Validate, sign, and publish an APP resource", _publish_app),
            MenuOption("5", "Manage resources", "Hosted data and on-chain deletion tools", _manage),
        ),
    )
