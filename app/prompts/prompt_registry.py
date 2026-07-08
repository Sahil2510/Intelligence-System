import time

from app.config import (
    HOLDING_RESPONSE_PROMPT_NAME,
    LANGFUSE_PROMPT_LABEL,
    MEETING_NOTES_EXTRACT_PROMPT_NAME,
    MEETING_NOTES_RETRIEVAL_PROMPT_NAME,
    SYSTEM_PROMPT_NAME,
    WEB_SEARCH_PROMPT_NAME,
)

from app.prompts.langfuse_client import langfuse

PROMPT_CACHE_TTL_SECONDS = 300
_prompt_cache: dict[str, tuple[str, float]] = {}


class PromptRegistry:

    def get_text_prompt(self, name: str) -> str:
        cached = _prompt_cache.get(name)

        if cached and (time.time() - cached[1]) < PROMPT_CACHE_TTL_SECONDS:
            return cached[0]

        prompt = langfuse.get_prompt(
            name,
            label=LANGFUSE_PROMPT_LABEL,
        )
        compiled = prompt.compile()
        _prompt_cache[name] = (compiled, time.time())
        return compiled

    def system_prompt(self) -> str:
        return self.get_text_prompt(
            SYSTEM_PROMPT_NAME
        )

    def web_search_prompt(self) -> str:
        return self.get_text_prompt(
            WEB_SEARCH_PROMPT_NAME
        )

    def holding_response_prompt(self) -> str:
        return self.get_text_prompt(
            HOLDING_RESPONSE_PROMPT_NAME
        )

    def meeting_notes_extract_prompt(self) -> str:
        return self.get_text_prompt(
            MEETING_NOTES_EXTRACT_PROMPT_NAME
        )

    def meeting_notes_retrieval_prompt(self) -> str:
        return self.get_text_prompt(
            MEETING_NOTES_RETRIEVAL_PROMPT_NAME
        )
