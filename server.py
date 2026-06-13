"""
FastAPI backend — runs locally on port 8765.
All AI calls are native asyncio via httpx, no threading hacks.
"""
import asyncio
import json
import httpx
import hmac
import hashlib
import time
import os
from fastapi import FastAPI
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel

from config import (
    ALL_MODELS, NVIDIA_BASE_URL, GROQ_BASE_URL,
    NVIDIA_API_KEY, GROQ_API_KEY,
    BYBIT_API_KEY, BYBIT_API_SECRET, BYBIT_USE_TESTNET, BYBIT_BASE_URL, COIN_PRECISION,
    AI_TIMEOUT_SEC, MAX_TOKENS, REASONING_TOKENS, COINS,
)

app = FastAPI()

# ── Indicator Math ────────────────────────────────────────────────────────────

def calculate_sma(prices: list[float], period: int) -> float:
    if len(prices) < period:
        return prices[-1] if prices else 0.0
    return sum(prices[-period:]) / period

def calculate_ema(prices: list[float], period: int) -> list[float]:
    if not prices:
        return []
    k = 2 / (period + 1)
    ema = [prices[0]]
    for price in prices[1:]:
        ema.append(price * k + ema[-1] * (1 - k))
    return ema

def calculate_rsi(prices: list[float], period: int = 14) -> float:
    if len(prices) < period + 1:
        return 50.0
    gains = []
    losses = []
    for i in range(1, len(prices)):
        diff = prices[i] - prices[i - 1]
        if diff >= 0:
            gains.append(diff)
            losses.append(0.0)
        else:
            gains.append(0.0)
            losses.append(-diff)
            
    # Wilder's smoothing
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))

def calculate_macd(prices: list[float]) -> tuple[float, float, float]:
    if len(prices) < 26:
        return 0.0, 0.0, 0.0
    ema12 = calculate_ema(prices, 12)
    ema26 = calculate_ema(prices, 26)
    macd_line = [e12 - e26 for e12, e26 in zip(ema12, ema26)]
    signal_line = calculate_ema(macd_line, 9)
    return macd_line[-1], signal_line[-1], macd_line[-1] - signal_line[-1]


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


async def get_technical_indicators(client: httpx.AsyncClient, symbol: str, category: str) -> dict:
    for cat in (category, "spot" if category == "linear" else "linear"):
        try:
            r = await client.get(
                "https://api.bybit.com/v5/market/kline",
                params={"category": cat, "symbol": symbol, "interval": "60", "limit": 100},
                timeout=5.0,
            )
            d = r.json()
            if d.get("retCode") == 0 and d["result"]["list"]:
                # Candles are returned in descending order (newest first). Reverse them.
                candles = list(reversed(d["result"]["list"]))
                close_prices = [float(c[4]) for c in candles]
                
                rsi = calculate_rsi(close_prices, 14)
                ema9_list = calculate_ema(close_prices, 9)
                ema21_list = calculate_ema(close_prices, 21)
                ema9 = ema9_list[-1] if ema9_list else 0.0
                ema21 = ema21_list[-1] if ema21_list else 0.0
                macd_line, macd_signal, macd_hist = calculate_macd(close_prices)
                
                prev_ema9 = ema9_list[-2] if len(ema9_list) >= 2 else 0.0
                prev_ema21 = ema21_list[-2] if len(ema21_list) >= 2 else 0.0
                
                ema_crossover = "HOLD"
                if prev_ema9 <= prev_ema21 and ema9 > ema21:
                    ema_crossover = "BULLISH CROSSOVER (BUY)"
                elif prev_ema9 >= prev_ema21 and ema9 < ema21:
                    ema_crossover = "BEARISH CROSSOVER (SELL)"
                    
                return {
                    "rsi": round(rsi, 2),
                    "ema9": round(ema9, 2),
                    "ema21": round(ema21, 2),
                    "ema_crossover": ema_crossover,
                    "macd": round(macd_line, 4),
                    "macd_signal": round(macd_signal, 4),
                    "macd_hist": round(macd_hist, 4)
                }
        except Exception:
            continue
    return {}


async def get_market(coin: str, category: str = "linear") -> dict | None:
    symbol = COINS.get(coin)
    if not symbol:
        return None
    async with httpx.AsyncClient() as client:
        ticker = await _bybit_ticker(client, symbol, category)
        if not ticker:
            return None
        cat = ticker["category"]
        ch1h = await _bybit_kline_change(client, symbol, cat)
        indicators = await get_technical_indicators(client, symbol, cat)
    ticker["change_1h"] = ch1h
    ticker["indicators"] = indicators
    return ticker


# ── AI models ─────────────────────────────────────────────────────────────────

def _build_prompt(market: dict) -> str:
    indicators = market.get("indicators", {})
    ind_str = ""
    if indicators:
        ind_str = (
            f"Technical Indicators (1h chart):\n"
            f"- RSI (14): {indicators.get('rsi')} (value < 30 is oversold, > 70 is overbought)\n"
            f"- EMA (9): {indicators.get('ema9')}\n"
            f"- EMA (21): {indicators.get('ema21')}\n"
            f"- EMA Crossover trend: {indicators.get('ema_crossover')}\n"
            f"- MACD Line: {indicators.get('macd')}, Signal Line: {indicators.get('macd_signal')}, Histogram: {indicators.get('macd_hist')}\n\n"
        )
    return (
        "You are an expert crypto trader. Analyze the following technical market metrics and indicators to classify the short-term sentiment momentum.\n"
        "Choose and output exactly one word from this list: BUY, SELL, or HOLD.\n"
        "Do not write any introductory text, reasoning, or financial disclaimers. Output only the single chosen word.\n\n"
        f"Symbol: {market['symbol']}\n"
        f"Current Price: {market['price']}\n"
        f"24h change: {market['change_24h']:+.2f}%\n"
        f"1h change: {market['change_1h']:+.2f}%\n"
        f"High: {market['high_24h']}\n"
        f"Low: {market['low_24h']}\n"
        f"{ind_str}"
        "Momentum Classification (BUY/SELL/HOLD):"
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


# ── Bybit Private Signed API ──────────────────────────────────────────────────

BYBIT_API_ROOT = BYBIT_BASE_URL or ("https://api-testnet.bybit.com" if BYBIT_USE_TESTNET else "https://api.bybit.com")

async def signed_bybit_request(method: str, path: str, params: dict = None, json_body: dict = None) -> dict:
    if not BYBIT_API_KEY or not BYBIT_API_SECRET:
        return {"error": "Bybit API keys not configured in .env"}

    url = BYBIT_API_ROOT + path
    timestamp = str(int(time.time() * 1000))
    recv_window = "5000"
    
    req_body = ""
    if json_body:
        req_body = json.dumps(json_body)
    
    req_query = ""
    if params:
        req_query = "&".join([f"{k}={v}" for k, v in params.items()])

    signature_payload = timestamp + BYBIT_API_KEY + recv_window + req_query + req_body
    signature = hmac.new(
        BYBIT_API_SECRET.encode("utf-8"),
        signature_payload.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()

    headers = {
        "X-BAPI-API-KEY": BYBIT_API_KEY,
        "X-BAPI-TIMESTAMP": timestamp,
        "X-BAPI-SIGN": signature,
        "X-BAPI-RECV-WINDOW": recv_window,
        "Content-Type": "application/json"
    }

    async with httpx.AsyncClient() as client:
        try:
            if method.upper() == "GET":
                resp = await client.get(url, params=params, headers=headers, timeout=5.0)
            elif method.upper() == "POST":
                resp = await client.post(url, content=req_body, headers=headers, timeout=5.0)
            else:
                return {"error": f"Unsupported method: {method}"}
            return resp.json()
        except Exception as e:
            return {"error": f"HTTP request failed: {e}"}


@app.get("/bybit/balance")
async def get_balance():
    params = {"accountType": "UNIFIED"}
    res = await signed_bybit_request("GET", "/v5/account/wallet-balance", params=params)
    if "error" in res or res.get("retCode") != 0:
        params = {"accountType": "CONTRACT"}
        res = await signed_bybit_request("GET", "/v5/account/wallet-balance", params=params)
    
    if isinstance(res, dict) and res.get("retCode") == 0:
        try:
            list_data = res["result"]["list"][0]
            for coin_info in list_data.get("coin", []):
                if coin_info.get("coin") == "USDT":
                    return {
                        "balance": float(coin_info.get("walletBalance", 0.0)),
                        "equity": float(coin_info.get("equity", 0.0)),
                        "available": float(coin_info.get("availableToWithdraw", 0.0))
                    }
            return {
                "balance": float(list_data.get("totalWalletBalance", 0.0)),
                "equity": float(list_data.get("totalEquity", 0.0)),
                "available": float(list_data.get("totalAvailableBalance", 0.0))
            }
        except Exception as e:
            return {"error": f"Failed to parse balance: {e}"}
    return {"error": res.get("retMsg", "Bybit keys or connection error")}


@app.get("/bybit/position/{coin}")
async def get_position(coin: str):
    symbol = COINS.get(coin)
    if not symbol:
        return {"error": "Invalid coin"}
        
    params = {"category": "linear", "symbol": symbol}
    res = await signed_bybit_request("GET", "/v5/position/list", params=params)
    
    if isinstance(res, dict) and res.get("retCode") == 0:
        try:
            positions = res["result"]["list"]
            for pos in positions:
                size = float(pos.get("size", 0.0))
                if size > 0:
                    side = pos.get("side")
                    entry_price = float(pos.get("entryPrice", 0.0))
                    unrealised_pnl = float(pos.get("unrealisedPnl", 0.0))
                    return {
                        "active": True,
                        "side": "LONG" if side == "Buy" else "SHORT",
                        "size": size,
                        "entry_price": entry_price,
                        "pnl": unrealised_pnl,
                        "leverage": float(pos.get("leverage", 1.0))
                    }
            return {"active": False}
        except Exception as e:
            return {"error": f"Failed to parse position: {e}"}
    return {"error": res.get("retMsg", "Bybit keys or connection error")}


class TradeRequest(BaseModel):
    coin: str
    side: str
    leverage: float = 10.0
    usdt_size: float = 10.0


@app.post("/bybit/trade")
async def place_trade(req: TradeRequest):
    symbol = COINS.get(req.coin)
    if not symbol:
        return {"error": "Invalid coin"}
    if req.side not in ("LONG", "SHORT"):
        return {"error": "Invalid side"}
    if req.leverage <= 0 or req.usdt_size <= 0:
        return {"error": "Leverage and size must be positive"}
        
    lev_str = str(int(req.leverage))
    lev_payload = {
        "category": "linear",
        "symbol": symbol,
        "buyLeverage": lev_str,
        "sellLeverage": lev_str
    }
    await signed_bybit_request("POST", "/v5/position/set-leverage", json_body=lev_payload)
    
    ticker = await get_market(req.coin, "linear")
    if not ticker or not ticker.get("price"):
        return {"error": "Failed to fetch market price"}
        
    price = ticker["price"]
    total_value = req.usdt_size * req.leverage
    raw_qty = total_value / price
    
    precision = COIN_PRECISION.get(req.coin, 2)
    if precision == 0:
        qty = str(int(round(raw_qty)))
    else:
        qty = f"{raw_qty:.{precision}f}"
        
    if float(qty) <= 0:
        return {"error": f"Calculated quantity {qty} is too small."}
        
    bybit_side = "Buy" if req.side == "LONG" else "Sell"
    
    order_payload = {
        "category": "linear",
        "symbol": symbol,
        "side": bybit_side,
        "orderType": "Market",
        "qty": qty,
        "timeInForce": "GTC"
    }
    
    res = await signed_bybit_request("POST", "/v5/order/create", json_body=order_payload)
    if isinstance(res, dict) and res.get("retCode") == 0:
        return {
            "success": True,
            "orderId": res["result"]["orderId"],
            "qty": qty,
            "price": price,
            "side": req.side
        }
    return {"error": res.get("retMsg", "Failed to place trade")}


class CloseRequest(BaseModel):
    coin: str


@app.post("/bybit/close")
async def close_trade(req: CloseRequest):
    symbol = COINS.get(req.coin)
    if not symbol:
        return {"error": "Invalid coin"}
        
    params = {"category": "linear", "symbol": symbol}
    pos_res = await signed_bybit_request("GET", "/v5/position/list", params=params)
    if not isinstance(pos_res, dict) or pos_res.get("retCode") != 0:
        return {"error": pos_res.get("retMsg", "Failed to fetch position")}
        
    try:
        positions = pos_res["result"]["list"]
        active_pos = None
        for pos in positions:
            if float(pos.get("size", 0.0)) > 0:
                active_pos = pos
                break
                
        if not active_pos:
            return {"error": "No active position to close"}
            
        qty = active_pos["size"]
        side = active_pos["side"]
        close_side = "Sell" if side == "Buy" else "Buy"
        
        order_payload = {
            "category": "linear",
            "symbol": symbol,
            "side": close_side,
            "orderType": "Market",
            "qty": qty,
            "reduceOnly": True
        }
        
        res = await signed_bybit_request("POST", "/v5/order/create", json_body=order_payload)
        if isinstance(res, dict) and res.get("retCode") == 0:
            return {
                "success": True,
                "orderId": res["result"]["orderId"],
                "qty": qty
            }
        return {"error": res.get("retMsg", "Failed to close position")}
    except Exception as e:
        return {"error": f"Error closing position: {e}"}


