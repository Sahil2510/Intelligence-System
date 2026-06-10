from google import genai

from app.config import GEMINI_API_KEY

client = genai.Client(
    api_key=GEMINI_API_KEY
)


def generate_response(query: str):

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=query
    )

    return response.text