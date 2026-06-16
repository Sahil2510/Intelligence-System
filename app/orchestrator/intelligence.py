from app.config import DEFAULT_USER_ID, STM_HISTORY_TURN_LIMIT
from app.conversation.transcriber import (
    transcribe_audio,
    transcribe_audio_bytes,
)
from app.conversation.responder import generate_speech
from app.conversation.language import detect_language_hint
from app.conversation.tts_jobs import start_tts_job
from app.storage.transcript_store import TranscriptStore
from app.storage.chat_store import ChatStore
from app.memory.short_term import RedisShortTermMemory
from app.memory.long_term import LongTermMemory
from app.context.prompt_builder import PromptBuilder
from app.tools.tools import (
    classify_intent,
    execute_tool,
    run_spotify_query,
    should_show_holding,
)
from app.utils.pipeline_log import pipeline_complete, pipeline_error, pipeline_start

FAST_HOLDING_RESPONSE = "One moment, I'll check that for you."


class IntelligenceOrchestrator:

    def __init__(self):
        self.store = TranscriptStore()
        self.chats = ChatStore()
        self.stm = RedisShortTermMemory()
        self.ltm = LongTermMemory()
        self.prompt_builder = PromptBuilder()

    def list_chats(self) -> list[dict]:
        return self.chats.list_chats()

    def create_chat(self, title: str = "New chat") -> dict:
        return self.chats.create_chat(title)

    def get_chat(self, chat_id: str) -> dict | None:
        return self.chats.get_chat(chat_id)

    def delete_chat(self, chat_id: str) -> bool:
        return self.chats.delete_chat(chat_id)

    def generate_tts(
        self,
        text: str,
        transcript: str = "",
    ) -> dict:
        language_hint = detect_language_hint(
            transcript,
            text,
        )

        return generate_speech(
            text,
            language_hint=language_hint,
        )

    @staticmethod
    def _resolve_user_id(user_id: str | None) -> str:
        cleaned = (user_id or "").strip()
        return cleaned or DEFAULT_USER_ID

    def _load_history(
        self,
        chat_id: str | None = None,
    ) -> list:
        if not chat_id:
            pipeline_start(
                "memory.stm.load",
                "No chat_id provided; short-term memory unavailable",
                {"turn_count": 0},
            )
            pipeline_complete(
                "memory.stm.load",
                "Short-term memory skipped",
                {"turn_count": 0},
            )
            return []

        try:
            return self.stm.get_history(
                chat_id,
                limit=STM_HISTORY_TURN_LIMIT,
            )
        except Exception:
            pipeline_start(
                "memory.stm.load",
                "Falling back to chat file history",
                {
                    "backend": "chat_store",
                    "chat_id": chat_id,
                    "turn_limit": STM_HISTORY_TURN_LIMIT,
                },
            )
            history = self.chats.get_history(
                chat_id,
                limit=STM_HISTORY_TURN_LIMIT,
            )
            pipeline_complete(
                "memory.stm.load",
                "Short-term memory loaded from chat file fallback",
                {
                    "backend": "chat_store",
                    "chat_id": chat_id,
                    "turn_count": len(history),
                },
            )
            return history

    def _load_ltm(
        self,
        user_id: str,
        transcript: str,
    ) -> list[dict]:
        return self.ltm.search(
            user_id=user_id,
            query=transcript,
        )

    @staticmethod
    def _memory_response_text(
        response: str,
        spotify_playback: dict | None,
    ) -> str:
        if response.strip():
            return response

        if not spotify_playback or spotify_playback.get("action") != "play":
            return response

        tracks = spotify_playback.get("tracks") or []
        index = spotify_playback.get("index") or 0

        if not tracks or index >= len(tracks):
            return response

        label = tracks[index].get("label") or tracks[index].get("name") or "track"
        return f"[Played: {label}]"

    def _save_memories(
        self,
        *,
        user_id: str,
        chat_id: str | None,
        transcript: str,
        response: str,
        intent: str,
        spotify_playback: dict | None,
    ) -> None:
        memory_response = self._memory_response_text(
            response,
            spotify_playback,
        )

        if chat_id:
            try:
                self.stm.append_turn(
                    chat_id,
                    transcript,
                    memory_response,
                )
            except Exception:
                pipeline_error(
                    "memory.stm.save",
                    "Redis save failed; chat UI history will still be stored",
                    {"chat_id": chat_id},
                )

            self.chats.append_turn(
                chat_id,
                transcript,
                memory_response,
            )

        self.ltm.add_turn(
            user_id=user_id,
            transcript=transcript,
            response=memory_response,
            chat_id=chat_id,
            intent=intent,
        )

        pipeline_start(
            "memory.audit.save",
            "Saving audit transcript log",
            {
                "transcript_preview": transcript[:120],
                "response_preview": memory_response[:120],
            },
        )
        self.store.save(
            transcript,
            memory_response,
        )
        pipeline_complete(
            "memory.audit.save",
            "Audit transcript log saved",
            {"saved": True},
        )

    def process_audio(
        self,
        audio_path: str,
        chat_id: str | None = None,
        user_id: str | None = None,
    ):
        history = self._load_history(chat_id)

        transcript = transcribe_audio(
            audio_path
        )

        return self.process_transcript(
            transcript,
            history=history,
            chat_id=chat_id,
            user_id=user_id,
        )

    def process_audio_bytes(
        self,
        audio_bytes: bytes,
        mime_type: str = "audio/webm",
        chat_id: str | None = None,
        user_id: str | None = None,
    ):
        pipeline_start(
            "session.start",
            "Starting full audio query pipeline",
            {
                "mime_type": mime_type,
                "audio_bytes": len(audio_bytes),
            },
        )

        result = self.process_voice_query(
            audio_bytes=audio_bytes,
            mime_type=mime_type,
            chat_id=chat_id,
            user_id=user_id,
        )

        pipeline_complete(
            "session.complete",
            "Full audio query pipeline completed",
            {"intent": result["intent"]},
        )

        return result

    def transcribe_audio_bytes(
        self,
        audio_bytes: bytes,
        mime_type: str = "audio/webm",
    ) -> dict:
        pipeline_start(
            "session.update",
            "Audio received from playground",
            {
                "mime_type": mime_type,
                "audio_bytes": len(audio_bytes),
            },
        )

        transcript = transcribe_audio_bytes(
            audio_bytes=audio_bytes,
            mime_type=mime_type,
        )

        return self.prepare_text_query(transcript)

    def prepare_text_query(self, transcript: str) -> dict:
        pipeline_start(
            "session.update",
            "Text query received from playground",
            {"transcript": transcript},
        )

        intent = classify_intent(transcript)

        pipeline_complete(
            "session.update",
            "Text query classified",
            {
                "intent": intent,
                "needs_holding": should_show_holding(intent),
            },
        )

        return {
            "transcript": transcript,
            "intent": intent,
            "needs_holding": should_show_holding(intent),
            "holding_response": self._fast_holding(intent),
        }

    def process_query(
        self,
        transcript: str,
        chat_id: str | None = None,
        intent: str | None = None,
        profile: dict | None = None,
        user_id: str | None = None,
    ) -> dict:
        pipeline_start(
            "query.start",
            "Running merged classify and respond pipeline",
            {"transcript": transcript},
        )

        if intent is None:
            intent = classify_intent(transcript)

        holding_response = self._fast_holding(intent)

        result = self.process_transcript(
            transcript,
            chat_id=chat_id,
            intent=intent,
            profile=profile,
            user_id=user_id,
        )
        result["holding_response"] = holding_response

        pipeline_complete(
            "query.complete",
            "Merged query pipeline completed",
            {"intent": intent},
        )

        return result

    def process_voice_query(
        self,
        audio_bytes: bytes,
        mime_type: str = "audio/webm",
        chat_id: str | None = None,
        profile: dict | None = None,
        user_id: str | None = None,
    ) -> dict:
        pipeline_start(
            "voice.query.start",
            "Running merged transcribe and respond pipeline",
            {"mime_type": mime_type},
        )

        transcript = transcribe_audio_bytes(
            audio_bytes=audio_bytes,
            mime_type=mime_type,
        )

        result = self.process_query(
            transcript,
            chat_id=chat_id,
            profile=profile,
            user_id=user_id,
        )
        result["transcript"] = transcript

        pipeline_complete(
            "voice.query.complete",
            "Merged voice query pipeline completed",
            {"intent": result["intent"]},
        )

        return result

    def build_holding_response(self, transcript: str) -> str:
        pipeline_start(
            "holding.start",
            "Starting holding response generation",
            {"transcript": transcript},
        )
        response = self.prompt_builder.build_holding_response(
            transcript
        )
        pipeline_complete(
            "holding.complete",
            "Holding response ready",
            {"response_length": len(response)},
        )
        return response

    def process_transcript(
        self,
        transcript: str,
        history: list | None = None,
        intent: str | None = None,
        chat_id: str | None = None,
        profile: dict | None = None,
        user_id: str | None = None,
    ):
        resolved_user_id = self._resolve_user_id(user_id)

        pipeline_start(
            "response.start",
            "Starting response generation",
            {
                "transcript": transcript,
                "user_id": resolved_user_id,
                "chat_id": chat_id,
            },
        )

        if history is None:
            history = self._load_history(chat_id)

        ltm_memories = self._load_ltm(
            resolved_user_id,
            transcript,
        )

        if intent is None:
            intent = classify_intent(transcript)
        else:
            pipeline_complete(
                "intent.classify",
                f"Using intent from earlier step: {intent}",
                {
                    "intent": intent,
                    "method": "cached",
                },
            )

        spotify_playback = None

        if intent == "spotify":
            response, spotify_playback = run_spotify_query(
                transcript,
                history,
                self.prompt_builder,
                profile=profile,
                ltm_memories=ltm_memories,
            )
        else:
            response = execute_tool(
                intent=intent,
                transcript=transcript,
                history=history,
                prompt_builder=self.prompt_builder,
                profile=profile,
                ltm_memories=ltm_memories,
            )

        tts_id = None
        if not (
            spotify_playback
            and spotify_playback.get("action") == "play"
        ):
            tts_id = start_tts_job(
                response,
                transcript=transcript,
            )

        if tts_id:
            pipeline_complete(
                "tts.prefetch",
                "Started background TTS generation",
                {"tts_id": tts_id},
            )

        self._save_memories(
            user_id=resolved_user_id,
            chat_id=chat_id,
            transcript=transcript,
            response=response,
            intent=intent,
            spotify_playback=spotify_playback,
        )

        pipeline_complete(
            "response.complete",
            "Final response ready",
            {
                "intent": intent,
                "response_length": len(response),
                "user_id": resolved_user_id,
                "ltm_memory_count": len(ltm_memories),
            },
        )

        return {
            "transcript": transcript,
            "intent": intent,
            "response": response,
            "needs_holding": should_show_holding(intent),
            "tts_id": tts_id,
            "spotify_playback": spotify_playback,
            "user_id": resolved_user_id,
        }

    def _fast_holding(self, intent: str) -> str | None:
        if should_show_holding(intent):
            return FAST_HOLDING_RESPONSE

        return None

    def memory_status(self) -> dict:
        return {
            "stm": {
                "backend": "redis",
                "connected": self.stm.ping(),
                "redis_url": self.stm.redis_url,
                "turn_limit": STM_HISTORY_TURN_LIMIT,
            },
            "ltm": {
                "backend": "mem0",
                "enabled": self.ltm.enabled,
                "search_limit": self.ltm.search_limit,
            },
        }
