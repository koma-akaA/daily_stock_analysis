"""Read-only Coinbase spot data. Crypto identity never passes through stock parsing."""

from datetime import datetime, timedelta, timezone
import math

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


CRYPTO_PRODUCTS = {"BTC": "BTC-USD", "ETH": "ETH-USD"}
COINGECKO_IDS = {"BTC": "bitcoin", "ETH": "ethereum"}


class CryptoFetcher:
    """Public GET endpoints only: no account, wallet, order or private API access."""

    def __init__(self, session=None):
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": "DSA-personal-research/1.0"})
        self.session.mount("https://", HTTPAdapter(max_retries=Retry(
            total=2, backoff_factor=1, status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=("GET",), respect_retry_after_header=False,
        )))

    def daily(self, symbol, now=None):
        product = CRYPTO_PRODUCTS[symbol]  # Reject CRCL and every unregistered token.
        now = now or datetime.now(timezone.utc)
        end = now.astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        response = self.session.get(
            f"https://api.exchange.coinbase.com/products/{product}/candles",
            params={"granularity": 86400, "start": (end - timedelta(days=180)).isoformat(),
                    "end": end.isoformat()}, timeout=(5, 20),
        )
        response.raise_for_status()
        raw = response.json()
        if not isinstance(raw, list) or not raw or any(len(row) != 6 for row in raw):
            raise ValueError("Invalid Coinbase candles")
        df = pd.DataFrame(raw, columns=["time", "low", "high", "open", "close", "volume"])
        df["date"] = pd.to_datetime(df["time"], unit="s", utc=True)
        # Exclude the still-open UTC daily candle; never call partial-day volume a daily signal.
        df = df[(df.date >= end - timedelta(days=180)) & (df.date < end)]
        df = df.sort_values("date").drop_duplicates("date").reset_index(drop=True)
        if df.empty or df.iloc[-1].date.date() != (end - timedelta(days=1)).date():
            raise ValueError("Stale Coinbase daily data")
        if not df.date.diff().iloc[1:].eq(pd.Timedelta(days=1)).all():
            raise ValueError("Coinbase daily data has gaps")
        return df[["date", "open", "high", "low", "close", "volume"]]

    def quote(self, symbol, now=None):
        now = now or datetime.now(timezone.utc)
        product = CRYPTO_PRODUCTS[symbol]
        root = f"https://api.exchange.coinbase.com/products/{product}"
        ticker_response = self.session.get(root + "/ticker", timeout=(5, 15))
        ticker_response.raise_for_status()
        ticker = ticker_response.json()
        stamp = datetime.fromisoformat(ticker["time"].replace("Z", "+00:00"))
        if abs((now - stamp).total_seconds()) > 900:
            raise ValueError("Stale Coinbase spot quote")
        price = float(ticker["price"])
        if not math.isfinite(price) or price <= 0:
            raise ValueError("Invalid Coinbase spot price")
        result = {"price": price, "as_of": stamp.isoformat(), "change_pct": None,
                  "source": root + "/ticker", "basis": "Coinbase现货最新成交；24小时涨跌"}
        # A missing stats response must not discard an otherwise valid current quote.
        try:
            stats_response = self.session.get(root + "/stats", timeout=(5, 15))
            stats_response.raise_for_status()
            opening = float(stats_response.json()["open"])
            if math.isfinite(opening) and opening > 0:
                result["change_pct"] = (price / opening - 1) * 100
        except (requests.RequestException, ValueError, KeyError, TypeError):
            pass
        return result

    def market_cap(self, symbol, demo_key):
        if not demo_key:
            return None
        response = self.session.get(
            "https://api.coingecko.com/api/v3/coins/markets",
            params={"vs_currency": "usd", "ids": COINGECKO_IDS[symbol]},
            headers={"x-cg-demo-api-key": demo_key}, timeout=(5, 15),
        )
        response.raise_for_status()
        rows = response.json()
        if len(rows) != 1 or rows[0].get("id") != COINGECKO_IDS[symbol]:
            raise ValueError("CoinGecko identity mismatch")
        return {"market_cap": rows[0].get("market_cap"), "as_of": rows[0].get("last_updated"),
                "source": "https://www.coingecko.com/en/coins/" + COINGECKO_IDS[symbol]}
