"""Message router: classify incoming messages and route to the right handler."""

from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import ContextTypes

from bot import config
from bot.handlers import chat_handler, memory_handler, skill_creator
from bot.llm import client as llm_client
from bot.llm.schemas import Intent

logger = logging.getLogger(__name__)


def is_authorized(user_id: int) -> bool:
    """Check if a user is in the allowed list."""
    if not config.ALLOWED_USER_IDS:
        return True  # No whitelist = allow all (for initial setup)
    return user_id in config.ALLOWED_USER_IDS


async def route_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int | None:
    """Main entry point for all non-command text messages.

    Classifies the message intent via LLM and routes accordingly.
    Returns ConversationHandler state if entering skill creation flow.
    """
    if not update.message or not update.message.text:
        return None

    user_id = update.effective_user.id
    if not is_authorized(user_id):
        await update.message.reply_text("Sorry, I only respond to my owner. 🔒")
        return None

    message = update.message.text.strip()
    if not message:
        return None

    logger.info("Message from %d: %s", user_id, message[:100])

    try:
        # Classify intent
        result = await llm_client.classify(message)
        logger.info(
            "Classified as %s (%.0f%% confidence): %s",
            result.intent.value,
            result.confidence * 100,
            result.reasoning,
        )

        if result.intent == Intent.CREATE_SKILL:
            return await skill_creator.start_creation(update, context, message)

        elif result.intent == Intent.UPDATE_MEMORY:
            await memory_handler.handle_memory_update(update, context, message)
            return None

        else:  # Intent.CHAT
            await chat_handler.handle_chat(update, context, message)
            return None

    except Exception as e:
        logger.error("Error routing message: %s", e)
        await update.message.reply_text(
            "Oops, something went wrong processing that. Try again?"
        )
        return None
