"""Memory handler: update memory.md from user instructions."""

from __future__ import annotations

import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from bot import config
from bot.core import git_sync
from bot.llm import client as llm_client

logger = logging.getLogger(__name__)


def read_memory() -> str:
    """Read current memory.md content."""
    if config.MEMORY_FILE.exists():
        return config.MEMORY_FILE.read_text(encoding="utf-8")
    return "## Preferences\n\n## Facts about me\n\n## Bot behavior\n"


def write_memory(content: str) -> None:
    """Write memory.md content."""
    config.MEMORY_FILE.write_text(content, encoding="utf-8")


async def handle_memory_update(
    update: Update, context: ContextTypes.DEFAULT_TYPE, message: str
) -> None:
    """Process a memory update request."""
    await update.message.reply_text("🧠 Updating my memory...")

    try:
        current = read_memory()
        result = await llm_client.update_memory(current, message)

        # Store pending update
        context.user_data["pending_memory"] = result.updated_content
        context.user_data["memory_summary"] = result.summary

        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("✅ Save", callback_data="memory_confirm"),
                    InlineKeyboardButton("❌ Cancel", callback_data="memory_cancel"),
                ]
            ]
        )
        await update.message.reply_text(
            f"📝 *Memory update:*\n\n{result.summary}\n\n_Save this?_",
            reply_markup=keyboard,
            parse_mode="Markdown",
        )

    except Exception as e:
        logger.error("Memory update failed: %s", e)
        await update.message.reply_text(
            f"Failed to process memory update: {str(e)[:200]}"
        )


async def handle_memory_confirm(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """User confirmed memory update."""
    query = update.callback_query
    await query.answer()

    content = context.user_data.pop("pending_memory", None)
    summary = context.user_data.pop("memory_summary", "Updated memory")
    if not content:
        await query.edit_message_text("No pending memory update.")
        return

    write_memory(content)

    # Git sync
    rel_path = str(config.MEMORY_FILE.relative_to(config.BASE_DIR))
    await git_sync.commit_and_push(rel_path, f"Update memory: {summary}")

    await query.edit_message_text(f"✅ Memory updated: {summary}")
    logger.info("Memory updated: %s", summary)


async def handle_memory_cancel(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """User cancelled memory update."""
    query = update.callback_query
    await query.answer()
    context.user_data.pop("pending_memory", None)
    context.user_data.pop("memory_summary", None)
    await query.edit_message_text("❌ Memory update cancelled.")
