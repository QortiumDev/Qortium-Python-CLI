"""Low-volume CoinGecko market prices for the wallet portfolio."""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Iterable

import requests


COINGECKO_SIMPLE_PRICE_URL = "https://api.coingecko.com/api/v3/simple/price"
COINGECKO_IDS: dict[str, str] = {
    "ARRR": "pirate-chain",
    "BTC": "bitcoin",
    "DASH": "dash",
    "DGB": "digibyte",
    "DOGE": "dogecoin",
    "FIRO": "zcoin",
    "LTC": "litecoin",
    "NMC": "namecoin",
    "RVN": "ravencoin",
}
MARKET_CACHE_TTL_SECONDS = 10 * 60


@dataclass(frozen=True)
class MarketQuote:
    ticker: str
    currency: str
    price: Decimal
    change_24h: Decimal | None = None
    last_updated_at: int | None = None


@dataclass(frozen=True)
class MarketSnapshot:
    quotes: dict[str, MarketQuote]
    currency: str
    fetched_at: float
    error: str = ""
    stale: bool = False


_cache_lock = threading.Lock()
_market_cache: dict[tuple[tuple[str, ...], str], MarketSnapshot] = {}


def _decimal(value: object) -> Decimal | None:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return parsed if parsed.is_finite() else None


def _cache_key(tickers: Iterable[str], currency: str) -> tuple[tuple[str, ...], str]:
    supported = tuple(
        sorted(
            {
                str(ticker or "").strip().upper()
                for ticker in tickers
                if str(ticker or "").strip().upper() in COINGECKO_IDS
            }
        )
    )
    return supported, str(currency or "usd").strip().lower()


def fetch_market_prices(
    tickers: Iterable[str],
    currency: str = "usd",
    *,
    force: bool = False,
    timeout_seconds: int = 20,
    session: requests.Session | None = None,
) -> MarketSnapshot:
    """Fetch one batched price request, with a ten-minute in-memory cache."""

    key = _cache_key(tickers, currency)
    supported, normalized_currency = key
    now = time.time()
    with _cache_lock:
        cached = _market_cache.get(key)
    if cached and not force and now - cached.fetched_at < MARKET_CACHE_TTL_SECONDS:
        return cached
    if not supported:
        return MarketSnapshot({}, normalized_currency, now)

    owns_session = session is None
    active_session = session or requests.Session()
    headers = {"Accept": "application/json"}
    demo_key = os.environ.get("QORTIUM_CLI_COINGECKO_API_KEY", "").strip()
    if demo_key:
        headers["x-cg-demo-api-key"] = demo_key

    try:
        response = active_session.get(
            COINGECKO_SIMPLE_PRICE_URL,
            params={
                "ids": ",".join(sorted(COINGECKO_IDS[ticker] for ticker in supported)),
                "vs_currencies": normalized_currency,
                "include_24hr_change": "true",
                "include_last_updated_at": "true",
            },
            headers=headers,
            timeout=min(max(1, int(timeout_seconds)), 30),
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("CoinGecko returned an unexpected response.")

        quotes: dict[str, MarketQuote] = {}
        for ticker in supported:
            entry = payload.get(COINGECKO_IDS[ticker])
            if not isinstance(entry, dict):
                continue
            price = _decimal(entry.get(normalized_currency))
            if price is None:
                continue
            change = _decimal(entry.get(f"{normalized_currency}_24h_change"))
            raw_updated = entry.get("last_updated_at")
            updated = int(raw_updated) if isinstance(raw_updated, (int, float)) else None
            quotes[ticker] = MarketQuote(
                ticker=ticker,
                currency=normalized_currency,
                price=price,
                change_24h=change,
                last_updated_at=updated,
            )

        snapshot = MarketSnapshot(
            quotes=quotes,
            currency=normalized_currency,
            fetched_at=now,
        )
        with _cache_lock:
            _market_cache[key] = snapshot
        return snapshot
    except (ValueError, requests.RequestException) as exc:
        if cached:
            return MarketSnapshot(
                quotes=cached.quotes,
                currency=cached.currency,
                fetched_at=cached.fetched_at,
                error=str(exc),
                stale=True,
            )
        return MarketSnapshot({}, normalized_currency, now, error=str(exc))
    finally:
        if owns_session:
            active_session.close()
