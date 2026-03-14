"""Skill scheduler: register/unregister APScheduler jobs via PTB's JobQueue."""

from __future__ import annotations

import logging
from zoneinfo import ZoneInfo

from telegram.ext import Application, CommandHandler, ContextTypes

from bot.core import skill_executor
from bot.core.skill_registry import delete_skill, get_all_skills, get_skill
from bot.llm.schemas import CommandTrigger, CronTrigger, OnceTrigger, SkillDefinition

logger = logging.getLogger(__name__)

_app: Application | None = None
_chat_id: int | None = None
_registered_commands: set[str] = set()


def init(app: Application, chat_id: int) -> None:
    """Store the application and default chat ID."""
    global _app, _chat_id
    _app = app
    _chat_id = chat_id


async def _send_message(text: str, parse_mode: str | None) -> None:
    """Send a message to the default chat."""
    if _app and _chat_id:
        try:
            await _app.bot.send_message(
                chat_id=_chat_id,
                text=text,
                parse_mode=parse_mode,
            )
        except Exception as e:
            # Fallback: try without parse_mode if Markdown fails
            if parse_mode:
                try:
                    await _app.bot.send_message(
                        chat_id=_chat_id,
                        text=text,
                        parse_mode=None,
                    )
                except Exception:
                    logger.error("Failed to send message: %s", e)
            else:
                logger.error("Failed to send message: %s", e)


async def _cron_callback(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Callback fired by APScheduler for cron-triggered skills."""
    skill_id = context.job.name
    skill = get_skill(skill_id)
    if not skill or not skill.enabled:
        return
    await skill_executor.execute_skill(skill, _send_message)


async def _command_callback(
    update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Callback fired by a Telegram /<command> for command-triggered skills."""
    command = update.message.text.lstrip("/").split()[0].split("@")[0]
    # Find skill by command name
    for skill in get_all_skills().values():
        if (
            isinstance(skill.trigger, CommandTrigger)
            and skill.trigger.command == command
            and skill.enabled
        ):

            async def send(text, parse_mode=None):
                await update.message.reply_text(text, parse_mode=parse_mode)

            await skill_executor.execute_skill(skill, send)
            return

    await update.message.reply_text(f"No active skill found for /{command}")


def register_skill(skill: SkillDefinition) -> None:
    """Register a skill's trigger with the scheduler."""
    if not _app:
        logger.error("Scheduler not initialized")
        return

    if not skill.enabled:
        return

    trigger = skill.trigger
    job_queue = _app.job_queue

    if isinstance(trigger, CronTrigger):
        # Parse cron: minute hour day month weekday
        parts = trigger.cron.split()
        if len(parts) != 5:
            logger.error("Invalid cron for %s: %s", skill.id, trigger.cron)
            return

        minute, hour, day, month, dow = parts
        tz = ZoneInfo(trigger.timezone)

        # Remove existing job if any
        _remove_job(skill.id)

        # PTB's job_queue doesn't have native cron support,
        # so we use run_custom with APScheduler's CronTrigger directly
        from apscheduler.triggers.cron import CronTrigger as APSCronTrigger

        aps_trigger = APSCronTrigger(
            minute=minute,
            hour=hour,
            day=day,
            month=month,
            day_of_week=dow,
            timezone=tz,
        )

        job_queue.scheduler.add_job(
            _run_cron_job,
            trigger=aps_trigger,
            id=skill.id,
            name=skill.id,
            args=[skill.id],
            replace_existing=True,
        )
        logger.info(
            "Registered cron skill: %s (%s)", skill.id, trigger.cron
        )

    elif isinstance(trigger, OnceTrigger):
        from apscheduler.triggers.date import DateTrigger as APSDateTrigger
        from datetime import datetime as dt
        from zoneinfo import ZoneInfo

        tz = ZoneInfo(trigger.timezone)
        run_at = trigger.run_at
        if run_at.tzinfo is None:
            run_at = run_at.replace(tzinfo=tz)

        _remove_job(skill.id)
        job_queue.scheduler.add_job(
            _run_once_job,
            trigger=APSDateTrigger(run_date=run_at),
            id=skill.id,
            name=skill.id,
            args=[skill.id],
            replace_existing=True,
        )
        logger.info("Registered one-time skill: %s at %s", skill.id, run_at)

    elif isinstance(trigger, CommandTrigger):
        cmd = trigger.command
        if cmd not in _registered_commands:
            _app.add_handler(CommandHandler(cmd, _command_callback))
            _registered_commands.add(cmd)
            logger.info("Registered command skill: /%s → %s", cmd, skill.id)
        else:
            logger.info("Command /%s already registered, skill updated", cmd)


async def _run_cron_job(skill_id: str) -> None:
    """Wrapper to run a cron-triggered skill (called by APScheduler)."""
    skill = get_skill(skill_id)
    if not skill or not skill.enabled:
        return
    await skill_executor.execute_skill(skill, _send_message)


async def _run_once_job(skill_id: str) -> None:
    """Wrapper to run a one-time skill then delete it."""
    skill = get_skill(skill_id)
    if not skill or not skill.enabled:
        return
    await skill_executor.execute_skill(skill, _send_message)
    await delete_skill(skill_id)
    logger.info("One-time skill %s fired and deleted", skill_id)


def _remove_job(skill_id: str) -> None:
    """Remove a scheduled job by skill ID."""
    if _app and _app.job_queue:
        try:
            _app.job_queue.scheduler.remove_job(skill_id)
        except Exception:
            pass  # Job might not exist


def unregister_skill(skill_id: str) -> None:
    """Unregister a skill's trigger."""
    _remove_job(skill_id)
    logger.info("Unregistered skill: %s", skill_id)


def register_all_skills() -> None:
    """Register all enabled skills. Called at startup."""
    for skill in get_all_skills().values():
        if skill.enabled:
            register_skill(skill)
