import re

LANGUAGE_HINTS = (
    (re.compile(r"[\u0900-\u097F]"), "Hindi"),
    (re.compile(r"[\u0980-\u09FF]"), "Bengali"),
    (re.compile(r"[\u0A80-\u0AFF]"), "Gujarati"),
    (re.compile(r"[\u0A00-\u0A7F]"), "Punjabi"),
    (re.compile(r"[\u0B80-\u0BFF]"), "Tamil"),
    (re.compile(r"[\u0C00-\u0C7F]"), "Telugu"),
    (re.compile(r"[\u0C80-\u0CFF]"), "Kannada"),
    (re.compile(r"[\u0D00-\u0D7F]"), "Malayalam"),
    (re.compile(r"[\u0B00-\u0B7F]"), "Odia"),
    (re.compile(r"[\u0600-\u06FF]"), "Urdu"),
)

# Indian BCP-47 locales for browser / TTS voice selection
LANGUAGE_LOCALES = {
    "Hindi": "hi-IN",
    "Bengali": "bn-IN",
    "Gujarati": "gu-IN",
    "Punjabi": "pa-IN",
    "Tamil": "ta-IN",
    "Telugu": "te-IN",
    "Kannada": "kn-IN",
    "Malayalam": "ml-IN",
    "Odia": "or-IN",
    "Urdu": "ur-IN",
}

DEFAULT_SPEECH_LOCALE = "en-IN"


def detect_language_hint(*texts: str) -> str | None:
    for text in texts:
        if not text:
            continue

        for pattern, language in LANGUAGE_HINTS:
            if pattern.search(text):
                return language

    return None


def detect_speech_locale(*texts: str) -> str:
    language = detect_language_hint(*texts)

    if language:
        return LANGUAGE_LOCALES.get(language, DEFAULT_SPEECH_LOCALE)

    return DEFAULT_SPEECH_LOCALE
