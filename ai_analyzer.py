import asyncio
import time
import aiohttp
from config import (
    ALL_MODELS, NVIDIA_BASE_URL, GROQ_BASE_URL,
    NVIDIA_API_KEY, GROQ_API_KEY, AI_TIMEOUT_SEC, MAX_TOKENS,
)


def build_prompt(market: dict) -> str:
    return (
        f"Crypto trading signal. Answer with ONE word only: BUY, SELL, or HOLD.\n"
        f"Coin: {market['symbol']}\n"
        f"Price: ${market['price']:,.4f}\n"
        f"24h change: {market['change_24h']:+.2f}%\n"
        f"1h change: {market['change_1h']:+.2f}%\n"
        f"24h high: ${market['high_24h']:,.4f}  low: ${market['low_24h']:,.4f}\n"
        f"Signal:"
    )


async def query_model(
    session: aiohttp.ClientSession,
    model: dict,
    prompt: str,
) -> dict:
    provider = model["provider"]
    url      = NVIDIA_BASE_URL if provider == "nvidia" else GROQ_BASE_URL
    api_key  = NVIDIA_API_KEY  if provider == "nvidia" else GROQ_API_KEY

    payload = {
        "model": model["id"],
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": MAX_TOKENS,
        "temperature": 0.1,
        "stream": False,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type":  "application/json",
    }

    t0 = time.monotonic()
    try:
        async with session.post(
            url,
            json=payload,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=AI_TIMEOUT_SEC),
        ) as resp:
            data    = await resp.json()
            elapsed = (time.monotonic() - t0) * 1000
            text    = data["choices"][0]["message"]["content"].strip().upper()
            signal  = _parse_signal(text)
            return {"model": model["name"], "signal": signal, "latency_ms": round(elapsed), "ok": True}
    except asyncio.TimeoutError:
        return {"model": model["name"], "signal": "TIMEOUT", "latency_ms": round(AI_TIMEOUT_SEC * 1000), "ok": False}
    except Exception as e:
        return {"model": model["name"], "signal": "ERROR",   "latency_ms": 0, "ok": False, "err": str(e)}


def _parse_signal(text: str) -> str:
    for word in text.split():
        word = word.strip(".,!?:")
        if word in ("BUY", "SELL", "HOLD"):
            return word
    if "BUY"  in text: return "BUY"
    if "SELL" in text: return "SELL"
    if "HOLD" in text: return "HOLD"
    return "?"


async def analyze(market: dict) -> dict:
    """Fire all models in parallel, return majority vote + individual results."""
    prompt = build_prompt(market)

    async with aiohttp.ClientSession() as session:
        tasks   = [query_model(session, m, prompt) for m in ALL_MODELS]
        results = await asyncio.gather(*tasks)

    votes  = [r["signal"] for r in results if r["signal"] in ("BUY", "SELL", "HOLD")]
    buy    = votes.count("BUY")
    sell   = votes.count("SELL")
    hold   = votes.count("HOLD")
    total  = len(votes) or 1

    if buy > sell and buy > hold:
        verdict, confidence = "BUY",  round(buy  / total * 100)
    elif sell > buy and sell > hold:
        verdict, confidence = "SELL", round(sell / total * 100)
    else:
        verdict, confidence = "HOLD", round(hold / total * 100)

    return {
        "verdict":    verdict,
        "confidence": confidence,
        "votes":      {"BUY": buy, "SELL": sell, "HOLD": hold},
        "results":    list(results),
        "responded":  len(votes),
        "total":      len(ALL_MODELS),
    }
