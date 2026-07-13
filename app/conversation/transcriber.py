from pathlib import Path

from google import genai
from google.genai import types

from app.config import GEMINI_API_KEY, GEMINI_MODEL
from app.utils.pipeline_log import pipeline_complete, pipeline_start

client = genai.Client(
    api_key=GEMINI_API_KEY
)

MODEL = GEMINI_MODEL


def transcribe_audio(audio_path: str):
    audio_bytes = Path(audio_path).read_bytes()

    return transcribe_audio_bytes(
        audio_bytes=audio_bytes,
        mime_type="audio/wav",
    )


def transcribe_audio_bytes(
    audio_bytes: bytes,
    mime_type: str = "audio/webm",
):
    pipeline_start(
        "transcription",
        "Sending audio bytes to Gemini for transcription",
        {
            "model": MODEL,
            "mime_type": mime_type,
            "audio_bytes": len(audio_bytes),
        },
    )

    response = client.models.generate_content(
        model=MODEL,
        contents=[
            "Transcribe verbatim, same language as spoken:",
            types.Part.from_bytes(
                data=audio_bytes,
                mime_type=mime_type,
            ),
        ],
    )

    transcript = response.text
    pipeline_complete(
        "transcription",
        "Audio transcription completed",
        {
            "transcript": transcript,
            "transcript_length": len(transcript),
        },
    )

    return transcript
