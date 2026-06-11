import os
from dotenv import load_dotenv

load_dotenv()

NVIDIA_API_KEY = os.getenv("NVIDIA_API_KEY", "")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")

COINS = {
    "BTC":  "BTCUSDT",
    "ETH":  "ETHUSDT",
    "TON":  "TONUSDT",
    "SOL":  "SOLUSDT",
    "DOGE": "DOGEUSDT",
}

NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
GROQ_BASE_URL   = "https://api.groq.com/openai/v1/chat/completions"

NVIDIA_MODELS = [
    {"id": "meta/llama-3.2-3b-instruct",              "name": "Llama-3.2-3B",    "provider": "nvidia"},
    {"id": "meta/llama-3.1-8b-instruct",              "name": "Llama-3.1-8B",    "provider": "nvidia"},
    {"id": "microsoft/phi-3-mini-128k-instruct",      "name": "Phi-3-Mini",      "provider": "nvidia"},
    {"id": "nvidia/llama-3.1-nemotron-nano-8b-v1",    "name": "Nemotron-8B",     "provider": "nvidia"},
    {"id": "google/gemma-2-9b-it",                    "name": "Gemma-2-9B",      "provider": "nvidia"},
    {"id": "mistralai/mistral-7b-instruct-v0.3",      "name": "Mistral-7B",      "provider": "nvidia"},
    {"id": "mistralai/mistral-nemo-12b-instruct",     "name": "Mistral-Nemo",    "provider": "nvidia"},
]

GROQ_MODELS = [
    {"id": "llama-3.1-8b-instant",  "name": "Groq-Llama-8B",   "provider": "groq"},
    {"id": "gemma2-9b-it",          "name": "Groq-Gemma-9B",   "provider": "groq"},
    {"id": "mixtral-8x7b-32768",    "name": "Groq-Mixtral",    "provider": "groq"},
]

ALL_MODELS = NVIDIA_MODELS + GROQ_MODELS

AI_TIMEOUT_SEC   = 0.25
REFRESH_INTERVAL = 5
MAX_TOKENS       = 5
