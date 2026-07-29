"""Read-only Qortal-node access used for QORT wallet information.

Qortium does not have a native coin. QORT belongs to the separate Qortal
network, so these requests must never be sent to the configured Qortium Core.
The candidate order and health checks mirror Qortium Home's Qortal bridge.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from urllib.parse import quote

import requests


QORTAL_LOCAL_NODE_API_URL = "http://127.0.0.1:12391"
QORTAL_REMOTE_NODE_API_URLS = (
    "https://ext-node.qortal.link",
    "https://api.qortal.org",
)
QORTAL_PUBLIC_READ_PROBE_PATH = (
    "/arbitrary/resources/search"
    "?mode=ALL&limit=1&includestatus=false&includemetadata=false"
)
QORTAL_NODE_CACHE_TTL_SECONDS = 5 * 60
QORTAL_PROBE_TIMEOUT_SECONDS = 5


@dataclass(frozen=True)
class QortalNodeCandidate:
    url: str
    source: str
    requires_synced_status: bool = False
    requires_public_read_probe: bool = False


@dataclass(frozen=True)
class QortBalance:
    amount: Decimal
    node_url: str
    node_source: str


@dataclass(frozen=True)
class QortalJsonResult:
    payload: object
    node_url: str
    node_source: str


_cache_lock = threading.Lock()
_cached_node: tuple[float, QortalNodeCandidate] | None = None


def qortal_node_candidates() -> tuple[QortalNodeCandidate, ...]:
    return (
        QortalNodeCandidate(
            url=QORTAL_LOCAL_NODE_API_URL,
            source="local",
            requires_synced_status=True,
            requires_public_read_probe=True,
        ),
        *(
            QortalNodeCandidate(url=url, source="public")
            for url in QORTAL_REMOTE_NODE_API_URLS
        ),
    )


def _is_synced_qortal_status(payload: object) -> bool:
    if not isinstance(payload, dict):
        return False
    height = payload.get("height")
    sync_percent = payload.get("syncPercent")
    blocks_remaining = payload.get("syncBlocksRemaining")
    return (
        isinstance(height, (int, float))
        and height > 0
        and str(payload.get("syncPhase") or "").strip().upper() == "SYNCED"
        and isinstance(sync_percent, (int, float))
        and sync_percent == 100
        and isinstance(blocks_remaining, (int, float))
        and blocks_remaining == 0
        and payload.get("isSynchronizing") is False
    )


def _probe_candidate(
    session: requests.Session,
    candidate: QortalNodeCandidate,
    timeout_seconds: int,
) -> bool:
    timeout = min(max(1, int(timeout_seconds)), QORTAL_PROBE_TIMEOUT_SECONDS)
    try:
        status_response = session.get(
            f"{candidate.url}/admin/status",
            timeout=timeout,
        )
        if status_response.status_code < 200 or status_response.status_code >= 300:
            return False
        status = status_response.json()
        if candidate.requires_synced_status and not _is_synced_qortal_status(status):
            return False
        if candidate.requires_public_read_probe:
            probe_response = session.get(
                f"{candidate.url}{QORTAL_PUBLIC_READ_PROBE_PATH}",
                timeout=timeout,
            )
            if probe_response.status_code < 200 or probe_response.status_code >= 300:
                return False
        return True
    except (ValueError, requests.RequestException):
        return False


def _invalidate_cached_node(url: str = "") -> None:
    global _cached_node
    with _cache_lock:
        if not url or (_cached_node and _cached_node[1].url == url):
            _cached_node = None


def resolve_qortal_node(
    session: requests.Session,
    timeout_seconds: int,
    *,
    excluded_urls: frozenset[str] = frozenset(),
) -> QortalNodeCandidate:
    global _cached_node

    with _cache_lock:
        cached = _cached_node
    if (
        cached
        and cached[0] > time.monotonic()
        and cached[1].url not in excluded_urls
    ):
        return cached[1]

    for candidate in qortal_node_candidates():
        if candidate.url in excluded_urls:
            continue
        if not _probe_candidate(session, candidate, timeout_seconds):
            continue
        with _cache_lock:
            _cached_node = (
                time.monotonic() + QORTAL_NODE_CACHE_TTL_SECONDS,
                candidate,
            )
        return candidate

    raise RuntimeError("No Qortal node is reachable right now.")


def _parse_qort_balance(response: requests.Response) -> Decimal:
    raw = ""
    try:
        payload = response.json()
        if isinstance(payload, dict) and "value" in payload:
            raw = str(payload["value"])
        elif isinstance(payload, (int, float, str)) and not isinstance(payload, bool):
            raw = str(payload)
    except (ValueError, requests.JSONDecodeError):
        pass
    if not raw:
        raw = (response.text or "").strip().strip('"')
    try:
        amount = Decimal(raw)
    except InvalidOperation as exc:
        raise ValueError("Qortal balance response was not a decimal amount.") from exc
    if not amount.is_finite():
        raise ValueError("Qortal balance response was not a finite amount.")
    return amount


def fetch_qort_balance(
    address: str,
    timeout_seconds: int,
    *,
    session: requests.Session | None = None,
) -> QortBalance:
    """Fetch QORT from Qortal, preferring a synced local Qortal node."""

    normalized_address = str(address or "").strip()
    if not normalized_address:
        raise ValueError("A Qortal account address is required.")

    owns_session = session is None
    active_session = session or requests.Session()
    active_session.headers.update(
        {
            "Accept": "text/plain,application/json",
            "Connection": "keep-alive",
        }
    )
    excluded_urls: set[str] = set()
    last_error: Exception | None = None

    try:
        for _ in qortal_node_candidates():
            try:
                candidate = resolve_qortal_node(
                    active_session,
                    timeout_seconds,
                    excluded_urls=frozenset(excluded_urls),
                )
            except RuntimeError:
                if last_error is not None:
                    break
                raise
            try:
                response = active_session.get(
                    f"{candidate.url}/addresses/balance/"
                    f"{quote(normalized_address, safe='')}",
                    timeout=max(1, int(timeout_seconds)),
                )
                response.raise_for_status()
                return QortBalance(
                    amount=_parse_qort_balance(response),
                    node_url=candidate.url,
                    node_source=candidate.source,
                )
            except (ValueError, requests.RequestException) as exc:
                last_error = exc
                excluded_urls.add(candidate.url)
                _invalidate_cached_node(candidate.url)
    finally:
        if owns_session:
            active_session.close()

    if last_error is not None:
        raise RuntimeError(f"QORT balance lookup failed: {last_error}") from last_error
    raise RuntimeError("No Qortal node is reachable right now.")


def fetch_qortal_json(
    path: str,
    timeout_seconds: int,
    *,
    params: dict[str, object] | None = None,
    session: requests.Session | None = None,
) -> QortalJsonResult:
    """Run a read-only JSON request against the Qortal bridge candidates."""

    normalized_path = "/" + str(path or "").strip().lstrip("/")
    owns_session = session is None
    active_session = session or requests.Session()
    active_session.headers.update(
        {
            "Accept": "application/json,text/plain",
            "Connection": "keep-alive",
        }
    )
    excluded_urls: set[str] = set()
    last_error: Exception | None = None

    try:
        for _ in qortal_node_candidates():
            try:
                candidate = resolve_qortal_node(
                    active_session,
                    timeout_seconds,
                    excluded_urls=frozenset(excluded_urls),
                )
            except RuntimeError:
                if last_error is not None:
                    break
                raise
            try:
                response = active_session.get(
                    f"{candidate.url}{normalized_path}",
                    params=params,
                    timeout=max(1, int(timeout_seconds)),
                )
                response.raise_for_status()
                payload = response.json()
                if isinstance(payload, dict):
                    if isinstance(payload.get("data"), list):
                        payload = payload["data"]
                    elif "value" in payload and len(payload) == 1:
                        payload = payload["value"]
                return QortalJsonResult(
                    payload=payload,
                    node_url=candidate.url,
                    node_source=candidate.source,
                )
            except (ValueError, requests.RequestException) as exc:
                last_error = exc
                excluded_urls.add(candidate.url)
                _invalidate_cached_node(candidate.url)
    finally:
        if owns_session:
            active_session.close()

    if last_error is not None:
        raise RuntimeError(f"Qortal read failed: {last_error}") from last_error
    raise RuntimeError("No Qortal node is reachable right now.")
