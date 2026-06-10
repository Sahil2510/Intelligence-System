from app.conversation.transcriber import transcribe_audio
from app.conversation.responder import generate_response


query = transcribe_audio(
    "recordings/weather.wav"
)

print("\nTRANSCRIPT:")
print(query)

response = generate_response(query)

print("\nRESPONSE:")
print(response)