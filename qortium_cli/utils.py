from __future__ import annotations

from decimal import Decimal, ROUND_DOWN
from typing import Any, Dict

import requests

from qortium_cli.constants import C_BAD, C_GOOD, C_WARN, RESET


def d8(value: Decimal) -> str:
    quantized = value.quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)
    return format(quantized, "f")


def qort_to_atomic(value: Decimal) -> int:
    quantized = value.quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)
    return int(quantized * Decimal("100000000"))


def format_uptime(ms: Any) -> str:
    try:
        total_seconds = int(ms) // 1000
    except Exception:
        return "Unknown"

    days, rem = divmod(total_seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, seconds = divmod(rem, 60)
    return f"{days}d {hours}h {minutes}m {seconds}s"


def format_bool(value: Any) -> str:
    if value is True:
        return C_GOOD + "Yes" + RESET
    if value is False:
        return C_BAD + "No" + RESET
    return str(value)


def format_sync_percent(value: Any) -> str:
    try:
        pct = float(value)
    except Exception:
        return str(value)

    text = f"{pct:g}%"
    if pct >= 99.9:
        return C_GOOD + text + RESET
    if pct >= 75:
        return C_WARN + text + RESET
    return C_BAD + text + RESET


def pretty_exception(exc: Exception) -> str:
    if isinstance(exc, requests.exceptions.HTTPError) and exc.response is not None:
        resp = exc.response
        body = (resp.text or "").strip()
        if len(body) > 1000:
            body = body[:1000] + "..."
        return f"HTTP {resp.status_code} from {resp.url}\n{body}"
    if isinstance(exc, requests.exceptions.RequestException):
        return f"Network/request error: {exc}"
    return str(exc)


def message_text_to_doc(message: str) -> Dict[str, Any]:
    lines = (message or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    content = []
    for line in lines:
        if line == "":
            content.append({"type": "paragraph"})
        else:
            content.append(
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": line}],
                }
            )

    return {
        "messageText": {"type": "doc", "content": content},
        "images": [""],
        "repliedTo": "",
        "version": 2,
        "isEdited": 0,
    }
