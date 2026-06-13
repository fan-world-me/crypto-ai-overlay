import os
from dotenv import load_dotenv

load_dotenv()

NVIDIA_API_KEY = os.getenv("NVIDIA_API_KEY", "")
GROQ_API_KEY   = os.getenv("GROQ_API_KEY", "")

# Bybit Credentials
BYBIT_API_KEY     = os.getenv("BYBIT_API_KEY", "")
BYBIT_API_SECRET  = os.getenv("BYBIT_API_SECRET", "")
BYBIT_USE_TESTNET = os.getenv("BYBIT_USE_TESTNET", "true").lower() == "true"
BYBIT_BASE_URL    = os.getenv("BYBIT_BASE_URL", "").strip()

COINS = {
    "BTC":  "BTCUSDT",
    "ETH":  "ETHUSDT",
    "TON":  "TONUSDT",
    "SOL":  "SOLUSDT",
    "DOGE": "DOGEUSDT",
}

# Quantity decimal precision for each coin on Bybit Futures
COIN_PRECISION = {
    "BTC":  3,
    "ETH":  2,
    "TON":  1,
    "SOL":  2,
    "DOGE": 0,
}


NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
GROQ_BASE_URL   = "https://api.groq.com/openai/v1/chat/completions"

# All model IDs verified working (live-tested June 2025).
# NIM free tier: integrate.api.nvidia.com  |  Groq free tier: api.groq.com/openai/v1
NVIDIA_MODELS = [
    {"id": "meta/llama-3.1-8b-instruct",               "name": "NIM Llama-3.1-8B",    "provider": "nvidia"},
    {"id": "nvidia/nemotron-mini-4b-instruct",          "name": "NIM Nemotron-4B",     "provider": "nvidia"},
    {"id": "nvidia/llama-3.1-nemotron-nano-8b-v1",     "name": "NIM Nemotron-Nano-8B","provider": "nvidia"},
    {"id": "upstage/solar-10.7b-instruct",              "name": "NIM Solar-10B",       "provider": "nvidia"},
    {"id": "meta/llama-3.1-70b-instruct",               "name": "NIM Llama-3.1-70B",   "provider": "nvidia"},
    {"id": "mistralai/mixtral-8x7b-instruct-v0.1",     "name": "NIM Mixtral-8x7B",    "provider": "nvidia"},
]

GROQ_MODELS = [
    {"id": "llama-3.1-8b-instant",                            "name": "Groq Llama-8B",      "provider": "groq"},
    {"id": "llama-3.3-70b-versatile",                         "name": "Groq Llama-70B",     "provider": "groq"},
    {"id": "meta-llama/llama-4-scout-17b-16e-instruct",       "name": "Groq Llama-4-Scout", "provider": "groq"},
    {"id": "qwen/qwen3-32b",                                   "name": "Groq Qwen3-32B",     "provider": "groq", "is_reasoning": True},
]

ALL_MODELS = NVIDIA_MODELS + GROQ_MODELS

AI_TIMEOUT_SEC   = 10.0   # cloud APIs vary; 10s covers p99
MAX_TOKENS       = 6      # enough for BUY/SELL/HOLD + punctuation
REASONING_TOKENS = 1000   # reserved for future reasoning models
AI_REFRESH_SEC   = 20     # AI votes refresh every 20 seconds to conserve API credits
LIVE_PRICE_REFRESH_SEC = 1.2 # Price updates in real-time every 1.2 seconds

