from pathlib import Path


def read_audio_file(path: str) -> bytes:
    return Path(path).read_bytes()