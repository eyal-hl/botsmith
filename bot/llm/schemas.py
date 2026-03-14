"""Pydantic models for structured LLM output and skill definitions."""

from __future__ import annotations
from datetime import datetime
from enum import Enum
from typing import Any, Literal
from pydantic import BaseModel, Field


class Intent(str, Enum):
    CREATE_SKILL = "create_skill"
    UPDATE_MEMORY = "update_memory"
    CHAT = "chat"


class ClassificationResult(BaseModel):
    intent: Intent
    confidence: float = Field(ge=0, le=1)
    reasoning: str = Field(description="Brief explanation of why this intent was chosen")


class DataSource(BaseModel):
    id: str = Field(description="Short identifier used in template, e.g. 'weather'")
    type: Literal["http"] = "http"
    url: str
    method: Literal["GET", "POST"] = "GET"
    params: dict[str, Any] = Field(default_factory=dict)
    headers: dict[str, str] = Field(default_factory=dict)
    body: dict[str, Any] | None = None
    timeout: int = 15


class CronTrigger(BaseModel):
    type: Literal["cron"] = "cron"
    cron: str = Field(description="Cron expression, e.g. '0 7 * * 0-4'")
    timezone: str = "Asia/Jerusalem"


class CommandTrigger(BaseModel):
    type: Literal["command"] = "command"
    command: str = Field(description="Command name without /, e.g. 'manchester'")


Trigger = CronTrigger | CommandTrigger


class SkillDefinition(BaseModel):
    id: str = Field(description="Snake_case unique identifier")
    name: str = Field(description="Human-readable name")
    description: str = Field(description="What this skill does, one sentence")
    trigger: Trigger
    data_sources: list[DataSource] = Field(default_factory=list)
    message_template: str = Field(description="Jinja2 template for the message")
    parse_mode: Literal["Markdown", "HTML", ""] = "Markdown"
    enabled: bool = True
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())

    def to_file_dict(self) -> dict:
        """Serialize for JSON file storage."""
        return self.model_dump(mode="json")

    @classmethod
    def from_file(cls, data: dict) -> "SkillDefinition":
        return cls.model_validate(data)


class MemoryUpdateResult(BaseModel):
    updated_content: str = Field(description="The full updated memory.md content")
    summary: str = Field(description="Brief summary of what changed")


class SkillGenerationResult(BaseModel):
    skill: SkillDefinition
    explanation: str = Field(description="Brief explanation of what was created and how it works")
