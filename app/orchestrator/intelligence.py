from app.conversation.transcriber import (
    transcribe_audio,
    transcribe_audio_bytes,
)
from app.conversation.responder import generate_speech
from app.conversation.language import detect_language_hint
from app.storage.transcript_store import TranscriptStore
from app.storage.chat_store import ChatStore
from app.storage.profile_store import ProfileStore
from app.memory.short_term import ShortTermMemory
from app.context.prompt_builder import PromptBuilder
from app.tools.tools import (
    classify_intent,
    execute_tool,
    should_show_holding,
)
from app.utils.pipeline_log import pipeline_complete, pipeline_start

FAST_HOLDING_RESPONSE = "One moment, I'll check that for you."


class IntelligenceOrchestrator:

    def __init__(self):
        self.store = TranscriptStore()
        self.chats = ChatStore()
        self.profiles = ProfileStore()
        self.stm = ShortTermMemory()
        self.prompt_builder = PromptBuilder()

    def list_chats(self) -> list[dict]:
        return self.chats.list_chats()

    def create_chat(self, title: str = "New chat") -> dict:
        return self.chats.create_chat(title)

    def get_chat(self, chat_id: str) -> dict | None:
        return self.chats.get_chat(chat_id)

    def delete_chat(self, chat_id: str) -> bool:
        return self.chats.delete_chat(chat_id)

    def get_profile(self) -> dict:
        profile = self.profiles.get()
        profile["display_name"] = self.profiles.display_name()
        profile["initials"] = self.profiles.initials()
        return profile

    def save_profile(self, profile: dict) -> dict:
        saved = self.profiles.save(profile)
        saved["display_name"] = self.profiles.display_name()
        saved["initials"] = self.profiles.initials()
        return saved

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

    def _load_history(
        self,
        chat_id: str | None = None,
    ) -> list:
        if chat_id:
            pipeline_start(
                "memory.load",
                "Loading conversation history for active chat",
                {"chat_id": chat_id},
            )
            history = self.chats.get_history(chat_id)
            pipeline_complete(
                "memory.load",
                "Chat history loaded",
                {"history_count": len(history)},
            )
            return history

        pipeline_start(
            "memory.load",
            "Loading short-term conversation history",
        )
        history = self.stm.get_recent_conversations()
        pipeline_complete(
            "memory.load",
            "Short-term history loaded",
            {"history_count": len(history)},
        )
        return history

    def process_audio(
        self,
        audio_path: str,
        chat_id: str | None = None,
    ):
        history = self._load_history(chat_id)

        transcript = transcribe_audio(
            audio_path
        )

        return self.process_transcript(
            transcript,
            history=history,
            chat_id=chat_id,
        )

    def process_audio_bytes(
        self,
        audio_bytes: bytes,
        mime_type: str = "audio/webm",
        chat_id: str | None = None,
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
    ):
        pipeline_start(
            "response.start",
            "Starting response generation",
            {"transcript": transcript},
        )

        if history is None:
            history = self._load_history(chat_id)

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

        response = execute_tool(
            intent=intent,
            transcript=transcript,
            history=history,
            prompt_builder=self.prompt_builder,
        )

        pipeline_start(
            "memory.save",
            "Saving transcript and response",
        )
        self.store.save(
            transcript,
            response
        )

        if chat_id:
            self.chats.append_turn(
                chat_id,
                transcript,
                response,
            )

        pipeline_complete(
            "memory.save",
            "Transcript stored to disk",
        )

        pipeline_complete(
            "response.complete",
            "Final response ready",
            {
                "intent": intent,
                "response_length": len(response),
            },
        )

        return {
            "transcript": transcript,
            "intent": intent,
            "response": response,
            "needs_holding": should_show_holding(intent),
        }

    def _fast_holding(self, intent: str) -> str | None:
        if should_show_holding(intent):
            return FAST_HOLDING_RESPONSE

        return None
