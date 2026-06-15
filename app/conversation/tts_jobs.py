from __future__ import annotations

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

from app.conversation.language import detect_language_hint
from app.conversation.responder import generate_speech

_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="tts")
_jobs: dict[str, dict] = {}
_lock = threading.Lock()


def start_tts_job(
    text: str,
    transcript: str = "",
) -> str | None:
    cleaned = text.strip()

    if not cleaned:
        return None

    job_id = uuid.uuid4().hex
    language_hint = detect_language_hint(
        transcript,
        cleaned,
    )

    with _lock:
        _jobs[job_id] = {
            "status": "pending",
            "result": None,
            "error": None,
        }

    _executor.submit(
        _run_job,
        job_id,
        cleaned,
        language_hint,
    )
    return job_id


def get_tts_job(job_id: str) -> dict | None:
    with _lock:
        job = _jobs.get(job_id)

        if job is None:
            return None

        return {
            "status": job["status"],
            "result": job["result"],
            "error": job["error"],
        }


def _run_job(
    job_id: str,
    text: str,
    language_hint: str | None,
) -> None:
    try:
        result = generate_speech(
            text,
            language_hint=language_hint,
        )
        status = "ready"
        error = None
    except Exception as exc:
        result = None
        status = "error"
        error = str(exc)

    with _lock:
        _jobs[job_id] = {
            "status": status,
            "result": result,
            "error": error,
        }
