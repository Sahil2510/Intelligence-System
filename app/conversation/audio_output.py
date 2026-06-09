from pathlib import Path


def save_audio_file(audio_bytes: bytes, path: str):
    Path(path).write_bytes(audio_bytes)