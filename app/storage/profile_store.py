class ProfileStore:

    @staticmethod
    def normalize(profile: dict | None) -> dict:
        empty = ProfileStore._empty_profile()

        if not profile:
            return empty

        empty.update(
            {
                key: str(profile.get(key, ""))
                for key in empty
            }
        )
        return empty

    @staticmethod
    def format_for_prompt(profile: dict | None) -> str:
        profile = ProfileStore.normalize(profile)

        if not ProfileStore.has_details(profile):
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

    @staticmethod
    def display_name(profile: dict | None) -> str:
        name = ProfileStore.normalize(profile).get("name", "").strip()
        return name or "Guest"

    @staticmethod
    def initials(profile: dict | None) -> str:
        name = ProfileStore.display_name(profile)
        parts = name.split()

        if len(parts) >= 2:
            return (parts[0][0] + parts[1][0]).upper()

        return name[:2].upper() or "G"

    @staticmethod
    def enrich(profile: dict | None) -> dict:
        normalized = ProfileStore.normalize(profile)
        normalized["display_name"] = ProfileStore.display_name(normalized)
        normalized["initials"] = ProfileStore.initials(normalized)
        return normalized

    @staticmethod
    def has_details(profile: dict) -> bool:
        return any(
            str(profile.get(key, "")).strip()
            for key in ("name", "age", "dob", "height", "weight")
        )

    @staticmethod
    def _empty_profile() -> dict:
        return {
            "name": "",
            "age": "",
            "dob": "",
            "height": "",
            "weight": "",
        }
