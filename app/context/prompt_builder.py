class PromptBuilder:

    def build(
        self,
        transcript: str,
        history: list
    ):

        prompt = (
            "Previous conversations:\n\n"
        )

        for item in history:

            prompt += (
                f"User: {item['transcript']}\n"
            )

            prompt += (
                f"Assistant: {item['response']}\n\n"
            )

        prompt += (
            f"\nCurrent User Message:\n"
            f"{transcript}"
        )

        return prompt