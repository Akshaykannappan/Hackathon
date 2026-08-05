"""Request bodies for admin product CRUD."""

from pydantic import BaseModel, Field, field_validator

LEVEL_BEGINNER = "beginner"
LEVEL_INTERMEDIATE = "intermediate"
LEVEL_ADVANCED = "advanced"
LEVELS = (LEVEL_BEGINNER, LEVEL_INTERMEDIATE, LEVEL_ADVANCED)


class ProductBase(BaseModel):
    """Fields shared by create and update.

    `description` carries real weight later: it is half of the text that gets
    embedded for retrieval, so a blank-ish one is rejected here rather than
    quietly producing a useless vector in Phase 3.
    """

    title: str = Field(min_length=3, max_length=255)
    description: str = Field(min_length=20)
    category: str = Field(min_length=2, max_length=100)
    level: str
    price: float = Field(ge=0.0)

    @field_validator("title", "category")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return value.strip()

    @field_validator("description")
    @classmethod
    def strip_description(cls, value: str) -> str:
        return value.strip()

    @field_validator("level")
    @classmethod
    def check_level(cls, value: str) -> str:
        value = value.strip().lower()
        if value not in LEVELS:
            raise ValueError(f"Level must be one of: {', '.join(LEVELS)}.")
        return value


class ProductCreate(ProductBase):
    """A new catalog product."""


class ProductUpdate(ProductBase):
    """A full replacement of an existing product — the edit form posts every field."""
