from datetime import datetime
from zoneinfo import ZoneInfo

from app.conversation.responder import generate_holding_response
from app.config import (
    HOLDING_RESPONSE_PROMPT_NAME,
    SYSTEM_PROMPT_NAME,
    WEB_SEARCH_PROMPT_NAME,
)
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
        ltm_memories: list | None = None,
    ) -> str:
        system_prompt = self._fetch_system_prompt()
        history_text = self._format_history(history)
        profile_text = ProfileStore.format_for_prompt(profile)
        ltm_text = self._format_ltm(ltm_memories)
        current_date = self._current_date_text()

        return (
            f"{system_prompt}\n\n"
            f"Current date:\n"
            f"{current_date}\n\n"
            f"User profile:\n"
            f"{profile_text}\n\n"
            f"Long-term memory:\n"
            f"{ltm_text}\n\n"
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
        ltm_memories: list | None = None,
    ) -> str:
        web_search_prompt = self._fetch_web_search_prompt()
        history_text = self._format_history(history)
        profile_text = ProfileStore.format_for_prompt(profile)
        ltm_text = self._format_ltm(ltm_memories)
        current_date = self._current_date_text()
        grounding_guardrail = self._web_grounding_guardrail()

        return (
            f"{grounding_guardrail}\n\n"
            f"Langfuse web-search prompt:\n"
            f"{web_search_prompt}\n\n"
            f"Current date:\n"
            f"{current_date}\n\n"
            f"User profile:\n"
            f"{profile_text}\n\n"
            f"Long-term memory:\n"
            f"{ltm_text}\n\n"
            f"Previous conversations:\n"
            f"{history_text}\n\n"
            f"Use previous conversations only for conversational context. "
            f"Never use previous assistant answers as evidence for current facts.\n\n"
            f"Final grounding reminder:\n"
            f"Use Google Search grounding now. If the current fact is not verified by search, say so instead of guessing.\n\n"
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
        ltm_memories: list | None = None,
    ) -> str:
        system_prompt = self._fetch_system_prompt()
        history_text = self._format_history(history)
        profile_text = ProfileStore.format_for_prompt(profile)
        ltm_text = self._format_ltm(ltm_memories)
        current_date = self._current_date_text()

        return (
            f"{system_prompt}\n\n"
            f"Current date:\n"
            f"{current_date}\n\n"
            f"User profile:\n"
            f"{profile_text}\n\n"
            f"Long-term memory:\n"
            f"{ltm_text}\n\n"
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
            {"prompt_name": SYSTEM_PROMPT_NAME},
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
            {"prompt_name": WEB_SEARCH_PROMPT_NAME},
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
            {"prompt_name": HOLDING_RESPONSE_PROMPT_NAME},
        )
        prompt = self.prompts.holding_response_prompt()
        pipeline_complete(
            "langfuse.prompt",
            "Holding-response prompt loaded from Langfuse",
            {"prompt_length": len(prompt)},
        )
        return prompt

    @staticmethod
    def _format_ltm(ltm_memories: list | None) -> str:
        if not ltm_memories:
            return "No long-term memories available."

        lines = []

        for item in ltm_memories:
            memory = item.get("memory", "").strip()

            if not memory:
                continue

            score = item.get("score")
            if score is None:
                lines.append(f"- {memory}")
            else:
                lines.append(f"- {memory} (score: {score})")

        if not lines:
            return "No long-term memories available."

        return "\n".join(lines)

    @staticmethod
    def _current_date_text() -> str:
        now = datetime.now(ZoneInfo("Asia/Kolkata"))
        return f"{now:%A, %B} {now.day}, {now:%Y}"

    @staticmethod
    def _web_grounding_guardrail() -> str:
        return (
            "Mandatory web-grounding rules:\n"
            "- This request was routed to web_search because the answer may be current or changing.\n"
            "- Use Google Search grounding for the answer. Do not answer from model memory.\n"
            "- For office holders, executives, leaders, prices, weather, scores, news, and dates, verify against current search results before answering.\n"
            "- If search grounding is unavailable or inconclusive, say you could not verify the current answer instead of guessing.\n"
            "- Prefer a direct answer with the as-of date. Do not add a generic follow-up question."
        )

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
