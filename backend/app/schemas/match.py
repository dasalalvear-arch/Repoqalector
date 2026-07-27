from datetime import datetime

from pydantic import BaseModel, Field

from app.models.match import MatchStatus


class MatchCreate(BaseModel):
    item_id: int
    # Un match no puede existir sin un primer mensaje al donante: el mensaje
    # se crea junto con la solicitud (ver create_match).
    message: str = Field(min_length=1, max_length=500)


class MatchUpdate(BaseModel):
    status: MatchStatus


class MatchRequester(BaseModel):
    id: int
    name: str

    model_config = {"from_attributes": True}


class MatchItemBrief(BaseModel):
    id: int
    title: str

    model_config = {"from_attributes": True}


class MatchRead(BaseModel):
    id: int
    item_id: int
    requester_id: int
    owner_id: int
    status: MatchStatus
    created_at: datetime
    requester: MatchRequester
    item: MatchItemBrief

    model_config = {"from_attributes": True}
