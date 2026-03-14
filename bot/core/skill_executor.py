"""Skill executor: fetch data → render Jinja2 template → send Telegram message."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from jinja2 import BaseLoader, Environment, sandbox

from bot import config
from bot.core import cache, data_fetcher
from bot.core.skill_registry import get_skill, toggle_skill
from bot.llm.schemas import SkillDefinition

logger = logging.getLogger(__name__)

# WMO Weather interpretation codes → emoji + description
WMO_CODES: dict[int, str] = {
    0: "☀️ Clear sky",
    1: "🌤 Mainly clear",
    2: "⛅ Partly cloudy",
    3: "☁️ Overcast",
    45: "🌫 Foggy",
    48: "🌫 Rime fog",
    51: "🌦 Light drizzle",
    53: "🌦 Moderate drizzle",
    55: "🌧 Dense drizzle",
    56: "🌧 Freezing drizzle",
    57: "🌧 Heavy freezing drizzle",
    61: "🌧 Slight rain",
    63: "🌧 Moderate rain",
    65: "🌧 Heavy rain",
    66: "🌧 Freezing rain",
    67: "🌧 Heavy freezing rain",
    71: "🌨 Slight snow",
    73: "🌨 Moderate snow",
    75: "🌨 Heavy snow",
    77: "🌨 Snow grains",
    80: "🌦 Slight showers",
    81: "🌧 Moderate showers",
    82: "🌧 Violent showers",
    85: "🌨 Slight snow showers",
    86: "🌨 Heavy snow showers",
    95: "⛈ Thunderstorm",
    96: "⛈ Thunderstorm + hail",
    99: "⛈ Thunderstorm + heavy hail",
}


def _weather_description(code: int | str) -> str:
    """Convert WMO weather code to emoji + description."""
    return WMO_CODES.get(int(code), f"🌡 Code {code}")


def _format_date(dt: datetime | str, fmt: str = "%A, %b %d") -> str:
    if isinstance(dt, str):
        dt = datetime.fromisoformat(dt)
    return dt.strftime(fmt)


def _round_num(value: float | int, decimals: int = 1) -> str:
    return str(round(float(value), decimals))


def _from_timestamp(ts: int | float) -> datetime:
    return datetime.fromtimestamp(float(ts), tz=ZoneInfo(config.TIMEZONE))


def _relative_time(dt: datetime | str) -> str:
    if isinstance(dt, str):
        dt = datetime.fromisoformat(dt)
    now = datetime.now(tz=ZoneInfo(config.TIMEZONE))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo(config.TIMEZONE))
    diff = dt - now
    seconds = diff.total_seconds()
    if abs(seconds) < 60:
        return "just now"
    minutes = abs(seconds) / 60
    if minutes < 60:
        label = f"{int(minutes)} minute{'s' if int(minutes) != 1 else ''}"
    elif minutes < 1440:
        hours = int(minutes / 60)
        label = f"{hours} hour{'s' if hours != 1 else ''}"
    else:
        days = int(minutes / 1440)
        label = f"{days} day{'s' if days != 1 else ''}"
    return f"in {label}" if seconds > 0 else f"{label} ago"


def _build_jinja_env() -> sandbox.SandboxedEnvironment:
    """Create a sandboxed Jinja2 environment with custom filters."""
    env = sandbox.SandboxedEnvironment(
        loader=BaseLoader(),
        autoescape=False,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["weather_description"] = _weather_description
    env.filters["format_date"] = _format_date
    env.filters["round_num"] = _round_num
    env.filters["from_timestamp"] = _from_timestamp
    env.filters["relative_time"] = _relative_time
    env.filters["truncate"] = lambda s, n=100: (
        s[:n] + "…" if len(str(s)) > n else str(s)
    )
    return env


_jinja_env = _build_jinja_env()


async def execute_skill(
    skill: SkillDefinition,
    send_message_fn,  # async callable(text, parse_mode)
) -> bool:
    """Execute a skill: fetch all data sources, render template, send message.

    Returns True on success, False on failure.
    """
    start = time.monotonic()
    skill_id = skill.id

    try:
        # Fetch all data sources concurrently
        context: dict = {
            "now": datetime.now(tz=ZoneInfo(config.TIMEZONE)),
        }

        async def _fetch_source(ds):
            # Resolve {{CONFIG_VAR}} placeholders in headers
            resolved_headers = {
                k: getattr(config, v[2:-2], v) if v.startswith("{{") and v.endswith("}}") else v
                for k, v in ds.headers.items()
            }
            data = await asyncio.wait_for(
                data_fetcher.fetch(
                    url=ds.url,
                    method=ds.method,
                    params=ds.params,
                    headers=resolved_headers,
                    body=ds.body,
                    timeout=ds.timeout,
                ),
                timeout=config.SKILL_EXECUTION_TIMEOUT,
            )
            return ds.id, data

        if skill.data_sources:
            results = await asyncio.gather(
                *[_fetch_source(ds) for ds in skill.data_sources],
                return_exceptions=True,
            )
            for result in results:
                if isinstance(result, Exception):
                    raise result
                source_id, data = result
                context[source_id] = data

        # Render template
        template = _jinja_env.from_string(skill.message_template)
        rendered = template.render(**context)

        # Send message
        parse_mode = skill.parse_mode if skill.parse_mode else None
        await send_message_fn(rendered, parse_mode)

        # Log success
        duration = (time.monotonic() - start) * 1000
        await cache.log_execution(skill_id, True, None, duration)
        logger.info("Skill %s executed in %.0fms", skill_id, duration)
        return True

    except Exception as e:
        duration = (time.monotonic() - start) * 1000
        error_msg = str(e)[:500]
        await cache.log_execution(skill_id, False, error_msg, duration)
        logger.error("Skill %s failed: %s", skill_id, error_msg)

        # Notify user immediately on every failure
        try:
            failures = await cache.get_consecutive_failures(skill_id)
            if failures >= 3:
                await toggle_skill(skill_id, enabled=False)
                await send_message_fn(
                    f"⚠️ Skill *{skill.name}* has been auto-disabled after "
                    f"3 consecutive failures.\n\n"
                    f"Error: `{error_msg[:200]}`\n\n"
                    f"Use /enable {skill_id} to re-enable.",
                    "Markdown",
                )
            else:
                await send_message_fn(
                    f"❌ Skill *{skill.name}* failed.\n\nError: `{error_msg[:200]}`",
                    "Markdown",
                )
        except Exception:
            pass

        return False
