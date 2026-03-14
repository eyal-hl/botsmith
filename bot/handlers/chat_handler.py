"""Chat handler: one-off LLM responses for general conversation."""

from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import ContextTypes

from bot.handlers.memory_handler import read_memory
from bot.llm import client as llm_client

logger = logging.getLogger(__name__)


HISTORY_LIMIT = 10  # max messages to keep (user + assistant pairs)


async def handle_chat(
    update: Update, context: ContextTypes.DEFAULT_TYPE, message: str
) -> None:
    """Handle a general chat message with conversation history and web search."""
    try:
        memory = read_memory()

        # Load conversation history from user_data
        history: list[dict] = context.user_data.get("chat_history", [])

        response = await llm_client.chat(message, memory, history)

        # Update history
        history.append({"role": "user", "content": message})
        history.append({"role": "assistant", "content": response})
        # Keep only the last HISTORY_LIMIT messages
        context.user_data["chat_history"] = history[-HISTORY_LIMIT:]

        # Telegram has a 4096 char limit per message
        if len(response) > 4000:
            chunks = [response[i : i + 4000] for i in range(0, len(response), 4000)]
            for chunk in chunks:
                await update.message.reply_text(chunk)
        else:
            await update.message.reply_text(response)

    except Exception as e:
        logger.error("Chat handler error: %s", e)
        await update.message.reply_text(
            "Sorry, I'm having trouble right now. Try again in a moment."
        )
