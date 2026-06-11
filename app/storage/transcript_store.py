import json
from pathlib import Path
from datetime import datetime


class TranscriptStore:

    def save(
        self,
        transcript: str,
        response: str
    ):

        timestamp = (
            datetime.utcnow()
            .isoformat()
        )

        payload = {
            "timestamp": timestamp,
            "transcript": transcript,
            "response": response
        }

        filename = (
            timestamp.replace(":", "-")
            + ".json"
        )

        Path(
            "data/transcripts"
        ).mkdir(
            parents=True,
            exist_ok=True
        )

        with open(
            f"data/transcripts/{filename}",
            "w"
        ) as f:

            json.dump(
                payload,
                f,
                indent=2
            )