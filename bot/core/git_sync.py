"""Git sync: auto-commit and push after every state change."""

from __future__ import annotations

import asyncio
import logging

from bot import config

logger = logging.getLogger(__name__)

_push_lock = asyncio.Lock()
_pending_push = False


async def _run_git(*args: str) -> tuple[int, str, str]:
    """Run a git command in the project root."""
    proc = await asyncio.create_subprocess_exec(
        "git",
        *args,
        cwd=str(config.BASE_DIR),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    return (
        proc.returncode or 0,
        stdout.decode().strip(),
        stderr.decode().strip(),
    )


async def commit_and_push(filepath: str, message: str) -> bool:
    """Stage a file, commit, and push. Non-blocking on push failure."""
    global _pending_push
    try:
        # Stage the file
        rc, _, err = await _run_git("add", filepath)
        if rc != 0:
            logger.error("git add failed: %s", err)
            return False

        # Commit
        rc, _, err = await _run_git("commit", "-m", message)
        if rc != 0:
            # Might be "nothing to commit" which is fine
            if "nothing to commit" in err or "nothing to commit" in _:
                logger.info("Nothing to commit for: %s", message)
                return True
            logger.error("git commit failed: %s", err)
            return False

        logger.info("Committed: %s", message)

        # Push (non-blocking, debounced)
        if config.GIT_AUTO_PUSH:
            _pending_push = True
            asyncio.create_task(_debounced_push())

        return True

    except Exception as e:
        logger.error("Git sync error: %s", e)
        return False


async def commit_multiple_and_push(files: list[str], message: str) -> bool:
    """Stage multiple files, commit once, and push."""
    global _pending_push
    try:
        for f in files:
            rc, _, err = await _run_git("add", f)
            if rc != 0:
                logger.error("git add failed for %s: %s", f, err)

        rc, _, err = await _run_git("commit", "-m", message)
        if rc != 0 and "nothing to commit" not in err:
            logger.error("git commit failed: %s", err)
            return False

        logger.info("Committed: %s", message)

        if config.GIT_AUTO_PUSH:
            _pending_push = True
            asyncio.create_task(_debounced_push())

        return True

    except Exception as e:
        logger.error("Git sync error: %s", e)
        return False


async def _debounced_push() -> None:
    """Wait 5 seconds then push (batches rapid changes)."""
    global _pending_push
    await asyncio.sleep(5)

    async with _push_lock:
        if not _pending_push:
            return
        _pending_push = False

        rc, _, err = await _run_git("push", "origin", config.GIT_BRANCH)
        if rc != 0:
            logger.warning("git push failed (will retry on next commit): %s", err)
        else:
            logger.info("Pushed to %s", config.GIT_BRANCH)
