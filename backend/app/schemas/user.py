from datetime import datetime
from app.models.user import UserRole
from pydantic import BaseModel, ConfigDict, EmailStr

class UserUpdate(BaseModel):
    name: str | None = None
    career: str | None = None

class UserRead(BaseModel):
    id: int
    name: str
    email: str
    career: str | None
    role: UserRole          # <-- agregar esto
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)