from __future__ import annotations

import json
import time
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any, Iterator

from app.conversation.language import detect_speech_locale
from app.config import STREAM_GEMINI_TTS
from app.conversation.language import detect_language_hint
from app.conversation.responder import generate_speech
from app.conversation.sentence_buffer import SpeakBuffer
from app.conversation.transcriber import transcribe_audio_bytes
from app.tools.tools import (
    classify_intent,
    run_spotify_query,
    should_show_holding,
    stream_tool_response,
)
from app.utils.pipeline_log import (
    PipelineLogger,
    pipeline_complete,
    pipeline_start,
    reset_pipeline_logger,
    set_pipeline_logger,
)

FAST_HOLDING_RESPONSE = "One moment, I'll check that for you."

_memory_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="memory")
_tts_stream_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="tts-stream")


def _load_context_parallel(orchestrator, chat_id, user_id, transcript):
    with ThreadPoolExecutor(max_workers=2) as pool:
        history_future = pool.submit(
            orchestrator._load_history,
            chat_id,
        )
        ltm_future = pool.submit(
            orchestrator._load_ltm,
            user_id,
            transcript,
        )
        history = history_future.result()
        ltm_memories = ltm_future.result()

    intent = classify_intent(transcript)
    return history, ltm_memories, intent


def _schedule_memory_save(orchestrator, **kwargs) -> None:
    _memory_executor.submit(
        orchestrator._save_memories,
        **kwargs,
    )


def _start_tts_future(sentence: str, transcript: str) -> Future:
    language_hint = detect_language_hint(transcript, sentence)
    return _tts_stream_executor.submit(
        generate_speech,
        sentence,
        language_hint,
    )


def _queue_tts_chunk(
    pending: list[tuple[int, Future]],
    index: int,
    sentence: str,
    transcript: str,
) -> int:
    cleaned = sentence.strip()

    if not cleaned:
        return index

    pending.append((index, _start_tts_future(cleaned, transcript)))
    return index + 1


def _yield_ready_tts(pending: list[tuple[int, Future]]) -> Iterator[dict[str, Any]]:
    pending.sort(key=lambda item: item[0])

    while pending and pending[0][1].done():
        sentence_index, future = pending.pop(0)

        try:
            audio = future.result()
            yield {
                "type": "tts_audio",
                "sentence_index": sentence_index,
                "audio_base64": audio["audio_base64"],
                "mime_type": audio["mime_type"],
            }
        except Exception as exc:
            yield {
                "type": "tts_error",
                "sentence_index": sentence_index,
                "message": str(exc),
            }


def _flush_pending_tts(pending: list[tuple[int, Future]]) -> Iterator[dict[str, Any]]:
    while pending:
        before = len(pending)
        yield from _yield_ready_tts(pending)

        if len(pending) == before and pending:
            time.sleep(0.02)


def _queue_speakable_chunks(
    pending_tts: list[tuple[int, Future]],
    chunks: list[str],
    *,
    transcript: str,
    start_index: int,
) -> int:
    index = start_index

    for chunk in chunks:
        index = _queue_tts_chunk(pending_tts, index, chunk, transcript)

    return index


def stream_query(
    orchestrator,
    transcript: str,
    *,
    chat_id: str | None = None,
    profile: dict | None = None,
    user_id: str | None = None,
) -> Iterator[dict[str, Any]]:
    resolved_user_id = orchestrator._resolve_user_id(user_id)

    pipeline_start(
        "query.stream.start",
        "Starting streaming query pipeline",
        {
            "transcript_preview": transcript[:120],
            "user_id": resolved_user_id,
            "chat_id": chat_id,
        },
    )

    history, ltm_memories, intent = _load_context_parallel(
        orchestrator,
        chat_id,
        resolved_user_id,
        transcript,
    )

    yield {
        "type": "intent",
        "intent": intent,
        "needs_holding": should_show_holding(intent),
        "google_search": intent == "web_search",
        "holding_response": (
            FAST_HOLDING_RESPONSE
            if should_show_holding(intent)
            else None
        ),
        "speech_lang": detect_speech_locale(transcript),
    }

    spotify_playback = None
    response_parts: list[str] = []
    speak_buffer = SpeakBuffer()
    pending_tts: list[tuple[int, Future]] = []
    tts_sentence_index = 0
    skip_tts = not STREAM_GEMINI_TTS

    if intent == "spotify":
        response, spotify_playback = run_spotify_query(
            transcript,
            history,
            orchestrator.prompt_builder,
            profile=profile,
            ltm_memories=ltm_memories,
        )

        skip_tts = (
            spotify_playback is not None
            and spotify_playback.get("action") == "play"
        )

        if spotify_playback:
            yield {
                "type": "spotify_playback",
                "playback": spotify_playback,
            }

        if response:
            response_parts.append(response)
            yield {"type": "token", "text": response}

            if not skip_tts:
                tts_sentence_index = _queue_speakable_chunks(
                    pending_tts,
                    [response],
                    transcript=transcript,
                    start_index=tts_sentence_index,
                )
                yield from _flush_pending_tts(pending_tts)
    else:
        for token in stream_tool_response(
            intent,
            transcript,
            history,
            orchestrator.prompt_builder,
            profile=profile,
            ltm_memories=ltm_memories,
            user_id=resolved_user_id,
        ):
            response_parts.append(token)
            yield {"type": "token", "text": token}

            if skip_tts:
                continue

            tts_sentence_index = _queue_speakable_chunks(
                pending_tts,
                speak_buffer.push(token),
                transcript=transcript,
                start_index=tts_sentence_index,
            )
            yield from _yield_ready_tts(pending_tts)

        remainder = speak_buffer.flush()

        if remainder and not skip_tts:
            tts_sentence_index = _queue_speakable_chunks(
                pending_tts,
                [remainder],
                transcript=transcript,
                start_index=tts_sentence_index,
            )

        yield from _flush_pending_tts(pending_tts)

    full_response = "".join(response_parts)

    _schedule_memory_save(
        orchestrator,
        user_id=resolved_user_id,
        chat_id=chat_id,
        transcript=transcript,
        response=full_response,
        intent=intent,
        spotify_playback=spotify_playback,
    )

    pipeline_complete(
        "query.stream.complete",
        "Streaming query pipeline completed",
        {
            "intent": intent,
            "response_length": len(full_response),
            "tts_sentences": tts_sentence_index,
        },
    )

    yield {
        "type": "done",
        "transcript": transcript,
        "intent": intent,
        "response": full_response,
        "spotify_playback": spotify_playback,
        "user_id": resolved_user_id,
    }


def stream_voice_query(
    orchestrator,
    audio_bytes: bytes,
    *,
    mime_type: str = "audio/webm",
    chat_id: str | None = None,
    profile: dict | None = None,
    user_id: str | None = None,
) -> Iterator[dict[str, Any]]:
    pipeline_start(
        "voice.stream.start",
        "Starting streaming voice query pipeline",
        {
            "mime_type": mime_type,
            "audio_bytes": len(audio_bytes),
        },
    )

    transcript = transcribe_audio_bytes(
        audio_bytes=audio_bytes,
        mime_type=mime_type,
    )

    yield {
        "type": "transcript",
        "text": transcript,
        "speech_lang": detect_speech_locale(transcript),
    }

    yield from stream_query(
        orchestrator,
        transcript,
        chat_id=chat_id,
        profile=profile,
        user_id=user_id,
    )

    pipeline_complete(
        "voice.stream.complete",
        "Streaming voice query pipeline completed",
        {"transcript_preview": transcript[:120]},
    )


def ndjson_event(event: dict[str, Any]) -> str:
    return json.dumps(event, ensure_ascii=False) + "\n"


def stream_ndjson_response(events: Iterator[dict[str, Any]]) -> Iterator[str]:
    """Wrap a pipeline event stream for Starlette StreamingResponse.

    Starlette pulls sync generators from a thread pool, so a single ContextVar
    scope cannot span the whole response. Bind the logger around each ``next()``
    on the underlying iterator instead.
    """
    pipeline_logger = PipelineLogger()
    event_iter = iter(events)

    while True:
        token = set_pipeline_logger(pipeline_logger)
        try:
            try:
                event = next(event_iter)
            except StopIteration:
                break
        finally:
            reset_pipeline_logger(token)

        if event.get("type") == "done":
            event["logs"] = pipeline_logger.to_list()

        yield ndjson_event(event)
