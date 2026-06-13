import json
from pathlib import Path


PROFILE_PATH = Path("data/user/profile.json")


class ProfileStore:

    def __init__(self, profile_path: Path = PROFILE_PATH):
        self.profile_path = profile_path
        self.profile_path.parent.mkdir(parents=True, exist_ok=True)

    def get(self) -> dict:
        if not self.profile_path.exists():
            return self._empty_profile()

        with self.profile_path.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    def save(self, profile: dict) -> dict:
        current = self._empty_profile()
        current.update(
            {
                key: value
                for key, value in profile.items()
                if key in current
            }
        )
        self._write(current)
        return current

    def format_for_prompt(self) -> str:
        profile = self.get()

        if not self.has_details(profile):
            return "No user profile available."

        lines = []

        if profile.get("name"):
            lines.append(f"Name: {profile['name']}")
        if profile.get("age"):
            lines.append(f"Age: {profile['age']}")
        if profile.get("dob"):
            lines.append(f"Date of birth: {profile['dob']}")
        if profile.get("height"):
            lines.append(f"Height: {profile['height']}")
        if profile.get("weight"):
            lines.append(f"Weight: {profile['weight']}")

        return "\n".join(lines)

    def display_name(self) -> str:
        profile = self.get()
        name = profile.get("name", "").strip()
        return name or "Guest"

    def initials(self) -> str:
        name = self.display_name()
        parts = name.split()

        if len(parts) >= 2:
            return (parts[0][0] + parts[1][0]).upper()

        return name[:2].upper() or "G"

    @staticmethod
    def has_details(profile: dict) -> bool:
        return any(
            str(profile.get(key, "")).strip()
            for key in ("name", "age", "dob", "height", "weight")
        )

    def _empty_profile(self) -> dict:
        return {
            "name": "",
            "age": "",
            "dob": "",
            "height": "",
            "weight": "",
        }

    def _write(self, profile: dict) -> None:
        with self.profile_path.open("w", encoding="utf-8") as handle:
            json.dump(profile, handle, indent=2)
