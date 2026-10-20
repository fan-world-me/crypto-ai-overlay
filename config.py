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

# Model IDs checked against provider docs on 2026-10-20.
# Retired and removed: NVIDIA llama-3.1-8b/70b-instruct, nemotron-mini-4b-instruct,
# llama-3.1-nemotron-nano-8b-v1, solar-10.7b-instruct (HTTP 410 EOL 2026-07/08),
# Groq llama-3.1-8b-instant, llama-3.3-70b-versatile, qwen3-32b, llama-4-scout (shut down 2026-07/08).
#
# Per-model "extra" is merged into the request body to switch thinking off:
#   - NVIDIA Nemotron 3.x: chat_template_kwargs.enable_thinking=false
#   - Groq Qwen3.8:        reasoning_effort="none"
#   - Groq GPT-OSS:        reasoning can't be disabled, so effort=low + hide it from the output
NVIDIA_MODELS = [
    {"id": "nvidia/nemotron-3-ultra-550b-a55b",              "name": "NIM Nemotron-Ultra-550B",   "provider": "nvidia",
     "extra": {"chat_template_kwargs": {"enable_thinking": False}}},
    {"id": "nvidia/nemotron-3.5-lightning-30b-a3b",          "name": "NIM Nemotron-Lightning-30B", "provider": "nvidia",
     "extra": {"chat_template_kwargs": {"enable_thinking": False}}},
    {"id": "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning",  "name": "NIM Nemotron-Omni-30B",     "provider": "nvidia",
     "extra": {"chat_template_kwargs": {"enable_thinking": False}}},
]

GROQ_MODELS = [
    {"id": "openai/gpt-oss-20b",   "name": "Groq GPT-OSS-20B",  "provider": "groq", "is_reasoning": True,
     "extra": {"reasoning_effort": "low", "include_reasoning": False}},
    {"id": "openai/gpt-oss-120b",  "name": "Groq GPT-OSS-120B", "provider": "groq", "is_reasoning": True,
     "extra": {"reasoning_effort": "low", "include_reasoning": False}},
    {"id": "qwen/qwen3.8-27b",     "name": "Groq Qwen3.8-27B",  "provider": "groq",
     "extra": {"reasoning_effort": "none"}},
]

ALL_MODELS = NVIDIA_MODELS + GROQ_MODELS

AI_TIMEOUT_SEC   = 10.0   # cloud APIs vary; 10s covers p99
MAX_TOKENS       = 6      # enough for BUY/SELL/HOLD + punctuation
REASONING_TOKENS = 1000   # budget for models that can't fully disable reasoning (GPT-OSS)
AI_REFRESH_SEC   = 20     # AI votes refresh every 20 seconds to conserve API credits
LIVE_PRICE_REFRESH_SEC = 1.2 # Price updates in real-time every 1.2 seconds
