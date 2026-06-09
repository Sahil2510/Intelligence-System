from pydub import AudioSegment


def wav_to_pcm(path: str) -> bytes:
    audio = AudioSegment.from_wav(path)

    audio = (
        audio
        .set_frame_rate(16000)
        .set_channels(1)
        .set_sample_width(2)
    )

    return audio.raw_data