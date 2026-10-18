"""Directory plugin: exposes relay.tools.directory through the scoped registry."""

from __future__ import annotations

from relay.plugins.registry import Plugin
from relay.tools import directory as dirtools

OPERATIONS = ("directory.lookup_user", "directory.plan_add_member")


def build_plugin(world_db: str | None = None) -> Plugin:
    db = world_db
    return Plugin(
        name="directory",
        tools={
            "directory.lookup_user": (lambda username: dirtools.lookup_user(db, username)) if db else dirtools.lookup_user,
            "directory.plan_add_member": dirtools.plan_add_member,
        },
        allowed_operations=set(OPERATIONS),
    )