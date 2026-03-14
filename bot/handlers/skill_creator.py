"""Skill creation handler: natural language → skill definition → confirm → save."""

from __future__ import annotations

import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ConversationHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from bot import config
from bot.core import skill_registry, skill_scheduler
from bot.handlers.message_router import is_authorized
from bot.llm import client as llm_client
from bot.llm.schemas import CronTrigger, CommandTrigger

logger = logging.getLogger(__name__)

# Conversation states
CONFIRMING = 1
EDITING = 2


def _read_memory() -> str:
    if config.MEMORY_FILE.exists():
        return config.MEMORY_FILE.read_text(encoding="utf-8")
    return ""


def _format_skill_preview(skill, explanation: str) -> str:
    """Format a skill definition into a human-readable preview."""
    trigger_desc = ""
    if isinstance(skill.trigger, CronTrigger):
        trigger_desc = f"⏰ Schedule: `{skill.trigger.cron}` ({skill.trigger.timezone})"
    elif isinstance(skill.trigger, CommandTrigger):
        trigger_desc = f"💬 Command: /{skill.trigger.command}"

    sources_desc = ""
    if skill.data_sources:
        sources = [f"  • `{ds.id}`: {ds.url}" for ds in skill.data_sources]
        sources_desc = "\n📡 Data sources:\n" + "\n".join(sources)

    return (
        f"🛠 *New Skill: {skill.name}*\n\n"
        f"📝 {skill.description}\n"
        f"{trigger_desc}\n"
        f"{sources_desc}\n\n"
        f"💡 {explanation}\n\n"
        f"_What do you want to do?_"
    )


async def start_creation(
    update: Update, context: ContextTypes.DEFAULT_TYPE, message: str
) -> int:
    """Begin the skill creation flow. Called by the message router."""
    # Check skill limit
    existing = skill_registry.get_all_skills()
    if len(existing) >= config.MAX_SKILLS:
        await update.message.reply_text(
            f"You've reached the skill limit ({config.MAX_SKILLS}). "
            f"Delete some with /delete before creating new ones."
        )
        return ConversationHandler.END

    await update.message.reply_text("🧠 Let me think about that...")

    try:
        memory = _read_memory()
        result = await llm_client.generate_skill(message, memory)
        skill = result.skill

        # Check for ID collision
        if skill_registry.get_skill(skill.id):
            # Append a number to make it unique
            base_id = skill.id
            i = 2
            while skill_registry.get_skill(f"{base_id}_{i}"):
                i += 1
            skill.id = f"{base_id}_{i}"

        # Store pending skill in user_data
        context.user_data["pending_skill"] = skill
        context.user_data["pending_explanation"] = result.explanation
        context.user_data["original_request"] = message

        preview = _format_skill_preview(skill, result.explanation)
        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("✅ Confirm", callback_data="skill_confirm"),
                    InlineKeyboardButton("✏️ Edit", callback_data="skill_edit"),
                    InlineKeyboardButton("❌ Cancel", callback_data="skill_cancel"),
                ]
            ]
        )
        await update.message.reply_text(
            preview, reply_markup=keyboard, parse_mode="Markdown"
        )
        return CONFIRMING

    except Exception as e:
        logger.error("Skill generation failed: %s", e)
        await update.message.reply_text(
            f"Sorry, I couldn't create that skill. Error: {str(e)[:200]}\n\n"
            "Try rephrasing your request?"
        )
        return ConversationHandler.END


async def handle_confirm(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """User confirmed the skill — save and register it."""
    query = update.callback_query
    await query.answer()

    skill = context.user_data.get("pending_skill")
    if not skill:
        await query.edit_message_text("No pending skill found. Try again.")
        return ConversationHandler.END

    try:
        await skill_registry.save_skill(skill)
        skill_scheduler.register_skill(skill)

        trigger_info = ""
        if isinstance(skill.trigger, CronTrigger):
            trigger_info = f"on schedule `{skill.trigger.cron}`"
        elif isinstance(skill.trigger, CommandTrigger):
            trigger_info = f"via /{skill.trigger.command}"

        await query.edit_message_text(
            f"✅ *Skill created: {skill.name}*\n\n"
            f"It will run {trigger_info}.\n"
            f"Use /skills to manage your skills.",
            parse_mode="Markdown",
        )

    except Exception as e:
        logger.error("Failed to save skill: %s", e)
        await query.edit_message_text(
            f"Failed to save skill: {str(e)[:200]}"
        )

    _clear_pending(context)
    return ConversationHandler.END


async def handle_edit(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """User wants to edit — ask what to change."""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "What would you like to change? Just describe the edit:\n\n"
        "Examples:\n"
        '• "Change the time to 8:30 AM"\n'
        '• "Add wind speed to the message"\n'
        '• "Make it run on weekends too"'
    )
    return EDITING


async def handle_edit_response(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Process the user's edit request and regenerate."""
    if not update.message or not update.message.text:
        return EDITING

    edit_request = update.message.text
    original = context.user_data.get("original_request", "")
    pending = context.user_data.get("pending_skill")

    await update.message.reply_text("🔄 Regenerating with your changes...")

    try:
        memory = _read_memory()
        combined = (
            f"Original request: {original}\n"
            f"Previous attempt: {pending.model_dump_json() if pending else 'none'}\n"
            f"Edit requested: {edit_request}"
        )
        result = await llm_client.generate_skill(combined, memory)
        skill = result.skill

        # Preserve the original ID if editing
        if pending:
            skill.id = pending.id

        context.user_data["pending_skill"] = skill
        context.user_data["pending_explanation"] = result.explanation

        preview = _format_skill_preview(skill, result.explanation)
        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("✅ Confirm", callback_data="skill_confirm"),
                    InlineKeyboardButton("✏️ Edit", callback_data="skill_edit"),
                    InlineKeyboardButton("❌ Cancel", callback_data="skill_cancel"),
                ]
            ]
        )
        await update.message.reply_text(
            preview, reply_markup=keyboard, parse_mode="Markdown"
        )
        return CONFIRMING

    except Exception as e:
        logger.error("Skill re-generation failed: %s", e)
        await update.message.reply_text(f"Failed to regenerate: {str(e)[:200]}")
        return ConversationHandler.END


async def handle_cancel(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """User cancelled skill creation."""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("❌ Skill creation cancelled.")
    _clear_pending(context)
    return ConversationHandler.END


def _clear_pending(context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.pop("pending_skill", None)
    context.user_data.pop("pending_explanation", None)
    context.user_data.pop("original_request", None)


def build_conversation_handler() -> ConversationHandler:
    """Build the ConversationHandler for skill creation flow."""
    return ConversationHandler(
        entry_points=[
            CommandHandler("newskill", _cmd_newskill),
        ],
        states={
            CONFIRMING: [
                CallbackQueryHandler(handle_confirm, pattern="^skill_confirm$"),
                CallbackQueryHandler(handle_edit, pattern="^skill_edit$"),
                CallbackQueryHandler(handle_cancel, pattern="^skill_cancel$"),
            ],
            EDITING: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_edit_response),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", _cmd_cancel),
        ],
        per_user=True,
        per_chat=True,
    )


async def _cmd_newskill(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Handle /newskill command — prompt user for a description."""
    if not is_authorized(update.effective_user.id):
        return ConversationHandler.END

    text = update.message.text.replace("/newskill", "").strip()
    if text:
        return await start_creation(update, context, text)

    await update.message.reply_text(
        "What skill would you like to create? Describe it in natural language.\n\n"
        "Examples:\n"
        '• "Send me weather every morning at 7am"\n'
        '• "Create a /bitcoin command that shows the current price"\n'
        '• "Every Friday remind me to submit timesheets"'
    )
    return EDITING  # Reuse editing state to capture the description


async def _cmd_cancel(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    await update.message.reply_text("Cancelled.")
    _clear_pending(context)
    return ConversationHandler.END
