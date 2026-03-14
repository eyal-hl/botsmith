"""Skill registry: CRUD for skill JSON files."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

from bot import config
from bot.core import git_sync
from bot.llm.schemas import SkillDefinition

logger = logging.getLogger(__name__)

# In-memory index of all loaded skills
_skills: dict[str, SkillDefinition] = {}


def _skill_path(skill_id: str) -> Path:
    return config.SKILLS_DIR / f"{skill_id}.json"


def load_all_skills() -> dict[str, SkillDefinition]:
    """Load all skills from the skills/ directory. Called once at startup."""
    global _skills
    _skills.clear()

    for path in config.SKILLS_DIR.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            skill = SkillDefinition.from_file(data)
            _skills[skill.id] = skill
            logger.info("Loaded skill: %s (%s)", skill.name, skill.id)
        except Exception as e:
            logger.error("Failed to load skill %s: %s", path.name, e)

    logger.info("Loaded %d skills total", len(_skills))
    return _skills


def get_skill(skill_id: str) -> SkillDefinition | None:
    return _skills.get(skill_id)


def get_all_skills() -> dict[str, SkillDefinition]:
    return _skills.copy()


async def save_skill(skill: SkillDefinition) -> None:
    """Save a skill to file and git."""
    path = _skill_path(skill.id)
    path.write_text(
        json.dumps(skill.to_file_dict(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    _skills[skill.id] = skill

    # Append to changelog
    _append_changelog(f"Created skill: {skill.name} ({skill.id})")

    # Git sync
    rel_path = str(path.relative_to(config.BASE_DIR))
    changelog_rel = str(config.CHANGELOG_FILE.relative_to(config.BASE_DIR))
    await git_sync.commit_multiple_and_push(
        [rel_path, changelog_rel],
        f"Add skill: {skill.name} ({skill.id})",
    )
    logger.info("Saved skill: %s", skill.id)


async def update_skill(skill: SkillDefinition) -> None:
    """Update an existing skill."""
    path = _skill_path(skill.id)
    path.write_text(
        json.dumps(skill.to_file_dict(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    _skills[skill.id] = skill

    _append_changelog(f"Updated skill: {skill.name} ({skill.id})")

    rel_path = str(path.relative_to(config.BASE_DIR))
    changelog_rel = str(config.CHANGELOG_FILE.relative_to(config.BASE_DIR))
    await git_sync.commit_multiple_and_push(
        [rel_path, changelog_rel],
        f"Update skill: {skill.name} ({skill.id})",
    )
    logger.info("Updated skill: %s", skill.id)


async def delete_skill(skill_id: str) -> bool:
    """Delete a skill file and remove from registry."""
    path = _skill_path(skill_id)
    skill = _skills.pop(skill_id, None)
    if not skill:
        return False

    if path.exists():
        path.unlink()

    name = skill.name
    _append_changelog(f"Deleted skill: {name} ({skill_id})")

    # Git: stage deletion + changelog
    rel_path = str(path.relative_to(config.BASE_DIR))
    changelog_rel = str(config.CHANGELOG_FILE.relative_to(config.BASE_DIR))
    # For deletions we need git rm
    await git_sync._run_git("rm", "--cached", "--ignore-unmatch", rel_path)
    await git_sync.commit_multiple_and_push(
        [changelog_rel],
        f"Delete skill: {name} ({skill_id})",
    )
    logger.info("Deleted skill: %s", skill_id)
    return True


async def toggle_skill(skill_id: str, enabled: bool) -> bool:
    """Enable or disable a skill."""
    skill = _skills.get(skill_id)
    if not skill:
        return False

    skill.enabled = enabled
    path = _skill_path(skill_id)
    path.write_text(
        json.dumps(skill.to_file_dict(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    action = "Enabled" if enabled else "Disabled"
    _append_changelog(f"{action} skill: {skill.name} ({skill_id})")

    rel_path = str(path.relative_to(config.BASE_DIR))
    changelog_rel = str(config.CHANGELOG_FILE.relative_to(config.BASE_DIR))
    await git_sync.commit_multiple_and_push(
        [rel_path, changelog_rel],
        f"{action} skill: {skill.name} ({skill_id})",
    )
    return True


def _append_changelog(entry: str) -> None:
    """Append a timestamped entry to changelog.md."""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"- [{ts}] {entry}\n"

    if not config.CHANGELOG_FILE.exists():
        config.CHANGELOG_FILE.write_text(
            "# Changelog\n\n" + line, encoding="utf-8"
        )
    else:
        with open(config.CHANGELOG_FILE, "a", encoding="utf-8") as f:
            f.write(line)
