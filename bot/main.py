"""Pi Helper Bot — main entry point."""

from __future__ import annotations

import logging
import signal
import sys

from telegram import Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from bot import config
from bot.core import cache, data_fetcher, skill_registry, skill_scheduler
from bot.core.plugin_loader import load_all_plugins
from bot.handlers import memory_handler, message_router, skill_manager
from bot.handlers.skill_creator import build_conversation_handler

# Logging setup
logging.basicConfig(
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    level=logging.INFO,
)
# Quiet noisy libraries
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("apscheduler").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)


async def cmd_start(update: Update, context) -> None:
    """Handle /start command."""
    if not message_router.is_authorized(update.effective_user.id):
        await update.message.reply_text("Sorry, I only respond to my owner. 🔒")
        return

    skills_count = len(skill_registry.get_all_skills())
    await update.message.reply_text(
        "👋 *Pi Helper Bot*\n\n"
        f"I have {skills_count} skill{'s' if skills_count != 1 else ''} loaded.\n\n"
        "Just talk to me in natural language to:\n"
        "• Create scheduled messages or commands\n"
        "• Update my memory about your preferences\n"
        "• Ask me anything\n\n"
        "*Commands:*\n"
        "/skills — List all skills\n"
        "/run <id> — Test a skill\n"
        "/enable <id> — Enable a skill\n"
        "/disable <id> — Disable a skill\n"
        "/delete <id> — Delete a skill\n"
        "/newskill — Create a skill step by step\n"
        "/memory — Show current memory\n"
        "/cancel — Cancel current operation",
        parse_mode="Markdown",
    )


async def cmd_help(update: Update, context) -> None:
    """Handle /help command — same as /start."""
    await cmd_start(update, context)


async def cmd_memory(update: Update, context) -> None:
    """Show current memory.md contents."""
    if not message_router.is_authorized(update.effective_user.id):
        return

    content = memory_handler.read_memory()
    if not content.strip() or content.strip() == "## Preferences\n\n## Facts about me\n\n## Bot behavior":
        await update.message.reply_text(
            "🧠 Memory is empty.\n\n"
            'Tell me things like "I live in Tel Aviv" or '
            '"prefer Celsius" and I\'ll remember them.'
        )
    else:
        # Truncate if too long
        if len(content) > 3500:
            content = content[:3500] + "\n\n... (truncated)"
        await update.message.reply_text(f"🧠 *My Memory*\n\n{content}", parse_mode="Markdown")


async def post_init(app: Application) -> None:
    """Called after the application is initialized."""
    logger.info("Bot starting up...")

    # Load skills from files
    skill_registry.load_all_skills()

    # Load plugins
    load_all_plugins()

    # We need the chat_id to send scheduled messages.
    # Use the first allowed user ID as the default recipient.
    chat_id = next(iter(config.ALLOWED_USER_IDS), None)
    if chat_id:
        skill_scheduler.init(app, chat_id)
        skill_scheduler.register_all_skills()
        logger.info("Scheduled skills registered for chat_id: %d", chat_id)
    else:
        logger.warning(
            "No ALLOWED_USER_IDS set — scheduled skills won't send messages. "
            "Set ALLOWED_USER_IDS in .env to your Telegram user ID."
        )

    # Initialize cache DB
    await cache.get_db()

    # Periodic cache cleanup (every 6 hours)
    if app.job_queue:
        app.job_queue.run_repeating(
            _cleanup_cache, interval=21600, first=60, name="cache_cleanup"
        )

    logger.info("Bot ready!")


async def _cleanup_cache(context) -> None:
    await cache.cleanup()


async def post_shutdown(app: Application) -> None:
    """Cleanup on shutdown."""
    logger.info("Bot shutting down...")
    await data_fetcher.close()
    await cache.close()


def main() -> None:
    """Build and run the bot."""
    logger.info("=== Pi Helper Bot ===")
    logger.info("Skills dir: %s", config.SKILLS_DIR)
    logger.info("Plugins dir: %s", config.PLUGINS_DIR)
    logger.info("Memory file: %s", config.MEMORY_FILE)
    logger.info("Allowed users: %s", config.ALLOWED_USER_IDS or "ALL (no whitelist)")

    # Build application
    app = (
        Application.builder()
        .token(config.TELEGRAM_TOKEN)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

    # Conversation handler for skill creation (must be added first for priority)
    conv_handler = build_conversation_handler()
    app.add_handler(conv_handler)

    # Command handlers
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("skills", skill_manager.cmd_skills))
    app.add_handler(CommandHandler("enable", skill_manager.cmd_enable))
    app.add_handler(CommandHandler("disable", skill_manager.cmd_disable))
    app.add_handler(CommandHandler("delete", skill_manager.cmd_delete))
    app.add_handler(CommandHandler("run", skill_manager.cmd_run))
    app.add_handler(CommandHandler("memory", cmd_memory))

    # Memory confirmation callbacks
    app.add_handler(
        CallbackQueryHandler(memory_handler.handle_memory_confirm, pattern="^memory_confirm$")
    )
    app.add_handler(
        CallbackQueryHandler(memory_handler.handle_memory_cancel, pattern="^memory_cancel$")
    )

    # Catch-all: route all other text messages through the LLM classifier
    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            _handle_text_message,
        )
    )

    # Start polling
    logger.info("Starting polling...")
    app.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,
    )


async def _handle_text_message(update: Update, context) -> None:
    """Route non-command text messages.

    This wraps the message router to handle the case where it returns
    a ConversationHandler state (for skill creation initiated via
    natural language rather than /newskill).
    """
    result = await message_router.route_message(update, context)
    # If the router started a skill creation flow, the ConversationHandler
    # will pick it up from here since we store state in user_data.


if __name__ == "__main__":
    main()
