import asyncio
import aiohttp
from config import COINS

BYBIT_TICKER_URL = "https://api.bybit.com/v5/market/tickers"
BYBIT_KLINE_URL  = "https://api.bybit.com/v5/market/kline"


async def fetch_ticker(session: aiohttp.ClientSession, symbol: str) -> dict | None:
    """Try linear (perpetual futures) first — that's the price traders see.
    Fall back to spot if no futures contract exists for the symbol."""
    for category in ("linear", "spot"):
        try:
            async with session.get(
                BYBIT_TICKER_URL,
                params={"category": category, "symbol": symbol},
                timeout=aiohttp.ClientTimeout(total=4),
            ) as resp:
                data = await resp.json(content_type=None)
                if data.get("retCode") == 0 and data["result"]["list"]:
                    item = data["result"]["list"][0]
                    return {
                        "symbol":     symbol,
                        "category":   category,
                        "price":      float(item["lastPrice"]),
                        "change_24h": float(item["price24hPcnt"]) * 100,
                        "high_24h":   float(item["highPrice24h"]),
                        "low_24h":    float(item["lowPrice24h"]),
                        "volume_24h": float(item.get("volume24h", item.get("turnover24h", 0))),
                    }
        except Exception:
            continue
    return None


async def fetch_kline_change(session: aiohttp.ClientSession, symbol: str,
                              category: str = "linear", interval: str = "60") -> float:
    """% change over the last completed 1h candle."""
    for cat in (category, "spot"):
        try:
            async with session.get(
                BYBIT_KLINE_URL,
                params={"category": cat, "symbol": symbol,
                        "interval": interval, "limit": 2},
                timeout=aiohttp.ClientTimeout(total=4),
            ) as resp:
                data = await resp.json(content_type=None)
                if data.get("retCode") == 0:
                    candles = data["result"]["list"]
                    if len(candles) >= 2:
                        open_price  = float(candles[1][1])
                        close_price = float(candles[0][4])
                        if open_price > 0:
                            return (close_price - open_price) / open_price * 100
                    break
        except Exception:
            continue
    return 0.0


async def get_market_data(coin: str) -> dict | None:
    symbol = COINS.get(coin)
    if not symbol:
        return None
    async with aiohttp.ClientSession() as session:
        ticker = await fetch_ticker(session, symbol)
        if not ticker:
            return None
        cat = ticker.get("category", "linear")
        change_1h = await fetch_kline_change(session, symbol, category=cat)
    ticker["change_1h"] = change_1h
    return ticker
