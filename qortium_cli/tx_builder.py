from __future__ import annotations

import argparse
import json
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict

import requests

from qortium_cli.crypto import to_base58_pubkey
from qortium_cli.models import AppContext
from qortium_cli.paths import project_root_dir, resolve_settings_dir
from qortium_cli.services import (
    build_raw_transaction,
    compute_transaction_nonce,
    get_last_reference,
    get_recommended_fee,
    get_timestamp,
    is_nonce_or_pow_error,
    make_session,
    process_tx,
    sign_tx,
)
from qortium_cli.storage import load_account_settings, load_chat_settings, load_endpoint_settings
from qortium_cli.utils import d8
from qortium_cli.validators import is_placeholder, normalize_node_url

APPROVAL_THRESHOLDS = ("NONE", "ONE", "PCT20", "PCT40", "PCT60", "PCT80", "PCT100")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build, sign, and optionally submit common transactions via Qortium/Qortal "
            "builder endpoints."
        )
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
        "--public-key",
        help="Override public key used as the transaction creator or joiner.",
    )
    parser.add_argument(
        "--reference",
        help="Override last reference. If omitted, fetched from node.",
    )
    parser.add_argument(
        "--timestamp",
        type=int,
        help="Override transaction timestamp in milliseconds. If omitted, fetched from node.",
    )
    parser.add_argument(
        "--tx-group-id",
        type=int,
        default=0,
        help="Transaction group ID (default: 0).",
    )
    parser.add_argument(
        "--fee",
        default="0",
        help="Transaction fee as decimal string (default: 0).",
    )
    parser.add_argument(
        "--build-only",
        action="store_true",
        help="Build unsigned transaction only (skip sign/process).",
    )
    parser.add_argument(
        "--skip-process",
        action="store_true",
        help="Build + sign but do not broadcast.",
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
    parser.add_argument(
        "--out-payload",
        help="Write builder JSON payload to this file.",
    )
    parser.add_argument(
        "--out-unsigned",
        help="Write unsigned transaction bytes to this file.",
    )
    parser.add_argument(
        "--out-signed",
        help="Write signed transaction bytes to this file.",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    join = subparsers.add_parser("group-join", help="Build/sign/submit /groups/join")
    join.add_argument("--group-id", type=int, required=True, help="Target group ID.")

    create = subparsers.add_parser("group-create", help="Build/sign/submit /groups/create")
    create.add_argument("--group-name", required=True, help="Group name (3-32 chars).")
    create.add_argument("--description", required=True, help="Group description (1-128 chars).")
    create.add_argument(
        "--approval-threshold",
        choices=APPROVAL_THRESHOLDS,
        default="NONE",
        help="Group approval threshold (default: NONE).",
    )
    create.add_argument(
        "--min-block-delay",
        type=int,
        default=0,
        help="Minimum block delay for approvals (default: 0).",
    )
    create.add_argument(
        "--max-block-delay",
        type=int,
        default=1440,
        help="Maximum block delay for approvals (default: 1440).",
    )
    create_group_mode = create.add_mutually_exclusive_group()
    create_group_mode.add_argument(
        "--open",
        dest="open_group",
        action="store_true",
        help="Create an open group (default).",
    )
    create_group_mode.add_argument(
        "--closed",
        dest="open_group",
        action="store_false",
        help="Create a closed group.",
    )
    create.set_defaults(open_group=True)

    register = subparsers.add_parser("name-register", help="Build/sign/submit /names/register")
    register.add_argument("--name", required=True, help="Name to register.")
    register.add_argument(
        "--data",
        default="{}",
        help="Name data string (default: {}).",
    )

    return parser.parse_args(argv)


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

    if args.public_key is not None:
        ctx.account.public_key = str(args.public_key).strip()

    return ctx


def _normalize_fee(raw_fee: str) -> str:
    try:
        fee = Decimal(str(raw_fee).strip())
    except (InvalidOperation, ValueError):
        raise RuntimeError(f"Invalid fee value: {raw_fee}") from None

    if fee < 0:
        raise RuntimeError("Fee cannot be negative.")
    return d8(fee)


def _require_wallet_values(ctx: AppContext, require_private: bool = True) -> None:
    missing = []
    if is_placeholder(ctx.account.account_address):
        missing.append("ACCOUNT_ADDRESS")
    if is_placeholder(ctx.account.public_key):
        missing.append("PUBLIC_KEY")
    if require_private and is_placeholder(ctx.account.private_key):
        missing.append("PRIVATE_KEY")

    if missing:
        raise RuntimeError("Missing wallet settings: " + ", ".join(missing))


def _write_text_file(path_value: str | None, text: str) -> None:
    if not path_value:
        return
    path = Path(path_value).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip() + "\n", encoding="utf-8")


def _extract_signature(process_result: Any) -> str:
    if isinstance(process_result, dict):
        for key in ("signature", "transactionSignature", "sig"):
            value = process_result.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    if isinstance(process_result, str):
        text = process_result.strip()
        if text and text.lower() not in {"true", "false"}:
            return text
    return ""


def _is_insufficient_fee_error(exc: Exception) -> bool:
    if not isinstance(exc, requests.exceptions.HTTPError):
        return False
    if exc.response is None:
        return False
    detail = (exc.response.text or "").upper()
    return "INSUFFICIENT_FEE" in detail


def _is_invalid_signature_error(exc: Exception) -> bool:
    if not isinstance(exc, requests.exceptions.HTTPError):
        return False
    if exc.response is None:
        return False
    detail = (exc.response.text or "").lower()
    return "invalid signature" in detail or '"error":101' in detail


def _base_payload(
    ctx: AppContext,
    args: argparse.Namespace,
    session: requests.Session,
) -> Dict[str, Any]:
    if args.tx_group_id < 0:
        raise RuntimeError("--tx-group-id must be >= 0.")

    timestamp = int(args.timestamp) if args.timestamp is not None else get_timestamp(ctx, session)

    if args.reference:
        reference = str(args.reference).strip()
    else:
        reference = get_last_reference(ctx, ctx.account.account_address, session)

    return {
        "timestamp": timestamp,
        "reference": reference,
        "fee": _normalize_fee(args.fee),
        "txGroupId": int(args.tx_group_id),
    }


def _build_payload_and_path(
    ctx: AppContext,
    args: argparse.Namespace,
    session: requests.Session,
) -> tuple[str, Dict[str, Any]]:
    sender_pub = to_base58_pubkey(ctx.account.public_key)
    payload = _base_payload(ctx, args, session)

    if args.command == "group-join":
        if args.group_id <= 0:
            raise RuntimeError("--group-id must be > 0.")
        payload.update(
            {
                "joinerPublicKey": sender_pub,
                "groupId": int(args.group_id),
            }
        )
        return "/groups/join", payload

    if args.command == "group-create":
        if args.min_block_delay < 0:
            raise RuntimeError("--min-block-delay must be >= 0.")
        if args.max_block_delay < 1:
            raise RuntimeError("--max-block-delay must be >= 1.")
        if args.max_block_delay < args.min_block_delay:
            raise RuntimeError("--max-block-delay must be >= --min-block-delay.")

        payload.update(
            {
                "groupName": str(args.group_name),
                "description": str(args.description),
                "approvalThreshold": str(args.approval_threshold),
                "minimumBlockDelay": int(args.min_block_delay),
                "maximumBlockDelay": int(args.max_block_delay),
                "open": bool(args.open_group),
                "creatorPublicKey": sender_pub,
            }
        )
        return "/groups/create", payload

    if args.command == "name-register":
        payload.update(
            {
                "registrantPublicKey": sender_pub,
                "name": str(args.name),
                "data": str(args.data),
            }
        )
        return "/names/register", payload

    raise RuntimeError(f"Unsupported command: {args.command}")


def run(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    ctx = _build_context(args)

    _require_wallet_values(ctx, require_private=not bool(args.build_only))

    with make_session(ctx, include_api_key=True) as session:
        path, payload = _build_payload_and_path(ctx, args, session)
        _write_text_file(args.out_payload, json.dumps(payload, indent=2))

        unsigned_tx = build_raw_transaction(ctx, path, payload, session)
        _write_text_file(args.out_unsigned, unsigned_tx)

        if args.build_only:
            print("Unsigned transaction bytes:")
            print(unsigned_tx)
            return 0

        signed_tx = sign_tx(ctx, unsigned_tx, session)
        _write_text_file(args.out_signed, signed_tx)

        if args.skip_process:
            print("Signed transaction bytes:")
            print(signed_tx)
            return 0

        fee_retried = False
        nonce_retried = False

        while True:
            try:
                result = process_tx(ctx, signed_tx, session)
                break
            except Exception as exc:
                should_try_mempow = (
                    _is_insufficient_fee_error(exc)
                    or is_nonce_or_pow_error(exc)
                    or _is_invalid_signature_error(exc)
                )
                if bool(args.auto_nonce) and not nonce_retried and should_try_mempow:
                    try:
                        unsigned_tx, nonce_path = compute_transaction_nonce(ctx, unsigned_tx, session)
                        nonce_retried = True
                        print(f"Computed mempow nonce via {nonce_path}.")
                        _write_text_file(args.out_unsigned, unsigned_tx)
                        signed_tx = sign_tx(ctx, unsigned_tx, session)
                        _write_text_file(args.out_signed, signed_tx)
                        continue
                    except Exception:
                        if not _is_insufficient_fee_error(exc):
                            raise

                if fee_retried or not _is_insufficient_fee_error(exc):
                    raise

                current_fee = Decimal(str(payload.get("fee", "0")))
                recommended_fee = get_recommended_fee(ctx, unsigned_tx, session)
                if recommended_fee <= current_fee:
                    raise RuntimeError(
                        f"Node reported INSUFFICIENT_FEE, but recommended fee ({recommended_fee}) "
                        f"is not greater than current fee ({current_fee})."
                    ) from exc

                payload["fee"] = d8(recommended_fee)
                fee_retried = True
                nonce_retried = False
                print(f"Insufficient fee. Retrying with recommended fee: {payload['fee']}")
                _write_text_file(args.out_payload, json.dumps(payload, indent=2))

                unsigned_tx = build_raw_transaction(ctx, path, payload, session)
                _write_text_file(args.out_unsigned, unsigned_tx)
                signed_tx = sign_tx(ctx, unsigned_tx, session)
                _write_text_file(args.out_signed, signed_tx)

    print("Transaction submitted.")
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
        response = exc.response
        status = response.status_code if response is not None else "?"
        body = ""
        if response is not None:
            body = (response.text or "").strip()
        if body:
            print(f"HTTP error ({status}): {body}", file=sys.stderr)
        else:
            print(f"HTTP error ({status}): {exc}", file=sys.stderr)
        raise SystemExit(1)
    except requests.exceptions.RequestException as exc:
        print(f"Request failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
