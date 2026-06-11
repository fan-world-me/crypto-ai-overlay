import asyncio
import aiohttp
from config import COINS

BYBIT_TICKER_URL = "https://api.bybit.com/v5/market/tickers"
BYBIT_KLINE_URL  = "https://api.bybit.com/v5/market/kline"


async def fetch_ticker(session: aiohttp.ClientSession, symbol: str) -> dict | None:
    try:
        async with session.get(
            BYBIT_TICKER_URL,
            params={"category": "spot", "symbol": symbol},
            timeout=aiohttp.ClientTimeout(total=3),
        ) as resp:
            data = await resp.json()
            if data.get("retCode") == 0:
                item = data["result"]["list"][0]
                return {
                    "symbol":     symbol,
                    "price":      float(item["lastPrice"]),
                    "change_24h": float(item["price24hPcnt"]) * 100,
                    "high_24h":   float(item["highPrice24h"]),
                    "low_24h":    float(item["lowPrice24h"]),
                    "volume_24h": float(item["volume24h"]),
                }
    except Exception:
        return None


async def fetch_kline_change(session: aiohttp.ClientSession, symbol: str, interval: str = "60", limit: int = 2) -> float:
    """Returns % change over the last `interval`-minute candle."""
    try:
        async with session.get(
            BYBIT_KLINE_URL,
            params={"category": "spot", "symbol": symbol, "interval": interval, "limit": limit},
            timeout=aiohttp.ClientTimeout(total=3),
        ) as resp:
            data = await resp.json()
            if data.get("retCode") == 0:
                candles = data["result"]["list"]
                if len(candles) >= 2:
                    open_price  = float(candles[1][1])
                    close_price = float(candles[0][4])
                    if open_price > 0:
                        return (close_price - open_price) / open_price * 100
    except Exception:
        pass
    return 0.0


async def get_market_data(coin: str) -> dict | None:
    symbol = COINS.get(coin)
    if not symbol:
        return None
    async with aiohttp.ClientSession() as session:
        ticker, change_1h = await asyncio.gather(
            fetch_ticker(session, symbol),
            fetch_kline_change(session, symbol, interval="60"),
        )
    if ticker:
        ticker["change_1h"] = change_1h
    return ticker
