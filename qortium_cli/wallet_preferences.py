"""Persistent presentation preferences for the wallet workspace."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path


FIAT_CURRENCIES: tuple[tuple[str, str], ...] = (
    ("usd", "USD - US Dollar"),
    ("eur", "EUR - Euro"),
    ("gbp", "GBP - British Pound"),
    ("jpy", "JPY - Japanese Yen"),
    ("aud", "AUD - Australian Dollar"),
    ("cad", "CAD - Canadian Dollar"),
    ("chf", "CHF - Swiss Franc"),
    ("cny", "CNY - Chinese Yuan"),
    ("inr", "INR - Indian Rupee"),
    ("krw", "KRW - South Korean Won"),
    ("brl", "BRL - Brazilian Real"),
    ("mxn", "MXN - Mexican Peso"),
    ("sgd", "SGD - Singapore Dollar"),
    ("hkd", "HKD - Hong Kong Dollar"),
    ("nok", "NOK - Norwegian Krone"),
    ("sek", "SEK - Swedish Krona"),
)
FIAT_CURRENCY_CODES = frozenset(code for code, _ in FIAT_CURRENCIES)

SORT_MODES: tuple[tuple[str, str], ...] = (
    ("default", "Wallet app order"),
    ("name-asc", "Name A to Z"),
    ("name-desc", "Name Z to A"),
    ("value-desc", "Fiat value high to low"),
    ("value-asc", "Fiat value low to high"),
)
SORT_MODE_KEYS = frozenset(key for key, _ in SORT_MODES)


@dataclass(frozen=True)
class WalletPreferences:
    currency: str = "usd"
    sort_mode: str = "default"
    hide_zero: bool = False


def wallet_preferences_path(settings_dir: Path) -> Path:
    return settings_dir / "wallet_settings.json"


def load_wallet_preferences(settings_dir: Path) -> WalletPreferences:
    path = wallet_preferences_path(settings_dir)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return WalletPreferences()
    if not isinstance(payload, dict):
        return WalletPreferences()

    currency = str(payload.get("currency") or "").strip().lower()
    sort_mode = str(payload.get("sort_mode") or "").strip().lower()
    return WalletPreferences(
        currency=currency if currency in FIAT_CURRENCY_CODES else "usd",
        sort_mode=sort_mode if sort_mode in SORT_MODE_KEYS else "default",
        hide_zero=payload.get("hide_zero") is True,
    )


def write_wallet_preferences(
    settings_dir: Path,
    preferences: WalletPreferences,
) -> None:
    settings_dir.mkdir(parents=True, exist_ok=True)
    wallet_preferences_path(settings_dir).write_text(
        json.dumps(asdict(preferences), indent=2) + "\n",
        encoding="utf-8",
    )
