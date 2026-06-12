from app.config import (
    LANGFUSE_PROMPT_LABEL,
    SYSTEM_PROMPT_NAME,
    WEB_SEARCH_PROMPT_NAME,
    HOLDING_RESPONSE_PROMPT_NAME,
)

from app.prompts.langfuse_client import langfuse


class PromptRegistry:
    
    def get_text_prompt(self, name: str) -> str:
        prompt = langfuse.get_prompt(
            name,
            label=LANGFUSE_PROMPT_LABEL,
        )

        return prompt.compile()

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