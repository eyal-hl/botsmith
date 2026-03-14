"""Chat handler: one-off LLM responses for general conversation."""

from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import ContextTypes

from bot.handlers.memory_handler import read_memory
from bot.llm import client as llm_client

logger = logging.getLogger(__name__)


async def handle_chat(
    update: Update, context: ContextTypes.DEFAULT_TYPE, message: str
) -> None:
    """Handle a general chat message with a one-off LLM response."""
    try:
        memory = read_memory()
        response = await llm_client.chat(message, memory)

        # Telegram has a 4096 char limit per message
        if len(response) > 4000:
            # Split into chunks
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
