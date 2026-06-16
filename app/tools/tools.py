import json
from functools import lru_cache
from pathlib import Path

from app.context.prompt_builder import PromptBuilder
from app.conversation.responder import (
    classify_intent_with_llm,
    generate_response,
    generate_with_google_search,
)
from app.tools.spotify_client import SpotifyClient
from app.utils.pipeline_log import pipeline_complete, pipeline_start

TOOLS_JSON = Path(__file__).parent / "tools.json"
_spotify_client = SpotifyClient()

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

    if "spotify" in cleaned:
        return "spotify"

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
    profile: dict | None = None,
    ltm_memories: list | None = None,
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
            profile=profile,
            ltm_memories=ltm_memories,
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
            profile=profile,
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
        profile=profile,
        ltm_memories=ltm_memories,
    )
    response = generate_response(prompt)
    pipeline_complete(
        "llm.response",
        "System prompt response generated",
        {"response_length": len(response)},
    )
    return response


def run_spotify_query(
    transcript: str,
    history: list,
    prompt_builder: PromptBuilder,
    profile: dict | None = None,
    ltm_memories: list | None = None,
) -> tuple[str, dict | None]:
    outcome = _spotify_client.handle_user_request(transcript)
    tool_result = outcome["message"]
    playback = outcome.get("playback")

    if (playback or {}).get("action") == "play":
        return "", playback

    prompt = prompt_builder.build_with_tool_result(
        transcript=transcript,
        history=history,
        tool_name="spotify",
        tool_result=tool_result,
        profile=profile,
        ltm_memories=ltm_memories,
    )

    response = generate_response(prompt)
    return response, playback


def _run_spotify(
    transcript: str,
    history: list,
    prompt_builder: PromptBuilder,
    profile: dict | None = None,
) -> str:
    response, _playback = run_spotify_query(
        transcript,
        history,
        prompt_builder,
        profile=profile,
    )
    return response
