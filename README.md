[![Telegram](https://img.shields.io/badge/Telegram-@fan__world__me-2CA5E0?style=flat-square&logo=telegram)](https://t.me/fan_world_me)   [![Discord](https://img.shields.io/badge/Discord-fan__world__me-5865F2?style=flat-square&logo=discord)](https://discord.com/users/1040301536036786248)   [![GitHub](https://img.shields.io/badge/GitHub-fan--world--me-181717?style=flat-square&logo=github)](https://github.com/fan-world-me)   [![Portfolio](https://img.shields.io/badge/Portfolio-fan--world--me.github.io-00e5ff?style=flat-square&logo=githubpages&logoColor=white)](https://fan-world-me.github.io/)

# 🔮 Crypto AI Overlay

Real-time crypto trading signals powered by 10 AI models in parallel — displayed as an always-on-top floating window for Windows.

### 💭 What it does

Fetches live crypto prices from **Bybit** (no API key needed) and simultaneously queries **7 NVIDIA NIM models** + **3 Groq models** in parallel with a 250ms timeout. Each model votes **BUY / SELL / HOLD** — the majority wins.

The result is shown in a sleek dark floating window that stays on top of all other apps.

---

### 🧰 Tech Stack

![Python](https://img.shields.io/badge/Python-3.10+-3776AB?style=flat-square&logo=python&logoColor=white)
![Tkinter](https://img.shields.io/badge/Tkinter-GUI-00e5ff?style=flat-square)
![asyncio](https://img.shields.io/badge/asyncio-aiohttp-00e5ff?style=flat-square)
![Bybit](https://img.shields.io/badge/Bybit-public_API-F7A600?style=flat-square)
![NVIDIA](https://img.shields.io/badge/NVIDIA_NIM-7_models-76B900?style=flat-square&logo=nvidia&logoColor=white)
![Groq](https://img.shields.io/badge/Groq-3_models-F55036?style=flat-square)

---

### 🪙 Supported coins

| Coin | Symbol |
|---|---|
| Bitcoin | BTC |
| Ethereum | ETH |
| Toncoin | TON |
| Solana | SOL |
| Dogecoin | DOGE |

---

### 🤖 AI Models

**NVIDIA NIM** (`api.nvidia.com`):

- Llama-3.2-3B · Llama-3.1-8B · Phi-3-Mini · Nemotron-8B · Gemma-2-9B · Mistral-7B · Mistral-Nemo-12B

**Groq** (`api.groq.com`):

- Llama-3.1-8B-instant · Gemma2-9B · Mixtral-8x7B

All requests fire **in parallel**. Models that don't respond within **250ms** are skipped — they don't affect the vote.

---

### 🗂️ Project Structure

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

### 📋 Requirements

- Windows 10/11
- Python 3.10+
- NVIDIA NIM API key (free — 1000 credits at [build.nvidia.com](https://build.nvidia.com))
- Groq API key (free at [console.groq.com](https://console.groq.com))

> **Bybit key is NOT required** — only the public market data API is used.

---

### 🔧 Installation

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

**`.env` file**

```env
NVIDIA_API_KEY=nvapi-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
GROQ_API_KEY=gsk_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

---

### 🚀 Usage

```bash
python main.py
```

| Action | How |
|---|---|
| Move window | Click and drag |
| Switch coin | Click BTC / ETH / TON / SOL / DOGE |
| Manual refresh | Click ↺ button (bottom right) |
| Close | Click ✕ (top right) |

Auto-refreshes every **5 seconds**.

---

### ⚙️ How it works

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

### 📄 License

[GPL-3.0](LICENSE) © [fan-world-me](https://github.com/fan-world-me)

---

Made with 🩵 in Ukraine 🇺🇦

[![Telegram](https://img.shields.io/badge/Telegram-@fan__world__me-2CA5E0?style=flat-square&logo=telegram)](https://t.me/fan_world_me)   [![Discord](https://img.shields.io/badge/Discord-fan__world__me-5865F2?style=flat-square&logo=discord)](https://discord.com/users/1040301536036786248)   [![Portfolio](https://img.shields.io/badge/Portfolio-fan--world--me.github.io-00e5ff?style=flat-square&logo=githubpages&logoColor=white)](https://fan-world-me.github.io/)
