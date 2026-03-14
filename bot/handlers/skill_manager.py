"""Skill management commands: /skills, /enable, /disable, /delete, /run."""

from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import ContextTypes

from bot.core import skill_executor, skill_registry, skill_scheduler
from bot.handlers.message_router import is_authorized
from bot.llm.schemas import CommandTrigger, CronTrigger

logger = logging.getLogger(__name__)


async def cmd_skills(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """List all skills with their status."""
    if not is_authorized(update.effective_user.id):
        return

    skills = skill_registry.get_all_skills()
    if not skills:
        await update.message.reply_text(
            "No skills yet! Send me a message like:\n"
            '"Send me weather every morning at 7am"'
        )
        return

    lines = ["📋 *Your Skills*\n"]
    for skill in skills.values():
        status = "✅" if skill.enabled else "⏸"
        trigger = ""
        if isinstance(skill.trigger, CronTrigger):
            trigger = f"⏰ `{skill.trigger.cron}`"
        elif isinstance(skill.trigger, CommandTrigger):
            trigger = f"/{skill.trigger.command}"

        lines.append(f"{status} *{skill.name}* (`{skill.id}`)\n   {trigger}")

    lines.append(
        "\n_Commands: /enable, /disable, /delete, /run followed by skill ID_"
    )
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def cmd_enable(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Enable a skill: /enable <skill_id>."""
    if not is_authorized(update.effective_user.id):
        return

    args = context.args
    if not args:
        await update.message.reply_text("Usage: /enable <skill\\_id>")
        return

    skill_id = args[0]
    success = await skill_registry.toggle_skill(skill_id, enabled=True)
    if success:
        skill = skill_registry.get_skill(skill_id)
        if skill:
            skill_scheduler.register_skill(skill)
        await update.message.reply_text(f"✅ Enabled: {skill_id}")
    else:
        await update.message.reply_text(f"Skill not found: {skill_id}")


async def cmd_disable(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Disable a skill: /disable <skill_id>."""
    if not is_authorized(update.effective_user.id):
        return

    args = context.args
    if not args:
        await update.message.reply_text("Usage: /disable <skill\\_id>")
        return

    skill_id = args[0]
    success = await skill_registry.toggle_skill(skill_id, enabled=False)
    if success:
        skill_scheduler.unregister_skill(skill_id)
        await update.message.reply_text(f"⏸ Disabled: {skill_id}")
    else:
        await update.message.reply_text(f"Skill not found: {skill_id}")


async def cmd_delete(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Delete a skill: /delete <skill_id>."""
    if not is_authorized(update.effective_user.id):
        return

    args = context.args
    if not args:
        await update.message.reply_text("Usage: /delete <skill\\_id>")
        return

    skill_id = args[0]
    skill = skill_registry.get_skill(skill_id)
    if not skill:
        await update.message.reply_text(f"Skill not found: {skill_id}")
        return

    skill_scheduler.unregister_skill(skill_id)
    success = await skill_registry.delete_skill(skill_id)
    if success:
        await update.message.reply_text(f"🗑 Deleted: {skill.name} ({skill_id})")
    else:
        await update.message.reply_text(f"Failed to delete: {skill_id}")


async def cmd_run(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Manually trigger a skill: /run <skill_id>."""
    if not is_authorized(update.effective_user.id):
        return

    args = context.args
    if not args:
        await update.message.reply_text("Usage: /run <skill\\_id>")
        return

    skill_id = args[0]
    skill = skill_registry.get_skill(skill_id)
    if not skill:
        await update.message.reply_text(f"Skill not found: {skill_id}")
        return

    await update.message.reply_text(f"▶️ Running *{skill.name}*...", parse_mode="Markdown")

    async def send(text, parse_mode=None):
        await update.message.reply_text(text, parse_mode=parse_mode)

    success = await skill_executor.execute_skill(skill, send)
    if not success:
        await update.message.reply_text("⚠️ Skill execution failed. Check logs.")
