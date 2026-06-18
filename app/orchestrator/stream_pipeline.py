from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Iterator

from app.conversation.sentence_buffer import SentenceBuffer
from app.conversation.transcriber import transcribe_audio_bytes
from app.conversation.tts_jobs import start_tts_job
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


def _emit_tts_for_sentences(
    sentences: list[str],
    *,
    transcript: str,
    start_index: int,
) -> Iterator[dict[str, Any]]:
    for offset, sentence in enumerate(sentences):
        job_id = start_tts_job(sentence, transcript=transcript)

        if not job_id:
            continue

        yield {
            "type": "tts",
            "job_id": job_id,
            "sentence_index": start_index + offset,
            "text_preview": sentence[:120],
        }


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
        "holding_response": (
            FAST_HOLDING_RESPONSE
            if should_show_holding(intent)
            else None
        ),
    }

    spotify_playback = None
    response_parts: list[str] = []
    sentence_buffer = SentenceBuffer()
    tts_sentence_index = 0
    skip_tts = False

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
                for event in _emit_tts_for_sentences(
                    [response],
                    transcript=transcript,
                    start_index=tts_sentence_index,
                ):
                    tts_sentence_index += 1
                    yield event
    else:
        for token in stream_tool_response(
            intent,
            transcript,
            history,
            orchestrator.prompt_builder,
            profile=profile,
            ltm_memories=ltm_memories,
        ):
            response_parts.append(token)
            yield {"type": "token", "text": token}

            for sentence in sentence_buffer.push(token):
                if skip_tts:
                    continue

                for event in _emit_tts_for_sentences(
                    [sentence],
                    transcript=transcript,
                    start_index=tts_sentence_index,
                ):
                    tts_sentence_index += 1
                    yield event

        remainder = sentence_buffer.flush()

        if remainder and not skip_tts:
            for event in _emit_tts_for_sentences(
                [remainder],
                transcript=transcript,
                start_index=tts_sentence_index,
            ):
                tts_sentence_index += 1
                yield event

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
