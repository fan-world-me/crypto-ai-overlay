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

# is_reasoning=True → model outputs <think>...</think> before answer,
# needs more tokens and special parsing
NVIDIA_MODELS = [
    {"id": "mistralai/mistral-7b-instruct-v0.3",       "name": "NIM Mistral-7B",     "provider": "nvidia"},
    {"id": "google/gemma-2-9b-it",                     "name": "NIM Gemma-2-9B",     "provider": "nvidia"},
    {"id": "meta/llama-3.1-8b-instruct",               "name": "NIM Llama-3.1-8B",   "provider": "nvidia"},
    {"id": "microsoft/phi-3-mini-4k-instruct",         "name": "NIM Phi-3-Mini",     "provider": "nvidia"},
    {"id": "deepseek-ai/deepseek-r1-distill-llama-8b", "name": "NIM DeepSeek-R1-8B", "provider": "nvidia", "is_reasoning": True},
    {"id": "nvidia/nemotron-mini-4b-instruct",         "name": "NIM Nemotron-4B",    "provider": "nvidia"},
    {"id": "meta/llama-3.2-3b-instruct",               "name": "NIM Llama-3.2-3B",   "provider": "nvidia"},
]

GROQ_MODELS = [
    {"id": "llama-3.1-8b-instant",    "name": "Groq Llama-8B",  "provider": "groq"},
    {"id": "qwen-qwq-32b",            "name": "Groq Qwen-QwQ",  "provider": "groq", "is_reasoning": True},
    {"id": "llama-3.3-70b-versatile", "name": "Groq Llama-70B", "provider": "groq"},
]

ALL_MODELS = NVIDIA_MODELS + GROQ_MODELS

AI_TIMEOUT_SEC     = 8.0
MAX_TOKENS         = 6          # standard models
REASONING_TOKENS   = 800        # reasoning models need room for <think> block
MARKET_REFRESH_SEC = 4
