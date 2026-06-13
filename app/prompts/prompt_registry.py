import time

from app.config import (
    LANGFUSE_PROMPT_LABEL,
    SYSTEM_PROMPT_NAME,
    WEB_SEARCH_PROMPT_NAME,
    HOLDING_RESPONSE_PROMPT_NAME,
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
