from dataclasses import dataclass
from datetime import datetime
import uuid


@dataclass
class ConversationSession:
    session_id: str
    created_at: datetime
    

    @classmethod
    def create(cls):
        return cls(
            session_id=str(uuid.uuid4()),
            created_at=datetime.utcnow()
        )