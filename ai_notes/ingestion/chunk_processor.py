from __future__ import annotations

from datetime import datetime
from pathlib import Path

from ai_notes.models.schemas import MeetingSession, TranscriptSegment
from app.conversation.transcriber import transcribe_audio_bytes
from app.utils.pipeline_log import pipeline_complete, pipeline_start


class ChunkProcessor:

    def transcribe_session(self, session: MeetingSession) -> tuple[str, list[TranscriptSegment]]:
        pipeline_start(
            "ai-notes.transcribe",
            "Transcribing meeting session chunks",
            {"chunk_count": len(session.chunks)},
        )

        segments: list[TranscriptSegment] = []
        parts: list[str] = []

        for chunk in session.chunks:
            chunk_path = Path(chunk.path)

            if not chunk_path.exists():
                continue

            audio_bytes = chunk_path.read_bytes()
            transcript = transcribe_audio_bytes(
                audio_bytes=audio_bytes,
                mime_type=chunk.mime_type,
            ).strip()

            if not transcript:
                continue

            segment = TranscriptSegment(
                index=chunk.index,
                transcript=transcript,
                recorded_at=chunk.recorded_at or datetime.utcnow().isoformat(),
            )
            segments.append(segment)
            parts.append(transcript)

        merged = "\n\n".join(parts)

        pipeline_complete(
            "ai-notes.transcribe",
            "Meeting session transcription completed",
            {
                "segment_count": len(segments),
                "transcript_length": len(merged),
            },
        )
        return merged, segments
