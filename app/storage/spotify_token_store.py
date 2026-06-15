import json
import time
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
TOKEN_PATH = PROJECT_ROOT / "data" / "spotify" / "token.json"


class SpotifyTokenStore:

    def __init__(self, token_path: Path = TOKEN_PATH):
        self.token_path = token_path
        self.token_path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> dict | None:
        if not self.token_path.exists():
            return None

        try:
            with self.token_path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (json.JSONDecodeError, OSError):
            return None

        if not isinstance(data, dict):
            return None

        return data

    def save(self, tokens: dict) -> dict:
        payload = {
            "access_token": tokens["access_token"],
            "refresh_token": tokens.get("refresh_token", ""),
            "expires_at": tokens.get(
                "expires_at",
                int(time.time()) + int(tokens.get("expires_in", 3600)),
            ),
            "scope": tokens.get("scope", ""),
            "token_type": tokens.get("token_type", "Bearer"),
        }

        if not payload["refresh_token"]:
            existing = self.load() or {}
            payload["refresh_token"] = existing.get("refresh_token", "")

        with self.token_path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)

        return payload

    def clear(self) -> None:
        if self.token_path.exists():
            self.token_path.unlink()

    def is_connected(self) -> bool:
        tokens = self.load()
        return bool(tokens and tokens.get("refresh_token"))
