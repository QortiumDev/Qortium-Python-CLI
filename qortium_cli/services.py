from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, List

import requests

from qortium_cli.constants import (
    ASSET_ID_QORT,
    NONCE_COMPUTE_PATHS,
    NONCE_COMPUTE_TIMEOUT_SECONDS,
    NONCE_ERROR_MARKERS,
)
from qortium_cli.models import AppContext
from qortium_cli.validators import is_placeholder


class ApiRequestError(RuntimeError):
    def __init__(self, path: str, status_code: int, detail: str):
        self.path = path
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"{path} failed ({status_code}): {detail}")


def parse_api_key_response(response: requests.Response) -> str:
    try:
        body = response.json()
        if isinstance(body, dict):
            for key in ("apiKey", "api_key", "value", "key"):
                value = str(body.get(key, "") or "").strip()
                if value:
                    return value
        if isinstance(body, str) and body.strip():
            return body.strip()
    except Exception:
        pass
    return (response.text or "").strip().strip('"')


def generate_api_key_via_node(base_url: str, timeout_seconds: int, existing_api_key: str = "") -> str:
    headers = {"Accept": "application/json,text/plain"}
    if existing_api_key:
        headers["X-API-KEY"] = existing_api_key

    response = requests.post(
        f"{base_url}/admin/apikey/generate",
        headers=headers,
        timeout=max(1, int(timeout_seconds)),
    )
    if response.status_code >= 400:
        detail = (response.text or "").strip()
        raise ApiRequestError("/admin/apikey/generate", response.status_code, detail)

    api_key = parse_api_key_response(response)
    if not api_key:
        raise RuntimeError("/admin/apikey/generate returned an empty API key.")
    return api_key


def qortal_public_key_from_private(base_url: str, private_key: str, timeout_seconds: int) -> str:
    response = requests.post(
        f"{base_url}/utils/publickey",
        data=private_key,
        headers={"Accept": "text/plain", "Content-Type": "text/plain"},
        timeout=max(1, int(timeout_seconds)),
    )
    response.raise_for_status()
    return (response.text or "").strip().strip('"')


def qortal_address_from_public(base_url: str, public_key: str, timeout_seconds: int) -> str:
    response = requests.get(
        f"{base_url}/addresses/convert/{public_key}",
        timeout=max(1, int(timeout_seconds)),
    )
    response.raise_for_status()
    return (response.text or "").strip().strip('"')


def qortal_primary_name_for_address(base_url: str, address: str, timeout_seconds: int) -> str:
    try:
        response = requests.get(
            f"{base_url}/names/primary/{address}",
            timeout=max(1, int(timeout_seconds)),
        )
        if response.status_code == 404:
            return ""
        response.raise_for_status()
        data = response.json()
        if isinstance(data, dict):
            return str(data.get("name", "") or "").strip()
    except Exception:
        return ""
    return ""


def build_api_url(ctx: AppContext, path: str) -> str:
    return f"{ctx.endpoint.base_url}{path}"


def make_session(ctx: AppContext, include_api_key: bool = True) -> requests.Session:
    session = requests.Session()
    headers = {
        "X-API-VERSION": "2",
        "Accept": "application/json,text/plain",
        "Connection": "keep-alive",
    }
    api_key = (ctx.account.api_key or "").strip()
    if include_api_key and not is_placeholder(api_key):
        headers["X-API-KEY"] = api_key
    session.headers.update(headers)
    return session


def request_json(ctx: AppContext, session: requests.Session, method: str, path: str, **kwargs: Any) -> Any:
    response = session.request(
        method=method,
        url=build_api_url(ctx, path),
        timeout=ctx.endpoint.timeout_seconds,
        **kwargs,
    )
    response.raise_for_status()
    return response.json()


def request_text_or_json(
    ctx: AppContext, session: requests.Session, method: str, path: str, **kwargs: Any
) -> Any:
    response = session.request(
        method=method,
        url=build_api_url(ctx, path),
        timeout=ctx.endpoint.timeout_seconds,
        **kwargs,
    )
    response.raise_for_status()

    content_type = (response.headers.get("Content-Type") or "").lower()
    if "application/json" in content_type:
        return response.json()
    return (response.text or "").strip()


def http_error_detail(exc: requests.exceptions.HTTPError) -> str:
    response = exc.response
    if response is None:
        return str(exc)
    body = (response.text or "").strip()
    if body:
        return body
    return f"HTTP {response.status_code}"


def is_nonce_or_pow_error(exc: Exception) -> bool:
    detail = str(exc)
    if isinstance(exc, requests.exceptions.HTTPError):
        detail = http_error_detail(exc)
    lower = detail.lower()
    return any(marker in lower for marker in NONCE_ERROR_MARKERS)


def compute_transaction_nonce(
    ctx: AppContext,
    unsigned_tx: str,
    session: requests.Session,
    compute_paths: tuple[str, ...] = NONCE_COMPUTE_PATHS,
) -> tuple[str, str]:
    last_error: Exception | None = None
    timeout = max(ctx.endpoint.timeout_seconds, NONCE_COMPUTE_TIMEOUT_SECONDS)

    for path in compute_paths:
        try:
            response = session.post(
                build_api_url(ctx, path),
                data=unsigned_tx,
                headers={"Content-Type": "text/plain"},
                timeout=timeout,
            )
            response.raise_for_status()
            computed = (response.text or "").strip().strip('"')
            if computed:
                return computed, path
        except requests.exceptions.HTTPError as exc:
            status_code = exc.response.status_code if exc.response is not None else 0
            if status_code in {400, 404}:
                continue
            last_error = exc
        except Exception as exc:
            last_error = exc

    if last_error is not None:
        raise RuntimeError(f"Nonce computation failed: {last_error}") from last_error
    raise RuntimeError("No nonce compute endpoint accepted this transaction.")


def get_last_reference(ctx: AppContext, address: str, session: requests.Session) -> str:
    # Legacy endpoint (older Qortal nodes)
    legacy = session.get(
        build_api_url(ctx, f"/addresses/lastreference/{address}"),
        timeout=ctx.endpoint.timeout_seconds,
    )
    if legacy.status_code < 400:
        return (legacy.text or "").strip().strip('"')
    if legacy.status_code != 404:
        legacy.raise_for_status()

    # Fallback endpoint (newer Qorium/Qortal nodes)
    response = session.get(
        build_api_url(ctx, f"/transactions/address/{address}"),
        params={"limit": 1, "offset": 0, "reverse": "true"},
        timeout=ctx.endpoint.timeout_seconds,
    )
    response.raise_for_status()

    data = response.json()
    if isinstance(data, list) and data:
        signature = str(data[0].get("signature", "") or "").strip()
        if signature:
            return signature

    raise RuntimeError(
        "No last reference found for this account on this chain. "
        "Fund the account or use an account that already has at least one transaction."
    )


def get_timestamp(ctx: AppContext, session: requests.Session) -> int:
    response = session.get(
        build_api_url(ctx, "/utils/timestamp"),
        timeout=ctx.endpoint.timeout_seconds,
    )
    response.raise_for_status()
    return int((response.text or "").strip())


def get_qort_balance(ctx: AppContext, address: str, session: requests.Session) -> Decimal:
    # Preferred endpoint for native balance on newer nodes.
    balance_response = session.get(
        build_api_url(ctx, f"/addresses/balance/{address}"),
        timeout=ctx.endpoint.timeout_seconds,
    )
    if balance_response.status_code < 400:
        content_type = (balance_response.headers.get("Content-Type") or "").lower()
        if "application/json" in content_type:
            try:
                body = balance_response.json()
                if isinstance(body, dict) and "value" in body:
                    return Decimal(str(body.get("value", "0")))
            except Exception:
                pass

        raw = (balance_response.text or "").strip().strip('"')
        try:
            return Decimal(raw)
        except Exception:
            pass
    elif balance_response.status_code != 404:
        balance_response.raise_for_status()

    # Fallback endpoint used by older setups.
    response = session.get(
        build_api_url(ctx, "/assets/balances"),
        params={
            "address": address,
            "assetid": ASSET_ID_QORT,
            "ordering": "ASSET_BALANCE_ACCOUNT",
            "limit": 20,
        },
        timeout=ctx.endpoint.timeout_seconds,
    )
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, list):
        return Decimal("0")

    for row in data:
        try:
            if int(row.get("assetId", -1)) == ASSET_ID_QORT:
                return Decimal(str(row.get("balance", "0")))
        except Exception:
            continue
    return Decimal("0")


def get_asset_balances(
    ctx: AppContext,
    address: str,
    session: requests.Session,
    *,
    exclude_zero: bool = True,
    limit: int = 200,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    response = session.get(
        build_api_url(ctx, "/assets/balances"),
        params={
            "address": address,
            "ordering": "ACCOUNT_ASSET",
            "excludeZero": str(bool(exclude_zero)).lower(),
            "limit": max(1, int(limit)),
            "offset": max(0, int(offset)),
        },
        timeout=ctx.endpoint.timeout_seconds,
    )
    response.raise_for_status()
    data = response.json()
    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)]
    return []


def get_asset_info(
    ctx: AppContext,
    session: requests.Session,
    *,
    asset_id: int | None = None,
    asset_name: str | None = None,
) -> Dict[str, Any]:
    params: Dict[str, Any] = {}
    if asset_id is not None:
        params["assetId"] = int(asset_id)
    elif asset_name:
        params["assetName"] = str(asset_name).strip()
    else:
        raise RuntimeError("get_asset_info requires asset_id or asset_name.")

    response = session.get(
        build_api_url(ctx, "/assets/info"),
        params=params,
        timeout=ctx.endpoint.timeout_seconds,
    )
    response.raise_for_status()
    data = response.json()
    if isinstance(data, dict):
        return data
    return {}


def build_chat(ctx: AppContext, payload: Dict[str, Any], session: requests.Session) -> str:
    response = session.post(
        build_api_url(ctx, "/chat"),
        json=payload,
        timeout=ctx.endpoint.timeout_seconds,
    )
    response.raise_for_status()
    return (response.text or "").strip()


def compute_chat_nonce(ctx: AppContext, unsigned_tx: str, session: requests.Session) -> str:
    response = session.post(
        build_api_url(ctx, "/chat/compute"),
        data=unsigned_tx,
        headers={"Content-Type": "text/plain"},
        timeout=max(ctx.endpoint.timeout_seconds, 180),
    )
    response.raise_for_status()
    return (response.text or "").strip()


def build_payment(ctx: AppContext, payload: Dict[str, Any], session: requests.Session) -> str:
    response = session.post(
        build_api_url(ctx, "/payments/pay"),
        json=payload,
        timeout=ctx.endpoint.timeout_seconds,
    )
    response.raise_for_status()
    content_type = (response.headers.get("Content-Type") or "").lower()
    if "application/json" in content_type:
        body = response.json()
        return (body.get("transactionBytes") or "").strip()
    return (response.text or "").strip()


def build_raw_transaction(
    ctx: AppContext,
    path: str,
    payload: Dict[str, Any],
    session: requests.Session,
) -> str:
    response = session.post(
        build_api_url(ctx, path),
        json=payload,
        timeout=ctx.endpoint.timeout_seconds,
    )
    response.raise_for_status()

    content_type = (response.headers.get("Content-Type") or "").lower()
    if "application/json" in content_type:
        body = response.json()
        if isinstance(body, dict):
            for key in ("transactionBytes", "unsignedTransactionBytes", "rawTransactionBytes"):
                value = str(body.get(key, "") or "").strip()
                if value:
                    return value
        if isinstance(body, str):
            return body.strip()
    return (response.text or "").strip().strip('"')


def get_recommended_fee(ctx: AppContext, unsigned_tx: str, session: requests.Session) -> Decimal:
    def parse_fee_value(raw_value: Any) -> Decimal:
        text = str(raw_value).strip().strip('"')
        if not text:
            raise RuntimeError("Node returned an empty recommended fee.")

        value = Decimal(text)
        # Core /transactions/fee response is int64 in atomic units (1e-8 QORT).
        if "." in text or "e" in text.lower():
            return value
        return value / Decimal("100000000")

    response = session.post(
        build_api_url(ctx, "/transactions/fee"),
        data=unsigned_tx,
        headers={"Content-Type": "text/plain"},
        timeout=ctx.endpoint.timeout_seconds,
    )
    response.raise_for_status()

    content_type = (response.headers.get("Content-Type") or "").lower()
    if "application/json" in content_type:
        body = response.json()
        if isinstance(body, dict):
            for key in ("recommendedFee", "fee", "value"):
                value = body.get(key)
                if value is not None:
                    return parse_fee_value(value)
        if isinstance(body, str):
            return parse_fee_value(body)

    text = (response.text or "").strip().strip('"')
    return parse_fee_value(text)


def sign_tx(ctx: AppContext, unsigned_tx: str, session: requests.Session) -> str:
    response = session.post(
        build_api_url(ctx, "/transactions/sign"),
        json={"privateKey": ctx.account.private_key, "transactionBytes": unsigned_tx},
        timeout=ctx.endpoint.timeout_seconds,
    )
    response.raise_for_status()
    content_type = (response.headers.get("Content-Type") or "").lower()
    if "application/json" in content_type:
        body = response.json()
        return (body.get("transactionBytes") or "").strip()
    return (response.text or "").strip()


def process_tx(ctx: AppContext, signed_tx: str, session: requests.Session) -> Any:
    response = session.post(
        build_api_url(ctx, "/transactions/process"),
        data=signed_tx,
        headers={"Content-Type": "text/plain"},
        timeout=ctx.endpoint.timeout_seconds,
    )
    response.raise_for_status()
    try:
        return response.json()
    except Exception:
        return (response.text or "").strip()


def fetch_node_snapshot(ctx: AppContext) -> Dict[str, Any]:
    with make_session(ctx, include_api_key=False) as session:
        info = request_json(ctx, session, "GET", "/admin/info")
        status = request_json(ctx, session, "GET", "/admin/status")
        height = status.get("height")

    return {
        "info": info,
        "status": status,
        "height": height,
    }


def get_chat_messages(
    ctx: AppContext,
    session: requests.Session,
    *,
    tx_group_id: int = 0,
    limit: int = 40,
    offset: int = 0,
    reverse: bool = True,
    encoding: str = "BASE64",
) -> List[Dict[str, Any]]:
    response = session.get(
        build_api_url(ctx, "/chat/messages"),
        params={
            "txGroupId": tx_group_id,
            "encoding": encoding,
            "limit": max(1, int(limit)),
            "offset": max(0, int(offset)),
            "reverse": str(bool(reverse)).lower(),
        },
        timeout=ctx.endpoint.timeout_seconds,
    )
    response.raise_for_status()

    data = response.json()
    if isinstance(data, list):
        return data
    return []




def get_unconfirmed_chat_messages(
    ctx: AppContext,
    session: requests.Session,
    *,
    tx_group_id: int = 0,
    limit: int = 40,
) -> List[Dict[str, Any]]:
    response = session.get(
        build_api_url(ctx, "/transactions/unconfirmed"),
        timeout=ctx.endpoint.timeout_seconds,
    )
    response.raise_for_status()

    rows = response.json()
    if not isinstance(rows, list):
        return []

    chats: List[Dict[str, Any]] = []
    for row in rows:
        if str(row.get("type", "")).upper() != "CHAT":
            continue

        try:
            if int(row.get("txGroupId", -1)) != int(tx_group_id):
                continue
        except Exception:
            continue

        chats.append(
            {
                "timestamp": row.get("timestamp"),
                "sender": row.get("sender") or row.get("creatorAddress"),
                "senderName": row.get("senderName") or row.get("sender") or row.get("creatorAddress"),
                "recipient": row.get("recipient") or "",
                "data": row.get("data") or "",
                "encoding": "BASE58",
                "isEncrypted": bool(row.get("isEncrypted", False)),
                "signature": row.get("signature") or "",
                "_unconfirmed": True,
            }
        )

    chats.sort(key=lambda item: int(item.get("timestamp") or 0))
    if limit > 0:
        chats = chats[-int(limit):]
    return chats
