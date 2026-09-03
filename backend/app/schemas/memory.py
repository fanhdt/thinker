import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class MemoryOut(BaseModel):
    id: uuid.UUID
    content: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
