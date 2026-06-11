from app.conversation.transcriber import transcribe_audio
from app.conversation.responder import generate_response
from app.storage.transcript_store import TranscriptStore
from app.memory.short_term import ShortTermMemory
from app.context.prompt_builder import PromptBuilder


class IntelligenceOrchestrator:

    def __init__(self):

        self.store = TranscriptStore()
        self.stm = ShortTermMemory()
        self.prompt_builder = PromptBuilder()

    def process_audio(
        self,
        audio_path: str
    ):

        history = (
            self.stm.get_recent_conversations()
        )

        print(
            f"Loaded {len(history)} conversations"
        )

        transcript = transcribe_audio(
            audio_path
        )

        prompt = (
            self.prompt_builder.build(
                transcript,
                history
            )
        )

        response = generate_response(
            prompt
        )

        self.store.save(
            transcript,
            response
        )

        return {
            "transcript": transcript,
            "response": response
        }