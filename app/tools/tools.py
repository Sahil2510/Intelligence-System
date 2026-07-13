import json
import re
from functools import lru_cache
from pathlib import Path

from app.context.prompt_builder import PromptBuilder
from app.config import GEMINI_MODEL
from app.conversation.responder import (
    classify_intent_with_llm,
    generate_response,
    generate_with_google_search,
    stream_response,
)
from app.tools.spotify_client import SpotifyClient
from app.utils.pipeline_log import pipeline_complete, pipeline_start
from ai_notes.pipeline.retrieval_handler import stream_meeting_notes_response

TOOLS_JSON = Path(__file__).parent / "tools.json"
_spotify_client = SpotifyClient()

VALID_INTENTS = {"normal", "web_search", "spotify", "meeting_notes"}

_WEB_HINTS = (
    "weather",
    "forecast",
    "temperature",
    "mausam",
    "news",
    "score",
    "stock",
    "price",
    "who is the",
    "who is ",
    "current president",
    "current pm",
    "president of usa",
    "president of the usa",
    "president of us",
    "president of the us",
    "president of america",
    "president of the united states",
    "prime minister of india",
    "pm of india",
    "chief minister",
    "cm of",
    "governor of",
    "mayor of",
    "ceo of",
    "chairman of",
    "current leader",
    "today's",
    "today ",
    "latest ",
    "live ",
)

_CURRENT_OFFICE_PATTERNS = (
    re.compile(
        r"\bwho\s+is\s+(the\s+)?(current\s+)?"
        r"(president|prime\s+minister|pm|chief\s+minister|cm|governor|mayor)"
        r"\s+of\b"
    ),
    re.compile(
        r"\bwho\s+is\s+(the\s+)?(current\s+)?"
        r"(ceo|chair(?:man|person)|head|leader)\s+of\b"
    ),
)

_SPOTIFY_HINTS = (
    "spotify",
    "play ",
    "pause",
    "resume",
    "skip",
    "next song",
    "previous song",
    "gana",
    "bajao",
    "gaana",
    "now playing",
)

_MEETING_NOTES_HINTS = (
    "meeting notes",
    "last meeting",
    "latest meeting",
    "recent meeting",
    "action items",
    "pending tasks",
    "completed tasks",
    "what happened in the meeting",
    "what did we discuss",
    "what was discussed",
    "meeting summary",
    "my meetings",
)


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
        "meetingnotes": "meeting_notes",
        "meeting": "meeting_notes",
        "notes": "meeting_notes",
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


def classify_intent_fast(transcript: str) -> str | None:
    cleaned = transcript.lower().strip()

    if not cleaned:
        return None

    if "spotify" in cleaned:
        return "spotify"

    if any(hint in cleaned for hint in _MEETING_NOTES_HINTS):
        return "meeting_notes"

    if any(hint in cleaned for hint in _SPOTIFY_HINTS):
        if any(
            word in cleaned
            for word in (
                "song",
                "music",
                "gana",
                "gaana",
                "artist",
                "album",
                "track",
                "spotify",
            )
        ):
            return "spotify"

    if any(hint in cleaned for hint in _WEB_HINTS):
        return "web_search"

    if any(pattern.search(cleaned) for pattern in _CURRENT_OFFICE_PATTERNS):
        return "web_search"

    return None


def classify_intent(transcript: str) -> str:
    pipeline_start(
        "intent.classify",
        "Classifying user intent",
        {"transcript": transcript},
    )

    fast_intent = classify_intent_fast(transcript)

    if fast_intent:
        pipeline_complete(
            "intent.classify",
            f"Intent classified as {fast_intent}",
            {
                "intent": fast_intent,
                "method": "heuristic",
            },
        )
        return fast_intent

    llm_intent = _normalize_intent(
        classify_intent_with_llm(transcript)
    )

    pipeline_complete(
        "intent.classify",
        f"Intent classified as {llm_intent}",
        {
            "intent": llm_intent,
            "method": GEMINI_MODEL,
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


def build_prompt_for_intent(
    intent: str,
    transcript: str,
    history: list,
    prompt_builder: PromptBuilder,
    profile: dict | None = None,
    ltm_memories: list | None = None,
) -> tuple[str, bool]:
    if intent == "web_search":
        return (
            prompt_builder.build_web_search(
                transcript,
                history,
                profile=profile,
                ltm_memories=ltm_memories,
            ),
            True,
        )

    return (
        prompt_builder.build(
            transcript,
            history,
            profile=profile,
            ltm_memories=ltm_memories,
        ),
        False,
    )


def stream_tool_response(
    intent: str,
    transcript: str,
    history: list,
    prompt_builder: PromptBuilder,
    profile: dict | None = None,
    ltm_memories: list | None = None,
    user_id: str | None = None,
):
    if intent == "web_search":
        pipeline_start(
            "llm.web_search",
            "Streaming web-search response with Google Search grounding",
            {"model": GEMINI_MODEL},
        )
        prompt, use_search = build_prompt_for_intent(
            intent,
            transcript,
            history,
            prompt_builder,
            profile=profile,
            ltm_memories=ltm_memories,
        )
        yield from stream_response(prompt, use_google_search=use_search)
        pipeline_complete(
            "llm.web_search",
            "Web search response stream completed",
            {},
        )
        return

    if intent == "spotify":
        outcome = _spotify_client.handle_user_request(transcript)
        playback = outcome.get("playback")

        if (playback or {}).get("action") == "play":
            return

        prompt = prompt_builder.build_with_tool_result(
            transcript=transcript,
            history=history,
            tool_name="spotify",
            tool_result=outcome["message"],
            profile=profile,
            ltm_memories=ltm_memories,
        )
        yield from stream_response(prompt)
        return

    if intent == "meeting_notes":
        pipeline_start(
            "ai-notes.retrieval",
            "Streaming meeting notes retrieval response",
            {"model": GEMINI_MODEL},
        )
        from app.config import DEFAULT_USER_ID

        resolved_user_id = (user_id or DEFAULT_USER_ID).strip() or DEFAULT_USER_ID

        yield from stream_meeting_notes_response(
            transcript,
            user_id=resolved_user_id,
        )
        pipeline_complete(
            "ai-notes.retrieval",
            "Meeting notes retrieval stream completed",
            {},
        )
        return

    pipeline_start(
        "llm.response",
        "Streaming response with Langfuse system prompt",
        {"model": GEMINI_MODEL},
    )
    prompt, _ = build_prompt_for_intent(
        intent,
        transcript,
        history,
        prompt_builder,
        profile=profile,
        ltm_memories=ltm_memories,
    )
    yield from stream_response(prompt)
    pipeline_complete(
        "llm.response",
        "System prompt response stream completed",
        {},
    )


def execute_tool(
    intent: str,
    transcript: str,
    history: list,
    prompt_builder: PromptBuilder,
    profile: dict | None = None,
    ltm_memories: list | None = None,
    user_id: str | None = None,
) -> str:
    if intent == "web_search":
        pipeline_start(
            "llm.web_search",
            "Generating response with Langfuse web-search prompt and Google Search",
            {"model": GEMINI_MODEL},
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

    if intent == "meeting_notes":
        from app.config import DEFAULT_USER_ID

        resolved_user_id = (user_id or DEFAULT_USER_ID).strip() or DEFAULT_USER_ID
        parts = list(
            stream_meeting_notes_response(
                transcript,
                user_id=resolved_user_id,
            )
        )
        return "".join(parts)

    pipeline_start(
        "llm.response",
        "Generating response with Langfuse system prompt",
        {"model": GEMINI_MODEL},
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
