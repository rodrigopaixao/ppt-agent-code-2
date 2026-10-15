from enum import Enum
from typing import List, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


class LayoutName(str, Enum):
    TITLE = "title"
    SECTION = "section"
    TITLE_CONTENT = "title_content"
    TWO_COLUMN = "two_column"
    BLANK = "blank"


class ContentBlock(BaseModel):
    kind: Literal["bullets", "paragraph", "quote", "stat"] = "bullets"
    heading: Optional[str] = Field(default=None, max_length=100)
    text: Optional[str] = Field(default=None, max_length=700)
    items: List[str] = Field(default_factory=list, max_length=8)

    @field_validator("items")
    @classmethod
    def validate_items(cls, items: List[str]) -> List[str]:
        cleaned = [item.strip() for item in items if item.strip()]
        if any(len(item) > 240 for item in cleaned):
            raise ValueError("Bullet items must be 240 characters or fewer.")
        return cleaned

    @model_validator(mode="after")
    def require_content(self) -> "ContentBlock":
        if not self.text and not self.items:
            raise ValueError("A content block needs text or at least one item.")
        return self


class SlideSpec(BaseModel):
    layout: LayoutName
    title: str = Field(min_length=1, max_length=140)
    subtitle: Optional[str] = Field(default=None, max_length=260)
    blocks: List[ContentBlock] = Field(default_factory=list, max_length=4)
    speaker_notes: Optional[str] = Field(default=None, max_length=2000)
    sources: List[str] = Field(default_factory=list, max_length=12)

    @model_validator(mode="after")
    def enforce_density(self) -> "SlideSpec":
        item_count = sum(len(block.items) for block in self.blocks)
        content_chars = sum(len(block.text or "") for block in self.blocks)
        content_chars += sum(len(item) for block in self.blocks for item in block.items)
        if item_count > 10 or content_chars > 1500:
            raise ValueError("Slide content is too dense; split it across slides.")
        return self


class PresentationSpec(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    subtitle: Optional[str] = Field(default=None, max_length=260)
    slides: List[SlideSpec] = Field(min_length=1, max_length=30)


class RevisionRequest(BaseModel):
    instruction: str = Field(min_length=3, max_length=4000)
