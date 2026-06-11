"""
Each model runs its own independent async loop.
As soon as a response arrives the callback fires — no waiting for others.
"""
import asyncio
import time
import aiohttp
from config import (
    ALL_MODELS, NVIDIA_BASE_URL, GROQ_BASE_URL,
    NVIDIA_API_KEY, GROQ_API_KEY, AI_TIMEOUT_SEC, MAX_TOKENS,
)


def build_prompt(market: dict) -> str:
    return (
        "You are a crypto trading signal bot. "
        "Reply with ONE word only — BUY, SELL, or HOLD — no explanation.\n"
        f"Coin: {market['symbol']}\n"
        f"Price: ${market['price']:,.4f}\n"
        f"24h: {market['change_24h']:+.2f}%  1h: {market['change_1h']:+.2f}%\n"
        f"High: ${market['high_24h']:,.4f}  Low: ${market['low_24h']:,.4f}\n"
        "Signal:"
    )


def _parse_signal(text: str) -> str:
    text = text.strip().upper()
    for word in text.split():
        w = word.strip(".,!?:")
        if w in ("BUY", "SELL", "HOLD"):
            return w
    if "BUY"  in text: return "BUY"
    if "SELL" in text: return "SELL"
    if "HOLD" in text: return "HOLD"
    return "?"


async def query_once(session: aiohttp.ClientSession, model: dict, market: dict) -> dict:
    """Single query to one model. Returns result dict immediately."""
    provider = model["provider"]
    url      = NVIDIA_BASE_URL if provider == "nvidia" else GROQ_BASE_URL
    api_key  = NVIDIA_API_KEY  if provider == "nvidia" else GROQ_API_KEY

    if not api_key:
        return {"model": model["name"], "signal": "NO KEY", "latency_ms": 0, "ok": False}

    payload = {
        "model":       model["id"],
        "messages":    [{"role": "user", "content": build_prompt(market)}],
        "max_tokens":  MAX_TOKENS,
        "temperature": 0.1,
        "stream":      False,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type":  "application/json",
    }

    t0 = time.monotonic()
    try:
        async with session.post(
            url, json=payload, headers=headers,
            timeout=aiohttp.ClientTimeout(total=AI_TIMEOUT_SEC),
        ) as resp:
            data    = await resp.json(content_type=None)
            elapsed = (time.monotonic() - t0) * 1000
            if resp.status != 200:
                err = data.get("error", {}).get("message", str(resp.status))
                return {"model": model["name"], "signal": "ERR", "latency_ms": round(elapsed), "ok": False, "err": err[:40]}
            text   = data["choices"][0]["message"]["content"]
            signal = _parse_signal(text)
            return {"model": model["name"], "signal": signal, "latency_ms": round(elapsed), "ok": True}
    except asyncio.TimeoutError:
        elapsed = (time.monotonic() - t0) * 1000
        return {"model": model["name"], "signal": "TIMEOUT", "latency_ms": round(elapsed), "ok": False}
    except Exception as e:
        return {"model": model["name"], "signal": "ERR", "latency_ms": 0, "ok": False, "err": str(e)[:40]}


def majority_signal(results: dict) -> tuple[str, int]:
    """Given {model_name: result_dict}, return (verdict, confidence_pct)."""
    votes = [r["signal"] for r in results.values() if r["signal"] in ("BUY", "SELL", "HOLD")]
    if not votes:
        return "—", 0
    buy  = votes.count("BUY")
    sell = votes.count("SELL")
    hold = votes.count("HOLD")
    total = len(votes)
    if buy >= sell and buy >= hold:
        return "BUY",  round(buy  / total * 100)
    if sell >= buy and sell >= hold:
        return "SELL", round(sell / total * 100)
    return "HOLD", round(hold / total * 100)
