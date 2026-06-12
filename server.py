"""
FastAPI backend — runs locally on port 8765.
All AI calls are native asyncio via httpx, no threading hacks.
"""
import asyncio
import json
import httpx
from fastapi import FastAPI
from fastapi.responses import StreamingResponse, JSONResponse

from config import (
    ALL_MODELS, NVIDIA_BASE_URL, GROQ_BASE_URL,
    NVIDIA_API_KEY, GROQ_API_KEY,
    AI_TIMEOUT_SEC, MAX_TOKENS, REASONING_TOKENS, COINS,
)

app = FastAPI()

# ── Bybit ─────────────────────────────────────────────────────────────────────

async def _bybit_ticker(client: httpx.AsyncClient, symbol: str, category: str = "linear") -> dict | None:
    categories = (category, "spot" if category == "linear" else "linear")
    for cat in categories:
        try:
            r = await client.get(
                "https://api.bybit.com/v5/market/tickers",
                params={"category": cat, "symbol": symbol},
                timeout=5.0,
            )
            d = r.json()
            if d.get("retCode") == 0 and d["result"]["list"]:
                it = d["result"]["list"][0]
                return {
                    "symbol":     symbol,
                    "category":   cat,
                    "price":      float(it["lastPrice"]),
                    "change_24h": float(it["price24hPcnt"]) * 100,
                    "high_24h":   float(it["highPrice24h"]),
                    "low_24h":    float(it["lowPrice24h"]),
                }
        except Exception:
            continue
    return None


async def _bybit_kline_change(client: httpx.AsyncClient, symbol: str, category: str) -> float:
    for cat in (category, "spot" if category == "linear" else "linear"):
        try:
            r = await client.get(
                "https://api.bybit.com/v5/market/kline",
                params={"category": cat, "symbol": symbol, "interval": "60", "limit": 2},
                timeout=5.0,
            )
            d = r.json()
            if d.get("retCode") == 0:
                candles = d["result"]["list"]
                if len(candles) >= 2:
                    op = float(candles[1][1])
                    cl = float(candles[0][4])
                    return (cl - op) / op * 100 if op > 0 else 0.0
        except Exception:
            continue
    return 0.0


async def get_market(coin: str, category: str = "linear") -> dict | None:
    symbol = COINS.get(coin)
    if not symbol:
        return None
    async with httpx.AsyncClient() as client:
        ticker = await _bybit_ticker(client, symbol, category)
        if not ticker:
            return None
        ch1h = await _bybit_kline_change(client, symbol, ticker["category"])
    ticker["change_1h"] = ch1h
    return ticker


# ── AI models ─────────────────────────────────────────────────────────────────

def _build_prompt(market: dict) -> str:
    return (
        "Analyze the following technical market metrics and classify the short-term sentiment momentum. "
        "Choose and output exactly one word from this list: BUY, SELL, or HOLD. "
        "Do not write any introductory text, reasoning, or financial disclaimers. Output only the single chosen word.\n"
        f"Symbol: {market['symbol']}\n"
        f"Current Price: {market['price']}\n"
        f"24h change: {market['change_24h']:+.2f}%\n"
        f"1h change: {market['change_1h']:+.2f}%\n"
        f"High: {market['high_24h']}\n"
        f"Low: {market['low_24h']}\n"
        "Momentum Classification:"
    )


def _parse(text: str) -> str:
    import re
    # strip <think>...</think> blocks (reasoning models)
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    text = text.strip().upper()
    for w in text.split():
        w = w.strip(".,!?:()\n")
        if w in ("BUY", "SELL", "HOLD"):
            return w
    for s in ("BUY", "SELL", "HOLD"):
        if s in text:
            return s
    return "?"


async def query_model(client: httpx.AsyncClient, model: dict, market: dict) -> dict:
    import time
    provider = model["provider"]
    url      = NVIDIA_BASE_URL if provider == "nvidia" else GROQ_BASE_URL
    api_key  = NVIDIA_API_KEY  if provider == "nvidia" else GROQ_API_KEY

    if not api_key:
        return {"model": model["name"], "signal": "NO KEY", "latency_ms": 0, "ok": False}

    is_reasoning = model.get("is_reasoning", False)
    payload = {
        "model":       model["id"],
        "messages":    [{"role": "user", "content": _build_prompt(market)}],
        "max_tokens":  REASONING_TOKENS if is_reasoning else MAX_TOKENS,
        "temperature": 0.1,
        "stream":      False,
    }
    t0 = time.monotonic()
    try:
        resp = await client.post(
            url, json=payload,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            timeout=AI_TIMEOUT_SEC,
        )
        elapsed = round((time.monotonic() - t0) * 1000)
        if resp.status_code != 200:
            try:
                err_body = resp.json()
                err = err_body.get("error", {}).get("message", resp.text[:80])
            except Exception:
                err = resp.text[:80]
            return {"model": model["name"], "signal": "ERR", "latency_ms": elapsed,
                    "ok": False, "err": str(err)[:60]}
        data   = resp.json()
        text   = data["choices"][0]["message"]["content"]
        signal = _parse(text)
        return {"model": model["name"], "signal": signal, "latency_ms": elapsed, "ok": True}
    except httpx.TimeoutException:
        elapsed = round((time.monotonic() - t0) * 1000)
        return {"model": model["name"], "signal": "TIMEOUT", "latency_ms": elapsed, "ok": False}
    except Exception as e:
        return {"model": model["name"], "signal": "ERR", "latency_ms": 0,
                "ok": False, "err": str(e)[:60]}


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"ok": True}


@app.get("/market/{coin}")
async def market_route(coin: str, category: str = "linear"):
    data = await get_market(coin, category)
    return JSONResponse(data or {"error": "not found"})


@app.get("/analyze/{coin}")
async def analyze(coin: str, category: str = "linear"):
    """
    SSE stream — emits events as each model responds.
    Client reads line-by-line: lines starting with 'data: ' contain JSON.
    """
    async def event_stream():
        # 1. market data
        market = await get_market(coin, category)
        if not market:
            yield f"data: {json.dumps({'type': 'error', 'coin': coin, 'msg': 'No market data'})}\n\n"
            return
        yield f"data: {json.dumps({'type': 'market', 'coin': coin, 'data': market})}\n\n"

        # 2. all models in parallel — yield each result as soon as it arrives
        async with httpx.AsyncClient() as client:
            tasks = {
                asyncio.ensure_future(query_model(client, m, market)): m
                for m in ALL_MODELS
            }
            pending = set(tasks.keys())
            while pending:
                done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
                for fut in done:
                    result = fut.result()
                    yield f"data: {json.dumps({'type': 'signal', 'coin': coin, 'result': result})}\n\n"

        yield f"data: {json.dumps({'type': 'done', 'coin': coin})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

