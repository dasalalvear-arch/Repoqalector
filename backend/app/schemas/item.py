from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.models.item import ItemStatus
from app.schemas.category import CategoryRead
from app.schemas.user import UserRead

# Solo http(s) o data:image/. Bloquea javascript:, file:, data:text/html, etc.
_ALLOWED_IMAGE_PREFIXES = ("http://", "https://", "data:image/")


def _validate_image_urls(urls: list[str]) -> list[str]:
    for url in urls:
        if not url.startswith(_ALLOWED_IMAGE_PREFIXES):
            raise ValueError("image_urls acepta solo URLs http(s) o data:image/")
    return urls


class ItemImageRead(BaseModel):
    id: int
    image_url: str

    model_config = {"from_attributes": True}


class ItemCreate(BaseModel):
    title: str = Field(min_length=3, max_length=140)
    description: str = Field(min_length=10)
    condition: str = Field(min_length=2, max_length=80)
    category_id: int
    image_urls: list[str] = Field(default=[], max_length=8)

    @field_validator("image_urls")
    @classmethod
    def check_image_urls(cls, value: list[str]) -> list[str]:
        return _validate_image_urls(value)


class ItemUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=3, max_length=140)
    description: str | None = Field(default=None, min_length=10)
    condition: str | None = Field(default=None, min_length=2, max_length=80)
    category_id: int | None = None
    status: ItemStatus | None = None
    image_urls: list[str] | None = Field(default=None, max_length=8)

    @field_validator("image_urls")
    @classmethod
    def check_image_urls(cls, value: list[str] | None) -> list[str] | None:
        return value if value is None else _validate_image_urls(value)


class ItemRead(BaseModel):
    id: int
    title: str
    description: str
    condition: str
    status: ItemStatus
    created_at: datetime
    category: CategoryRead
    owner: UserRead
    images: list[ItemImageRead]

    model_config = {"from_attributes": True}
