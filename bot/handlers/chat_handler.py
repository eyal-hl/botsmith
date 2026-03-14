"""Chat handler: one-off LLM responses for general conversation."""

from __future__ import annotations

import asyncio
import logging

from telegram import Update
from telegram.ext import ContextTypes

from bot.handlers.memory_handler import read_memory
from bot.llm import client as llm_client

logger = logging.getLogger(__name__)

HISTORY_LIMIT = 10  # max messages to keep (user + assistant pairs)
CHAT_TIMEOUT = 45   # seconds before giving up


async def handle_chat(
    update: Update, context: ContextTypes.DEFAULT_TYPE, message: str
) -> None:
    """Handle a general chat message with conversation history and web search."""
    try:
        memory = read_memory()
        history: list[dict] = context.user_data.get("chat_history", [])

        # Show indicator so user knows bot received the message
        await update.message.reply_text("🔍 Searching...")
        logger.info("Chat request: %s", message[:100])

        try:
            response = await asyncio.wait_for(
                llm_client.chat(message, memory, history),
                timeout=CHAT_TIMEOUT,
            )
            logger.info("Chat response received (%d chars)", len(response))
        except asyncio.TimeoutError:
            logger.warning("Chat timed out after %ds for: %s", CHAT_TIMEOUT, message[:100])
            await update.message.reply_text(
                "⏱ Search timed out. Try asking something more specific."
            )
            return

        # Update history
        history.append({"role": "user", "content": message})
        history.append({"role": "assistant", "content": response})
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
