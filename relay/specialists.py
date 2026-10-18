"""Specialist executors: real typed tools, five-step budget, trajectory recording."""

from __future__ import annotations

import time

from shared.schemas import SpecialistResult, Subtask, ToolCall, ToolError, ToolResult
from relay.tools import directory as dirtools
from relay.tools import storage as storetools

MAX_TOOL_STEPS = 5


def _record(call: ToolCall, value=None, error: Exception | None = None) -> ToolResult:
    if error is None:
        return ToolResult(call=call, value=value, error=None)
    code = getattr(error, "code", type(error).__name__)
    return ToolResult(call=call, value=None, error=ToolError(code=code, message=str(error)))


def run_storage(world_db: str, task: Subtask) -> SpecialistResult:
    started = time.time()
    trajectory: list[ToolResult] = []
    action = task.action
    steps = 0
    try:
        call = ToolCall(name="storage.parse_bucket", arguments={"bucket": action.target})
        parsed = storetools.parse_bucket(action.target)
        trajectory.append(_record(call, parsed)); steps += 1
        call = ToolCall(name="storage.list_objects", arguments={"bucket": action.target})
        trajectory.append(_record(call, storetools.list_objects(world_db, action.target))); steps += 1
        if len(trajectory) < MAX_TOOL_STEPS:
            if action.operation == "download":
                call = ToolCall(name="storage.read_object", arguments={"bucket": action.target, "key": action.path})
                trajectory.append(_record(call, storetools.read_object(world_db, action.target, action.path))); steps += 1
            elif action.operation == "upload":
                call = ToolCall(name="storage.plan_upload", arguments={"bucket": action.target, "key": action.path})
                trajectory.append(_record(call, action.model_dump(mode="json"))); steps += 1
            elif action.operation == "delete":
                call = ToolCall(name="storage.plan_delete", arguments={"bucket": action.target, "key": action.path})
                trajectory.append(_record(call, action.model_dump(mode="json"))); steps += 1
        success = all(r.error is None for r in trajectory)
        return SpecialistResult(task_id=task.id, success=success, action=action if success else None, trajectory=trajectory, started=started, ended=time.time())
    except Exception as exc:  # noqa: BLE001 - typed error recorded below
        trajectory.append(_record(ToolCall(name="storage.plan", arguments={"task": task.id}), error=exc))
        return SpecialistResult(task_id=task.id, success=False, action=None, trajectory=trajectory, started=started, ended=time.time())


def run_directory(world_db: str, task: Subtask) -> SpecialistResult:
    started = time.time()
    trajectory: list[ToolResult] = []
    action = task.action
    try:
        call = ToolCall(name="directory.lookup_user", arguments={"username": action.user})
        try:
            trajectory.append(_record(call, dirtools.lookup_user(world_db, action.user)))
        except Exception as exc:  # noqa: BLE001 - unknown users stop the budget with failure
            trajectory.append(_record(call, error=exc))
            return SpecialistResult(task_id=task.id, success=False, action=None, trajectory=trajectory, started=started, ended=time.time())
        if len(trajectory) < MAX_TOOL_STEPS:
            call = ToolCall(name="directory.plan_add_member", arguments={"username": action.user, "group": action.target})
            trajectory.append(_record(call, action.model_dump(mode="json")))
        success = all(r.error is None for r in trajectory)
        return SpecialistResult(task_id=task.id, success=success, action=action if success else None, trajectory=trajectory, started=started, ended=time.time())
    except Exception as exc:  # noqa: BLE001
        trajectory.append(_record(ToolCall(name="directory.plan", arguments={"task": task.id}), error=exc))
        return SpecialistResult(task_id=task.id, success=False, action=None, trajectory=trajectory, started=started, ended=time.time())


def run_task(world_db: str, task: Subtask) -> SpecialistResult:
    if task.specialist == "directory":
        return run_directory(world_db, task)
    return run_storage(world_db, task)