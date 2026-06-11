# 🔮 Crypto AI Overlay

> Real-time crypto trading signals powered by 10 AI models in parallel — displayed as an always-on-top floating window for Windows.

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)

---

## What it does

Fetches live crypto prices from **Bybit** (no API key needed) and simultaneously queries **7 NVIDIA NIM models** + **3 Groq models** in parallel with a 250ms timeout. Each model votes **BUY / SELL / HOLD** — the majority wins.

The result is shown in a sleek dark floating window that stays on top of all other apps.

![Screenshot placeholder](https://via.placeholder.com/320x480/0d0d0d/00e676?text=CRYPTO+AI+OVERLAY)

---

## Supported coins

| Coin | Symbol |
|------|--------|
| Bitcoin | BTC |
| Ethereum | ETH |
| Toncoin | TON |
| Solana | SOL |
| Dogecoin | DOGE |

---

## AI Models

**NVIDIA NIM** (`api.nvidia.com`):
- Llama-3.2-3B · Llama-3.1-8B · Phi-3-Mini · Nemotron-8B · Gemma-2-9B · Mistral-7B · Mistral-Nemo-12B

**Groq** (`api.groq.com`):
- Llama-3.1-8B-instant · Gemma2-9B · Mixtral-8x7B

All requests fire **in parallel**. Models that don't respond within **250ms** are skipped — they don't affect the vote.

---

## Requirements

- Windows 10/11
- Python 3.10+
- NVIDIA NIM API key (free — 1000 credits at [build.nvidia.com](https://build.nvidia.com))
- Groq API key (free at [console.groq.com](https://console.groq.com))

> **Bybit key is NOT required** — only the public market data API is used.

---

## Installation

```bash
# 1. Clone
git clone https://github.com/fan-world-me/crypto-ai-overlay.git
cd crypto-ai-overlay

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure API keys
copy .env.example .env
# Open .env and paste your keys
```

### `.env` file

```env
NVIDIA_API_KEY=nvapi-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
GROQ_API_KEY=gsk_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

---

## Usage

```bash
python main.py
```

| Action | How |
|--------|-----|
| Move window | Click and drag |
| Switch coin | Click BTC / ETH / TON / SOL / DOGE |
| Manual refresh | Click ↺ button (bottom right) |
| Close | Click ✕ (top right) |

Auto-refreshes every **5 seconds**.

---

## Project structure

```
crypto-overlay/
├── main.py          — GUI overlay (tkinter, always-on-top)
├── ai_analyzer.py   — parallel async AI requests + majority vote
├── bybit_client.py  — Bybit public API price fetcher
├── config.py        — models list, coins, timeouts
├── requirements.txt
├── .env.example
└── LICENSE          — GNU GPL v3
```

---

## How it works

```
Every 5s:
  1. Fetch price + 24h/1h change from Bybit REST API
  2. Build a short prompt with market data
  3. Fire all 10 AI models simultaneously (asyncio + aiohttp)
  4. Collect responses within 250ms timeout
  5. Count BUY / SELL / HOLD votes
  6. Show majority signal + confidence % in the overlay
```

---

## License

GNU General Public License v3.0 — see [LICENSE](LICENSE) for details.
