from app.conversation.transcriber import transcribe_audio

print(
    transcribe_audio(
        "recordings/weather.wav"
    )
)