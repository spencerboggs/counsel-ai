"""Cancel flags for long discovery runs.

Stop sets an in-memory flag AND the API marks the run cancelled in SQLite.
Hard asyncio.Task.cancel() is avoided during DB writes; the pipeline exits
cooperatively when it sees the flag or a cancelled DB status.
"""

from __future__ import annotations

import asyncio
from typing import Any

_cancelled: set[str] = set()
_tasks: dict[str, asyncio.Task[Any]] = {}


def register_run_task(run_id: str, task: asyncio.Task[Any]) -> None:
    """Track the background task so orphaned 'running' rows can be detected."""
    _tasks[run_id] = task

    def _cleanup(_task: asyncio.Task[Any]) -> None:
        _tasks.pop(run_id, None)

    task.add_done_callback(_cleanup)


def is_run_task_alive(run_id: str) -> bool:
    task = _tasks.get(run_id)
    return task is not None and not task.done()


def request_cancel(run_id: str) -> bool:
    """Mark the run cancelled in memory. Returns True if a live task exists."""
    _cancelled.add(run_id)
    return is_run_task_alive(run_id)


def clear_cancel(run_id: str) -> None:
    _cancelled.discard(run_id)


def is_cancelled(run_id: str) -> bool:
    return run_id in _cancelled


async def wait_or_cancel(
    run_id: str,
    awaitable: Any,
    *,
    poll_seconds: float = 0.15,
) -> Any:
    """Await work but bail as soon as Stop is requested."""
    task = asyncio.ensure_future(awaitable)
    try:
        while True:
            if is_cancelled(run_id):
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass
                raise asyncio.CancelledError()
            done, _ = await asyncio.wait({task}, timeout=poll_seconds)
            if done:
                return task.result()
    except asyncio.CancelledError:
        if not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        raise
