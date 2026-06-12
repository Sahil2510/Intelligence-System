from app.prompts.prompt_registry import PromptRegistry


class PromptBuilder:

    def __init__(self):
        self.prompts = PromptRegistry()

    def build(
        self,
        transcript: str,
        history: list
    ):

        system_prompt = (
            self.prompts.system_prompt()
        )

        history_text = (
            self._format_history(history)
        )

        prompt = (
            f"{system_prompt}\n\n"
            f"Previous conversations:\n"
            f"{history_text}\n\n"
            f"Current user message:\n"
            f"{transcript}\n\n"
            f"Answer:"
        )

        return prompt

    def build_web_search_unavailable(
        self,
        transcript: str
    ):

        web_search_prompt = (
            self.prompts.web_search_prompt()
        )

        return (
            f"{web_search_prompt}\n\n"
            f"User message:\n"
            f"{transcript}\n\n"
            f"Answer:"
        )

    def holding_response(self) -> str:
        return self.prompts.holding_response_prompt()

    def _format_history(
        self,
        history: list
    ):

        if not history:
            return "No previous conversations available."

        lines = []

        for item in history:
            lines.append(
                f"User: {item.get('transcript', '')}"
            )
            lines.append(
                f"Assistant: {item.get('response', '')}"
            )
            lines.append("")

        return "\n".join(lines).strip()