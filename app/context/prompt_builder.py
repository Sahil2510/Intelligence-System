from app.conversation.responder import generate_holding_response
from app.prompts.prompt_registry import PromptRegistry
from app.storage.profile_store import ProfileStore
from app.utils.pipeline_log import pipeline_complete, pipeline_start


class PromptBuilder:

    def __init__(self):
        self.prompts = PromptRegistry()

    def build(
        self,
        transcript: str,
        history: list,
        profile: dict | None = None,
    ) -> str:
        system_prompt = self._fetch_system_prompt()
        history_text = self._format_history(history)
        profile_text = ProfileStore.format_for_prompt(profile)

        return (
            f"{system_prompt}\n\n"
            f"User profile:\n"
            f"{profile_text}\n\n"
            f"Previous conversations:\n"
            f"{history_text}\n\n"
            f"Current user message:\n"
            f"{transcript}\n\n"
            f"Answer:"
        )

    def build_web_search(
        self,
        transcript: str,
        history: list,
        profile: dict | None = None,
    ) -> str:
        web_search_prompt = self._fetch_web_search_prompt()
        history_text = self._format_history(history)
        profile_text = ProfileStore.format_for_prompt(profile)

        return (
            f"{web_search_prompt}\n\n"
            f"User profile:\n"
            f"{profile_text}\n\n"
            f"Previous conversations:\n"
            f"{history_text}\n\n"
            f"Current user message:\n"
            f"{transcript}\n\n"
            f"Answer:"
        )

    def build_with_tool_result(
        self,
        transcript: str,
        history: list,
        tool_name: str,
        tool_result: str,
        profile: dict | None = None,
    ) -> str:
        system_prompt = self._fetch_system_prompt()
        history_text = self._format_history(history)
        profile_text = ProfileStore.format_for_prompt(profile)

        return (
            f"{system_prompt}\n\n"
            f"User profile:\n"
            f"{profile_text}\n\n"
            f"Previous conversations:\n"
            f"{history_text}\n\n"
            f"Tool ({tool_name}) result:\n"
            f"{tool_result}\n\n"
            f"Current user message:\n"
            f"{transcript}\n\n"
            f"Answer:"
        )

    def build_holding_response(self, transcript: str) -> str:
        holding_prompt = self._fetch_holding_prompt()

        return generate_holding_response(
            holding_prompt,
            transcript,
        )

    def _fetch_system_prompt(self) -> str:
        pipeline_start(
            "langfuse.prompt",
            "Fetching system prompt from Langfuse",
            {"prompt_name": "system-prompt-luvio"},
        )
        prompt = self.prompts.system_prompt()
        pipeline_complete(
            "langfuse.prompt",
            "System prompt loaded from Langfuse",
            {"prompt_length": len(prompt)},
        )
        return prompt

    def _fetch_web_search_prompt(self) -> str:
        pipeline_start(
            "langfuse.prompt",
            "Fetching web-search prompt from Langfuse",
            {"prompt_name": "web-search-luvio"},
        )
        prompt = self.prompts.web_search_prompt()
        pipeline_complete(
            "langfuse.prompt",
            "Web-search prompt loaded from Langfuse",
            {"prompt_length": len(prompt)},
        )
        return prompt

    def _fetch_holding_prompt(self) -> str:
        pipeline_start(
            "langfuse.prompt",
            "Fetching holding-response prompt from Langfuse",
            {"prompt_name": "holding-response-luvio"},
        )
        prompt = self.prompts.holding_response_prompt()
        pipeline_complete(
            "langfuse.prompt",
            "Holding-response prompt loaded from Langfuse",
            {"prompt_length": len(prompt)},
        )
        return prompt

    def _format_history(
        self,
        history: list
    ) -> str:
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
