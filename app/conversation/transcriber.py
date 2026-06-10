from pathlib import Path

from google import genai
from google.genai import types

from app.config import GEMINI_API_KEY

client = genai.Client(
    api_key=GEMINI_API_KEY
)


def transcribe_audio(audio_path: str):

    audio_bytes = Path(audio_path).read_bytes()

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=[
            "Transcribe this audio exactly.",
            types.Part.from_bytes(
                data=audio_bytes,
                mime_type="audio/wav"
            )
        ]
    )

    return response.text