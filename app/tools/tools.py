import json
from functools import lru_cache
from pathlib import Path

from app.context.prompt_builder import PromptBuilder
from app.conversation.responder import (
    classify_intent_with_llm,
    generate_response,
    generate_with_google_search,
)
from app.utils.pipeline_log import pipeline_complete, pipeline_start

TOOLS_JSON = Path(__file__).parent / "tools.json"

VALID_INTENTS = {"normal", "web_search", "spotify"}


@lru_cache
def _load_config() -> dict:
    with TOOLS_JSON.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _enabled_tools() -> list[dict]:
    return [
        tool
        for tool in _load_config().get("tools", [])
        if tool.get("enabled", True)
    ]


def _normalize_intent(raw_intent: str) -> str:
    cleaned = (
        raw_intent.strip()
        .lower()
        .replace("`", "")
        .replace("-", "_")
    )

    aliases = {
        "websearch": "web_search",
        "web": "web_search",
        "search": "web_search",
        "google_search": "web_search",
    }

    if cleaned in aliases:
        cleaned = aliases[cleaned]

    if cleaned in VALID_INTENTS:
        return cleaned

    if "web" in cleaned and "search" in cleaned:
        return "web_search"

    return _load_config().get("default_intent", "normal")


def classify_intent(transcript: str) -> str:
    pipeline_start(
        "intent.classify",
        "Classifying user intent with Gemini",
        {"transcript": transcript},
    )

    llm_intent = _normalize_intent(
        classify_intent_with_llm(transcript)
    )

    pipeline_complete(
        "intent.classify",
        f"Intent classified as {llm_intent}",
        {
            "intent": llm_intent,
            "method": "gemini-2.5-flash",
        },
    )
    return llm_intent


def should_show_holding(intent: str) -> bool:
    if intent == "normal":
        return False

    for tool in _enabled_tools():
        if tool["name"] == intent:
            return tool.get("show_holding_response", False)

    return False


def execute_tool(
    intent: str,
    transcript: str,
    history: list,
    prompt_builder: PromptBuilder,
) -> str:
    if intent == "web_search":
        pipeline_start(
            "llm.web_search",
            "Generating response with Langfuse web-search prompt and Google Search",
            {"model": "gemini-2.5-flash"},
        )
        prompt = prompt_builder.build_web_search(
            transcript,
            history,
        )
        response = generate_with_google_search(prompt)
        pipeline_complete(
            "llm.web_search",
            "Web search response generated",
            {"response_length": len(response)},
        )
        return response

    if intent == "spotify":
        pipeline_start(
            "tool.spotify",
            "Running Spotify tool path",
        )
        response = _run_spotify(
            transcript,
            history,
            prompt_builder,
        )
        pipeline_complete(
            "tool.spotify",
            "Spotify tool path completed",
            {"response_length": len(response)},
        )
        return response

    pipeline_start(
        "llm.response",
        "Generating response with Langfuse system prompt",
        {"model": "gemini-2.5-flash"},
    )
    prompt = prompt_builder.build(
        transcript,
        history,
    )
    response = generate_response(prompt)
    pipeline_complete(
        "llm.response",
        "System prompt response generated",
        {"response_length": len(response)},
    )
    return response


def _run_spotify(
    transcript: str,
    history: list,
    prompt_builder: PromptBuilder,
) -> str:
    tool_result = (
        "Spotify is not connected yet. "
        "Acknowledge the music request briefly and say playback control "
        "will be available once Spotify is linked."
    )

    prompt = prompt_builder.build_with_tool_result(
        transcript=transcript,
        history=history,
        tool_name="spotify",
        tool_result=tool_result,
    )

    return generate_response(prompt)
