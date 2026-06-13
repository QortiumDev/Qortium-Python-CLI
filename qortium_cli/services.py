from __future__ import annotations

from decimal import Decimal
from pathlib import Path, PurePosixPath
import shutil
import stat
import tempfile
from typing import Any, Dict, List
from urllib.parse import quote
import zipfile

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


def check_node_connection(base_url: str, timeout_seconds: int) -> tuple[bool, str]:
    timeout = min(max(1, int(timeout_seconds)), 5)
    try:
        response = requests.get(
            f"{base_url}/admin/status",
            headers={"Accept": "application/json,text/plain"},
            timeout=timeout,
        )
        response.raise_for_status()
    except requests.exceptions.Timeout:
        return False, f"Timed out after {timeout} seconds while checking /admin/status."
    except requests.exceptions.ConnectionError as exc:
        return False, f"Connection failed while checking /admin/status: {exc}"
    except requests.exceptions.HTTPError as exc:
        detail = http_error_detail(exc)
        status_code = exc.response.status_code if exc.response is not None else 0
        return False, f"/admin/status returned HTTP {status_code}: {detail}"
    except requests.exceptions.RequestException as exc:
        return False, f"Connection check failed while checking /admin/status: {exc}"

    try:
        status = response.json()
    except Exception:
        return False, "/admin/status responded, but did not return node status JSON."

    if not isinstance(status, dict):
        return False, "/admin/status responded, but did not return node status JSON."

    height = status.get("height", "Unknown")
    sync_percent = status.get("syncPercent", "Unknown")
    return True, f"Node API responded. Height: {height}; sync: {sync_percent}%."


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


def get_group_info(
    ctx: AppContext,
    group_id: int,
    session: requests.Session,
) -> Dict[str, Any]:
    response = session.get(
        build_api_url(ctx, f"/groups/{int(group_id)}"),
        timeout=ctx.endpoint.timeout_seconds,
    )
    response.raise_for_status()
    data = response.json()
    if isinstance(data, dict):
        return data
    return {}


def get_group_invites(
    ctx: AppContext,
    address: str,
    session: requests.Session,
) -> List[Dict[str, Any]]:
    response = session.get(
        build_api_url(ctx, f"/groups/invites/{address}"),
        timeout=ctx.endpoint.timeout_seconds,
    )
    response.raise_for_status()
    data = response.json()
    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)]
    return []


def _flatten_admin_join_request_groups(rows: Any) -> List[Dict[str, Any]]:
    if not isinstance(rows, list):
        return []

    requests: List[Dict[str, Any]] = []
    seen: set[tuple[int, str]] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue

        group = row.get("group")
        join_requests = row.get("joinRequests")
        if not isinstance(group, dict) or not isinstance(join_requests, list):
            continue

        try:
            group_id = int(group.get("groupId", 0))
        except (TypeError, ValueError):
            continue
        if group_id <= 0:
            continue

        group_name = str(group.get("groupName", "") or "").strip()
        for join_request in join_requests:
            if not isinstance(join_request, dict):
                continue
            joiner = str(join_request.get("joiner", "") or "").strip()
            if not joiner:
                continue

            key = (group_id, joiner)
            if key in seen:
                continue
            seen.add(key)
            requests.append(
                {
                    "groupId": group_id,
                    "groupName": group_name,
                    "joiner": joiner,
                }
            )

    return requests


def _get_group_admin_addresses(
    ctx: AppContext,
    group_id: int,
    session: requests.Session,
) -> set[str]:
    response = session.get(
        build_api_url(ctx, f"/groups/members/{int(group_id)}"),
        params={"onlyAdmins": "true", "limit": 0},
        timeout=ctx.endpoint.timeout_seconds,
    )
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict):
        return set()

    members = data.get("groupMembers")
    if not isinstance(members, list):
        members = data.get("members")
    if not isinstance(members, list):
        return set()

    return {
        str(member.get("member", "") or "").strip()
        for member in members
        if isinstance(member, dict) and str(member.get("member", "") or "").strip()
    }


def _get_group_join_requests(
    ctx: AppContext,
    group_id: int,
    session: requests.Session,
) -> List[Dict[str, Any]]:
    response = session.get(
        build_api_url(ctx, f"/groups/joinrequests/{int(group_id)}"),
        timeout=ctx.endpoint.timeout_seconds,
    )
    response.raise_for_status()
    data = response.json()
    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)]
    return []


def get_admin_group_join_requests(
    ctx: AppContext,
    address: str,
    session: requests.Session,
) -> List[Dict[str, Any]]:
    safe_address = quote(address, safe="")
    response = session.get(
        build_api_url(ctx, f"/groups/joinrequests/admin/{safe_address}"),
        timeout=ctx.endpoint.timeout_seconds,
    )
    if response.status_code != 404:
        response.raise_for_status()
        return _flatten_admin_join_request_groups(response.json())

    # Compatibility path for nodes without the aggregate admin endpoint.
    groups_response = session.get(
        build_api_url(ctx, f"/groups/member/{safe_address}"),
        timeout=ctx.endpoint.timeout_seconds,
    )
    groups_response.raise_for_status()
    groups = groups_response.json()
    if not isinstance(groups, list):
        return []

    null_owner = "QdSnUy6sUiEnaN87dWmE92g1uQjrvPgrWG"
    requests: List[Dict[str, Any]] = []
    seen: set[tuple[int, str]] = set()
    for group in groups:
        if not isinstance(group, dict):
            continue
        try:
            group_id = int(group.get("groupId", 0))
        except (TypeError, ValueError):
            continue
        if group_id <= 0:
            continue

        admins = _get_group_admin_addresses(ctx, group_id, session)
        owner = str(group.get("owner", "") or "").strip()
        can_approve = address in admins
        if owner == null_owner and not admins:
            can_approve = True
        if not can_approve:
            continue

        group_name = str(group.get("groupName", "") or "").strip()
        for join_request in _get_group_join_requests(ctx, group_id, session):
            joiner = str(join_request.get("joiner", "") or "").strip()
            if not joiner:
                continue
            key = (group_id, joiner)
            if key in seen:
                continue
            seen.add(key)
            requests.append(
                {
                    "groupId": group_id,
                    "groupName": group_name,
                    "joiner": joiner,
                }
            )

    return requests


def get_name_info(
    ctx: AppContext,
    name: str,
    session: requests.Session,
) -> Dict[str, Any]:
    response = session.get(
        build_api_url(ctx, f"/names/{quote(name, safe='')}"),
        timeout=ctx.endpoint.timeout_seconds,
    )
    response.raise_for_status()
    data = response.json()
    if isinstance(data, dict):
        return data
    return {}


def get_account_names(
    ctx: AppContext,
    address: str,
    session: requests.Session,
    *,
    limit: int = 100,
    offset: int = 0,
) -> List[str]:
    response = session.get(
        build_api_url(ctx, f"/names/address/{quote(address, safe='')}"),
        params={
            "limit": max(1, int(limit)),
            "offset": max(0, int(offset)),
            "reverse": "false",
        },
        timeout=ctx.endpoint.timeout_seconds,
    )
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, list):
        return []

    names: List[str] = []
    for row in data:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name", "") or "").strip()
        if name:
            names.append(name)
    return names


def search_arbitrary_resources(
    ctx: AppContext,
    session: requests.Session,
    *,
    query: str = "",
    service: str = "",
    names: List[str] | None = None,
    limit: int = 20,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    params: Dict[str, Any] = {
        "mode": "LATEST",
        "includestatus": "true",
        "includemetadata": "true",
        "excludeblocked": "false",
        "limit": max(1, int(limit)),
        "offset": max(0, int(offset)),
        "reverse": "true",
    }
    if query:
        params["query"] = query
    if service:
        params["service"] = service
    if names:
        params["name"] = names
        params["exactmatchnames"] = "true"

    response = session.get(
        build_api_url(ctx, "/arbitrary/resources/search"),
        params=params,
        timeout=ctx.endpoint.timeout_seconds,
    )
    response.raise_for_status()
    data = response.json()
    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)]
    return []


def get_hosted_arbitrary_resources(
    ctx: AppContext,
    session: requests.Session,
    *,
    query: str = "",
    limit: int = 100,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    params: Dict[str, Any] = {
        "limit": max(1, int(limit)),
        "offset": max(0, int(offset)),
    }
    if query:
        params["query"] = query

    response = session.get(
        build_api_url(ctx, "/arbitrary/hosted/resources"),
        params=params,
        timeout=ctx.endpoint.timeout_seconds,
    )
    response.raise_for_status()
    data = response.json()
    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)]
    return []


def build_arbitrary_delete(
    ctx: AppContext,
    service: str,
    name: str,
    identifier: str | None,
    fee_atomic: int,
    session: requests.Session,
) -> str:
    service_path = quote(service, safe="")
    name_path = quote(name, safe="")
    if identifier is None:
        path = f"/arbitrary/resource/{service_path}/{name_path}/delete"
    else:
        identifier_path = quote(identifier, safe="")
        path = f"/arbitrary/resource/{service_path}/{name_path}/{identifier_path}/delete"

    response = session.post(
        build_api_url(ctx, path),
        params={"fee": max(0, int(fee_atomic))},
        timeout=ctx.endpoint.timeout_seconds,
    )
    response.raise_for_status()
    return (response.text or "").strip().strip('"')


def delete_local_arbitrary_resource(
    ctx: AppContext,
    service: str,
    name: str,
    identifier: str,
    session: requests.Session,
) -> bool:
    path = (
        f"/arbitrary/resource/{quote(service, safe='')}/"
        f"{quote(name, safe='')}/{quote(identifier, safe='')}"
    )
    response = session.delete(
        build_api_url(ctx, path),
        timeout=ctx.endpoint.timeout_seconds,
    )
    response.raise_for_status()

    try:
        body = response.json()
        if isinstance(body, bool):
            return body
    except Exception:
        pass
    return (response.text or "").strip().lower() == "true"


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


def _extract_zip_safely(archive: zipfile.ZipFile, target_dir: Path) -> None:
    root = target_dir.resolve()

    for member in archive.infolist():
        member_name = member.filename.replace("\\", "/")
        member_path = PurePosixPath(member_name)
        parts = member_path.parts
        if (
            not parts
            or member_path.is_absolute()
            or ".." in parts
            or (len(parts[0]) >= 2 and parts[0][1] == ":")
        ):
            raise RuntimeError(f"Unsafe path in APP zip: {member.filename}")

        unix_mode = member.external_attr >> 16
        file_type = unix_mode & 0o170000
        if file_type == stat.S_IFLNK:
            raise RuntimeError(f"Symbolic links are not allowed in APP zip: {member.filename}")
        if file_type not in (0, stat.S_IFREG, stat.S_IFDIR):
            raise RuntimeError(f"Unsupported entry in APP zip: {member.filename}")

        output_path = target_dir.joinpath(*parts).resolve()
        if output_path != root and root not in output_path.parents:
            raise RuntimeError(f"Unsafe path in APP zip: {member.filename}")

        if member.is_dir():
            output_path.mkdir(parents=True, exist_ok=True)
            continue

        output_path.parent.mkdir(parents=True, exist_ok=True)
        with archive.open(member) as source, output_path.open("wb") as destination:
            shutil.copyfileobj(source, destination)


def _validate_arbitrary_metadata(
    title: str | None,
    description: str | None,
    tags: list[str] | None,
) -> list[str]:
    if title and len(title.encode("utf-8")) > 80:
        raise RuntimeError("QDN title exceeds 80 UTF-8 bytes.")
    if description and len(description.encode("utf-8")) > 240:
        raise RuntimeError("QDN description exceeds 240 UTF-8 bytes.")

    cleaned_tags = [str(tag).strip() for tag in tags or [] if str(tag).strip()]
    if len(cleaned_tags) > 5:
        raise RuntimeError("QDN supports at most 5 tags.")
    for tag in cleaned_tags:
        if len(tag) > 20:
            raise RuntimeError(f"QDN tag exceeds 20 characters: {tag}")
    return cleaned_tags


def build_arbitrary_from_path(
    ctx: AppContext,
    session: requests.Session,
    *,
    service: str,
    name: str,
    local_path: str,
    identifier: str | None = None,
    title: str | None = None,
    description: str | None = None,
    tags: list[str] | None = None,
    category: str | None = None,
    fee_atomic: int | None = None,
    preview: bool = False,
) -> str:
    normalized_service = str(service).strip().upper()
    normalized_name = str(name).strip()
    if not normalized_service:
        raise RuntimeError("QDN service cannot be empty.")
    if not normalized_name:
        raise RuntimeError("Registered name cannot be empty.")

    cleaned_title = str(title or "").strip()
    cleaned_description = str(description or "").strip()
    cleaned_tags = _validate_arbitrary_metadata(
        cleaned_title or None,
        cleaned_description or None,
        tags,
    )

    safe_service = quote(normalized_service, safe="")
    safe_name = quote(normalized_name, safe="")
    identifier_value = str(identifier or "").strip()
    if identifier_value:
        path = f"/arbitrary/{safe_service}/{safe_name}/{quote(identifier_value, safe='')}"
    else:
        path = f"/arbitrary/{safe_service}/{safe_name}"

    params: Dict[str, Any] = {}
    if cleaned_title:
        params["title"] = cleaned_title
    if cleaned_description:
        params["description"] = cleaned_description
    if cleaned_tags:
        params["tags"] = cleaned_tags
    if category:
        params["category"] = str(category).strip().upper()
    if fee_atomic is not None:
        params["fee"] = max(0, int(fee_atomic))
    if preview:
        params["preview"] = "true"

    source_path = Path(str(local_path)).expanduser()
    if not source_path.exists():
        raise RuntimeError(f"Local path does not exist: {source_path}")

    publish_path = source_path.resolve()
    temp_dir = None
    if normalized_service == "APP":
        if source_path.is_file():
            if source_path.suffix.lower() != ".zip":
                raise RuntimeError("APP publish path must be a folder or .zip file.")

            temp_dir = tempfile.TemporaryDirectory(prefix="qortium_cli_app_")
            extract_root = Path(temp_dir.name)
            try:
                with zipfile.ZipFile(source_path) as archive:
                    _extract_zip_safely(archive, extract_root)
            except zipfile.BadZipFile as exc:
                temp_dir.cleanup()
                temp_dir = None
                raise RuntimeError(f"Invalid zip file for APP publish: {source_path}") from exc
            except Exception:
                temp_dir.cleanup()
                temp_dir = None
                raise

            children = [child for child in extract_root.iterdir() if child.name != "__MACOSX"]
            publish_path = extract_root
            if len(children) == 1 and children[0].is_dir():
                publish_path = children[0]
        elif not source_path.is_dir():
            raise RuntimeError("APP publish path must be a folder or .zip file.")

        if not (publish_path / "index.html").is_file():
            if temp_dir is not None:
                temp_dir.cleanup()
                temp_dir = None
            raise RuntimeError(
                "APP publishing requires index.html at the app root "
                "(or inside a single top-level zip folder)."
            )

    try:
        response = session.post(
            build_api_url(ctx, path),
            params=params,
            data=str(publish_path),
            headers={"Content-Type": "text/plain"},
            timeout=ctx.endpoint.timeout_seconds,
        )
        response.raise_for_status()
        return (response.text or "").strip().strip('"')
    finally:
        if temp_dir is not None:
            temp_dir.cleanup()


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
