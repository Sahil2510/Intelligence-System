import base64
import io
import wave

from google import genai
from google.genai import types

from app.config import (
    GEMINI_API_KEY,
    GEMINI_TTS_MODEL,
    GEMINI_TTS_VOICE,
)
from app.utils.pipeline_log import pipeline_complete, pipeline_start

MODEL = "gemini-2.5-flash"
TTS_MODEL = GEMINI_TTS_MODEL
TTS_VOICE = GEMINI_TTS_VOICE

client = genai.Client(
    api_key=GEMINI_API_KEY
)

INTENT_CLASSIFIER_PROMPT = """Classify the user message into exactly one intent.

Choose web_search when the answer depends on current, recent, or changing information such as:
- weather, forecasts, temperature, mausam, local conditions, or "how hot/cold is it"
- current office holders, elections, or government leaders
- news, sports scores, stock prices, or live events
- anything where an outdated answer would be wrong

Choose spotify when the user clearly wants music on Spotify, such as:
- play, pause, resume, skip, next, previous
- search for a song, artist, album, or playlist
- ask what is currently playing

Choose normal for stable general knowledge, opinions, explanations, or conversation.

Reply with only one word: web_search, spotify, or normal.

User message:
{transcript}
"""


def _extract_text(response) -> str:
    if response.text:
        return response.text

    for candidate in response.candidates or []:
        content = candidate.content
        if not content:
            continue

        for part in content.parts or []:
            if part.text:
                return part.text

    raise ValueError("Gemini returned no text content")


def _iter_stream_text(response) -> str:
    if response.text:
        yield response.text
        return

    for candidate in response.candidates or []:
        content = candidate.content
        if not content:
            continue

        for part in content.parts or []:
            if part.text:
                yield part.text


def stream_response(prompt: str, *, use_google_search: bool = False):
    config = None

    if use_google_search:
        config = types.GenerateContentConfig(
            tools=[
                types.Tool(
                    google_search=types.GoogleSearch()
                )
            ]
        )

    pipeline_start(
        "llm.stream",
        "Streaming response with Gemini",
        {
            "model": MODEL,
            "google_search": use_google_search,
        },
    )

    for chunk in client.models.generate_content_stream(
        model=MODEL,
        contents=prompt,
        config=config,
    ):
        if chunk.text:
            yield chunk.text
            continue

        for text in _iter_stream_text(chunk):
            yield text

    pipeline_complete(
        "llm.stream",
        "Gemini response stream completed",
        {"google_search": use_google_search},
    )


def generate_response(prompt: str) -> str:
    response = client.models.generate_content(
        model=MODEL,
        contents=prompt,
    )

    return _extract_text(response)


def generate_holding_response(holding_prompt: str, transcript: str = "") -> str:
    pipeline_start(
        "llm.holding",
        "Generating holding response with Langfuse prompt",
        {"model": MODEL},
    )

    prompt = holding_prompt

    if transcript.strip():
        prompt = (
            f"{holding_prompt}\n\n"
            f"User message:\n"
            f"{transcript}\n\n"
            f"Holding response:"
        )

    response = client.models.generate_content(
        model=MODEL,
        contents=prompt,
    )

    text = _extract_text(response).strip()
    pipeline_complete(
        "llm.holding",
        "Holding response generated",
        {"response_length": len(text)},
    )
    return text


def generate_with_google_search(prompt: str) -> str:
    response = client.models.generate_content(
        model=MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            tools=[
                types.Tool(
                    google_search=types.GoogleSearch()
                )
            ]
        ),
    )

    return _extract_text(response)


def classify_intent_with_llm(transcript: str) -> str:
    pipeline_start(
        "llm.intent_classifier",
        "Running Gemini intent classification",
        {"model": MODEL},
    )

    response = client.models.generate_content(
        model=MODEL,
        contents=INTENT_CLASSIFIER_PROMPT.format(
            transcript=transcript
        ),
    )

    intent = _extract_text(response).strip().lower()
    pipeline_complete(
        "llm.intent_classifier",
        f"Gemini returned intent: {intent}",
        {"raw_response": intent},
    )
    return intent


def _pcm_to_wav_bytes(
    pcm_data: bytes,
    channels: int = 1,
    rate: int = 24000,
    sample_width: int = 2,
) -> bytes:
    buffer = io.BytesIO()

    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(channels)
        wav_file.setsampwidth(sample_width)
        wav_file.setframerate(rate)
        wav_file.writeframes(pcm_data)

    return buffer.getvalue()


def _speech_instruction(text: str, language_hint: str | None = None) -> str:
    if language_hint:
        return (
            f"Speak naturally in {language_hint}. "
            f"Use a warm conversational tone:\n{text}"
        )

    return f"Speak naturally in the same language as this text:\n{text}"


def generate_speech(
    text: str,
    language_hint: str | None = None,
) -> dict[str, str]:
    pipeline_start(
        "tts.gemini",
        "Generating speech audio with Gemini TTS",
        {
            "model": TTS_MODEL,
            "voice": TTS_VOICE,
            "language_hint": language_hint,
        },
    )

    response = client.models.generate_content(
        model=TTS_MODEL,
        contents=_speech_instruction(text, language_hint),
        config=types.GenerateContentConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name=TTS_VOICE,
                    )
                )
            ),
        ),
    )

    inline_data = response.candidates[0].content.parts[0].inline_data
    pcm_data = inline_data.data

    if isinstance(pcm_data, str):
        pcm_data = base64.b64decode(pcm_data)

    wav_bytes = _pcm_to_wav_bytes(pcm_data)
    audio_base64 = base64.b64encode(wav_bytes).decode("utf-8")

    pipeline_complete(
        "tts.gemini",
        "Gemini TTS audio generated",
        {
            "mime_type": "audio/wav",
            "audio_bytes": len(wav_bytes),
        },
    )

    return {
        "audio_base64": audio_base64,
        "mime_type": "audio/wav",
    }
