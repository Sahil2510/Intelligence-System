from pathlib import Path

from dotenv import load_dotenv
import os

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = PROJECT_ROOT / ".env"

load_dotenv(ENV_PATH)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
LANGFUSE_SECRET_KEY = os.getenv("LANGFUSE_SECRET_KEY")
LANGFUSE_PUBLIC_KEY = os.getenv("LANGFUSE_PUBLIC_KEY")
LANGFUSE_BASE_URL = os.getenv("LANGFUSE_BASE_URL", "https://jp.cloud.langfuse.com")
LANGFUSE_PROMPT_LABEL = os.getenv("LANGFUSE_PROMPT_LABEL", "develop")

SYSTEM_PROMPT_NAME = os.getenv("SYSTEM_PROMPT_NAME", "system-prompt-luvio")
WEB_SEARCH_PROMPT_NAME = os.getenv("WEB_SEARCH_PROMPT_NAME", "web-search-luvio")
HOLDING_RESPONSE_PROMPT_NAME = os.getenv(
    "HOLDING_RESPONSE_PROMPT_NAME",
    "holding-response-luvio",
)

GEMINI_TTS_MODEL = os.getenv(
    "GEMINI_TTS_MODEL",
    "gemini-2.5-flash-preview-tts",
)
GEMINI_TTS_VOICE = os.getenv("GEMINI_TTS_VOICE", "Kore")

SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")
SPOTIFY_REDIRECT_URI = os.getenv(
    "SPOTIFY_REDIRECT_URI",
    "http://127.0.0.1:8000/api/spotify/callback",
)
SPOTIFY_MARKET = os.getenv("SPOTIFY_MARKET", "IN")

REDIS_URL = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")
REDIS_STM_MAX_MESSAGES = int(os.getenv("REDIS_STM_MAX_MESSAGES", "40"))
REDIS_STM_TTL_SECONDS = int(os.getenv("REDIS_STM_TTL_SECONDS", "604800"))
STM_HISTORY_TURN_LIMIT = int(os.getenv("STM_HISTORY_TURN_LIMIT", "5"))

MEM0_API_KEY = os.getenv("MEM0_API_KEY")
MEM0_SEARCH_LIMIT = int(os.getenv("MEM0_SEARCH_LIMIT", "5"))
DEFAULT_USER_ID = os.getenv("DEFAULT_USER_ID", "playground-default")
