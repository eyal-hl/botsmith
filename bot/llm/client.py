"""Claude API wrapper with structured output, retry, and fallback."""

from __future__ import annotations

import json
import logging
from typing import TypeVar

import anthropic
from pydantic import BaseModel

from bot import config
from bot.llm import prompts
from bot.llm.schemas import (
    ClassificationResult,
    MemoryUpdateResult,
    SkillGenerationResult,
)

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

_client: anthropic.AsyncAnthropic | None = None


def get_client() -> anthropic.AsyncAnthropic:
    global _client
    if _client is None:
        _client = anthropic.AsyncAnthropic(api_key=config.CLAUDE_API_KEY)
    return _client


async def _call_llm(
    system: str,
    user_message: str,
    model: str,
    response_model: type[T],
    max_retries: int = 3,
) -> T:
    """Call Claude API and parse into a Pydantic model."""
    client = get_client()

    schema_description = json.dumps(
        response_model.model_json_schema(), indent=2
    )
    full_system = (
        f"{system}\n\n"
        f"You MUST respond with ONLY valid JSON matching this schema:\n"
        f"```json\n{schema_description}\n```\n"
        f"No markdown fences, no explanation outside the JSON."
    )

    last_error: Exception | None = None
    for attempt in range(max_retries):
        try:
            response = await client.messages.create(
                model=model,
                max_tokens=4096,
                system=full_system,
                messages=[{"role": "user", "content": user_message}],
            )

            text = response.content[0].text.strip()
            # Strip markdown fences if the model includes them
            if text.startswith("```"):
                text = text.split("\n", 1)[1]
                if text.endswith("```"):
                    text = text[:-3].strip()

            data = json.loads(text)
            return response_model.model_validate(data)

        except json.JSONDecodeError as e:
            last_error = e
            logger.warning(
                "LLM returned invalid JSON (attempt %d/%d): %s",
                attempt + 1,
                max_retries,
                str(e)[:200],
            )
        except anthropic.APIError as e:
            last_error = e
            logger.warning(
                "Claude API error (attempt %d/%d): %s",
                attempt + 1,
                max_retries,
                str(e)[:200],
            )
        except Exception as e:
            last_error = e
            logger.error(
                "Unexpected error in LLM call (attempt %d/%d): %s",
                attempt + 1,
                max_retries,
                str(e),
            )

    raise RuntimeError(
        f"LLM call failed after {max_retries} attempts: {last_error}"
    )


async def classify(message: str) -> ClassificationResult:
    """Classify a user message into an intent."""
    return await _call_llm(
        system=prompts.CLASSIFICATION_PROMPT,
        user_message=message,
        model=config.CLAUDE_CLASSIFICATION_MODEL,
        response_model=ClassificationResult,
    )


async def generate_skill(
    description: str, memory: str
) -> SkillGenerationResult:
    """Generate a skill definition from natural language."""
    context = f"User's memory/preferences:\n{memory}\n\nUser's request:\n{description}"
    return await _call_llm(
        system=prompts.make_skill_generation_prompt(),
        user_message=context,
        model=config.CLAUDE_GENERATION_MODEL,
        response_model=SkillGenerationResult,
    )


async def update_memory(
    current_memory: str, instruction: str
) -> MemoryUpdateResult:
    """Generate an updated memory.md from the user's instruction."""
    return await _call_llm(
        system=prompts.make_memory_update_prompt(current_memory),
        user_message=instruction,
        model=config.CLAUDE_GENERATION_MODEL,
        response_model=MemoryUpdateResult,
    )


async def chat(message: str, memory: str, history: list[dict] | None = None) -> str:
    """Chat response with web search and optional conversation history."""
    client = get_client()
    messages = [*(history or []), {"role": "user", "content": message}]
    system = prompts.make_chat_prompt(memory)
    tools = [{"type": "web_search_20250305", "name": "web_search"}]

    try:
        # Server-side tool loop: handle pause_turn up to 5 continuations
        for _ in range(5):
            response = await client.messages.create(
                model=config.CLAUDE_GENERATION_MODEL,
                max_tokens=2048,
                system=system,
                messages=messages,
                tools=tools,
            )

            if response.stop_reason == "end_turn":
                text = next((b.text for b in response.content if b.type == "text"), "")
                return text

            if response.stop_reason == "pause_turn":
                # Server loop hit its limit — re-send to continue
                messages = [
                    {"role": "user", "content": message},
                    {"role": "assistant", "content": response.content},
                ]
                continue

            # Unexpected stop reason
            text = next((b.text for b in response.content if b.type == "text"), "")
            return text

        return "Sorry, the response took too long. Try again?"

    except Exception as e:
        logger.error("Chat LLM call failed: %s", e)
        return "Sorry, I'm having trouble connecting to my brain right now. Try again in a moment."
