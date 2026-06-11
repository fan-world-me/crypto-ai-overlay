import os
from dotenv import load_dotenv

load_dotenv()

NVIDIA_API_KEY = os.getenv("NVIDIA_API_KEY", "")
GROQ_API_KEY   = os.getenv("GROQ_API_KEY", "")

COINS = {
    "BTC":  "BTCUSDT",
    "ETH":  "ETHUSDT",
    "TON":  "TONUSDT",
    "SOL":  "SOLUSDT",
    "DOGE": "DOGEUSDT",
}

NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
GROQ_BASE_URL   = "https://api.groq.com/openai/v1/chat/completions"

# ── NVIDIA NIM — fastest models for low-latency inference ──────────────────────
NVIDIA_MODELS = [
    {"id": "mistralai/mistral-7b-instruct-v0.3",        "name": "NIM Mistral-7B",     "provider": "nvidia"},
    {"id": "google/gemma-2-9b-it",                      "name": "NIM Gemma-2-9B",     "provider": "nvidia"},
    {"id": "meta/llama-3.1-8b-instruct",                "name": "NIM Llama-3.1-8B",   "provider": "nvidia"},
    {"id": "microsoft/phi-3.5-mini-instruct",           "name": "NIM Phi-3.5-Mini",   "provider": "nvidia"},
    {"id": "deepseek-ai/deepseek-r1-distill-llama-8b",  "name": "NIM DeepSeek-R1-8B", "provider": "nvidia"},
    {"id": "qwen/qwen2.5-7b-instruct",                  "name": "NIM Qwen-2.5-7B",    "provider": "nvidia"},
    {"id": "nvidia/nemotron-mini-4b-instruct",          "name": "NIM Nemotron-4B",    "provider": "nvidia"},
]

# ── Groq — ultra-fast inference chips ─────────────────────────────────────────
GROQ_MODELS = [
    {"id": "llama-3.1-8b-instant",   "name": "Groq Llama-8B",   "provider": "groq"},
    {"id": "qwen-qwq-32b",           "name": "Groq Qwen-QwQ",   "provider": "groq"},
    {"id": "llama-3.3-70b-versatile","name": "Groq Llama-70B",  "provider": "groq"},
]

ALL_MODELS = NVIDIA_MODELS + GROQ_MODELS

# Per-request timeout — cloud APIs need 4-8s even for 5-token replies
AI_TIMEOUT_SEC     = 7.0
MAX_TOKENS         = 5
MARKET_REFRESH_SEC = 4
