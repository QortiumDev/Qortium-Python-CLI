from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import requests

from qortium_cli.models import AppContext
from qortium_cli.paths import project_root_dir, resolve_settings_dir
from qortium_cli.services import (
    compute_transaction_nonce,
    http_error_detail,
    is_nonce_or_pow_error,
    make_session,
    process_tx,
    sign_tx,
)
from qortium_cli.storage import load_account_settings, load_chat_settings, load_endpoint_settings
from qortium_cli.validators import is_placeholder, normalize_node_url

TRANSACTION_BYTES_KEYS = (
    "transactionBytes",
    "unsignedTransactionBytes",
    "signedTransactionBytes",
    "rawTransactionBytes",
    "rawBytes",
    "txBytes",
)

def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Load a raw transaction, sign it, and submit it to a Qortium/Qortal node. "
            "Input can be plain transaction bytes or JSON containing transactionBytes."
        )
    )

    input_group = parser.add_mutually_exclusive_group()
    input_group.add_argument(
        "--tx",
        help="Raw transaction bytes, or JSON containing transaction bytes.",
    )
    input_group.add_argument(
        "--tx-file",
        help="Path to file containing raw transaction bytes or JSON. Use '-' for stdin.",
    )

    parser.add_argument(
        "--signed",
        action="store_true",
        help="Treat input as already signed and submit directly.",
    )
    parser.add_argument(
        "--skip-process",
        action="store_true",
        help="Sign only (or validate signed input) and skip broadcast.",
    )
    parser.add_argument(
        "--out-signed",
        help="Write signed transaction bytes to this file.",
    )
    parser.add_argument(
        "--settings-dir",
        help="Override runtime settings directory (contains endpoint.py/config.py).",
    )
    parser.add_argument(
        "--endpoint",
        help="Override node base URL, e.g. http://127.0.0.1:24891.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        help="Override request timeout in seconds.",
    )
    parser.add_argument(
        "--api-key",
        help="Override API key used for authenticated calls.",
    )
    parser.add_argument(
        "--private-key",
        help="Override private key used for signing.",
    )
    parser.add_argument(
        "--auto-nonce",
        dest="auto_nonce",
        action="store_true",
        help="Retry with automatic nonce computation if node reports nonce/PoW issues (default).",
    )
    parser.add_argument(
        "--no-auto-nonce",
        dest="auto_nonce",
        action="store_false",
        help="Disable nonce/PoW retry logic.",
    )
    parser.set_defaults(auto_nonce=True)

    return parser.parse_args(argv)


def _extract_tx_bytes_from_json(node: Any) -> str:
    if isinstance(node, dict):
        for key in TRANSACTION_BYTES_KEYS:
            value = node.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()

        for value in node.values():
            extracted = _extract_tx_bytes_from_json(value)
            if extracted:
                return extracted
        return ""

    if isinstance(node, list):
        for item in node:
            extracted = _extract_tx_bytes_from_json(item)
            if extracted:
                return extracted
    return ""


def _read_input_text(args: argparse.Namespace) -> str:
    if args.tx is not None:
        return str(args.tx)

    if args.tx_file:
        if args.tx_file == "-":
            return sys.stdin.read()
        return Path(args.tx_file).read_text(encoding="utf-8")

    if not sys.stdin.isatty():
        return sys.stdin.read()

    raise RuntimeError("No transaction input provided. Use --tx, --tx-file, or pipe input via stdin.")


def _load_tx_bytes(raw_input: str) -> str:
    text = (raw_input or "").lstrip("\ufeff").strip()
    if not text:
        raise RuntimeError("Transaction input is empty.")

    if text.startswith("{") or text.startswith("["):
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            return text

        extracted = _extract_tx_bytes_from_json(payload)
        if extracted:
            return extracted

        raise RuntimeError(
            "JSON input did not include transaction bytes. "
            f"Expected one of: {', '.join(TRANSACTION_BYTES_KEYS)}."
        )

    return text


def _build_context(args: argparse.Namespace) -> AppContext:
    project_root = project_root_dir()
    if args.settings_dir:
        settings_dir = Path(args.settings_dir).expanduser().resolve()
    else:
        settings_dir = resolve_settings_dir(project_root)

    endpoint = load_endpoint_settings(settings_dir)
    account = load_account_settings(settings_dir)
    chat = load_chat_settings(settings_dir)
    ctx = AppContext(settings_dir=settings_dir, endpoint=endpoint, account=account, chat=chat, debug=False)

    if args.endpoint:
        ctx.endpoint.base_url = normalize_node_url(args.endpoint)

    if args.timeout is not None:
        if int(args.timeout) <= 0:
            raise RuntimeError("--timeout must be greater than 0.")
        ctx.endpoint.timeout_seconds = int(args.timeout)

    if args.api_key is not None:
        ctx.account.api_key = str(args.api_key).strip()

    if args.private_key is not None:
        ctx.account.private_key = str(args.private_key).strip()

    return ctx


def _extract_signature(process_result: Any) -> str:
    if isinstance(process_result, dict):
        candidate_keys = ("signature", "transactionSignature", "sig")
        for key in candidate_keys:
            value = process_result.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    if isinstance(process_result, str):
        text = process_result.strip()
        if text and text.lower() not in {"true", "false"}:
            return text
    return ""


def _is_insufficient_fee_error(exc: requests.exceptions.HTTPError) -> bool:
    detail = http_error_detail(exc).upper()
    return "INSUFFICIENT_FEE" in detail


def _is_invalid_signature_error(exc: requests.exceptions.HTTPError) -> bool:
    detail = http_error_detail(exc).lower()
    return "invalid signature" in detail or '"error":101' in detail


def _require_private_key(ctx: AppContext) -> None:
    if is_placeholder(ctx.account.private_key):
        raise RuntimeError(
            "Private key is missing. Set it in config.py or pass --private-key for this run."
        )


def _maybe_write_signed(path_value: str | None, signed_tx: str) -> None:
    if not path_value:
        return
    path = Path(path_value).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(signed_tx + "\n", encoding="utf-8")


def _submit_with_optional_nonce_retry(
    ctx: AppContext,
    unsigned_tx: str,
    session: requests.Session,
    auto_nonce: bool,
) -> tuple[str, Any]:
    signed_tx = sign_tx(ctx, unsigned_tx, session)
    try:
        result = process_tx(ctx, signed_tx, session)
        return signed_tx, result
    except requests.exceptions.HTTPError as exc:
        if not auto_nonce:
            raise
        if not (
            is_nonce_or_pow_error(exc)
            or _is_insufficient_fee_error(exc)
            or _is_invalid_signature_error(exc)
        ):
            raise

        computed_tx, path = compute_transaction_nonce(ctx, unsigned_tx, session)
        print(f"Computed mempow nonce via {path}.", file=sys.stderr)

        signed_retry = sign_tx(ctx, computed_tx, session)
        result_retry = process_tx(ctx, signed_retry, session)
        return signed_retry, result_retry


def run(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    ctx = _build_context(args)

    raw_input = _read_input_text(args)
    tx_bytes = _load_tx_bytes(raw_input)

    if args.signed:
        signed_tx = tx_bytes
        _maybe_write_signed(args.out_signed, signed_tx)
        if args.skip_process:
            print("Input accepted as signed transaction. Broadcast skipped (--skip-process).")
            return 0

        with make_session(ctx, include_api_key=True) as session:
            result = process_tx(ctx, signed_tx, session)
        print("Transaction submitted.")
        signature = _extract_signature(result)
        if signature:
            print("Signature: " + signature)
        print("Node response:")
        print(json.dumps(result, indent=2) if isinstance(result, (dict, list)) else str(result))
        return 0

    _require_private_key(ctx)
    with make_session(ctx, include_api_key=True) as session:
        if args.skip_process:
            signed_tx = sign_tx(ctx, tx_bytes, session)
            _maybe_write_signed(args.out_signed, signed_tx)
            print("Transaction signed. Broadcast skipped (--skip-process).")
            print(signed_tx)
            return 0

        signed_tx, result = _submit_with_optional_nonce_retry(ctx, tx_bytes, session, bool(args.auto_nonce))
        _maybe_write_signed(args.out_signed, signed_tx)

    print("Transaction signed and submitted.")
    signature = _extract_signature(result)
    if signature:
        print("Signature: " + signature)
    print("Node response:")
    print(json.dumps(result, indent=2) if isinstance(result, (dict, list)) else str(result))
    return 0


def main() -> None:
    try:
        raise SystemExit(run())
    except requests.exceptions.HTTPError as exc:
        status_code = exc.response.status_code if exc.response is not None else "?"
        print(f"HTTP error ({status_code}): {http_error_detail(exc)}", file=sys.stderr)
        raise SystemExit(1)
    except requests.exceptions.RequestException as exc:
        print(f"Request failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
