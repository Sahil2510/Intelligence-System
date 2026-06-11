import json
from pathlib import Path


class ShortTermMemory:

    def get_recent_conversations(
        self,
        limit: int = 5
    ):

        transcript_dir = Path(
            "data/transcripts"
        )

        if not transcript_dir.exists():
            return []

        files = sorted(
            transcript_dir.glob("*.json")
        )

        files = files[-limit:]

        history = []

        for file in files:

            with open(file) as f:

                history.append(
                    json.load(f)
                )

        return history