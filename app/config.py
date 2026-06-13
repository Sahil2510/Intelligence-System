from dotenv import load_dotenv
import os

load_dotenv()

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
