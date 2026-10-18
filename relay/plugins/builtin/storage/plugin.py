"""Storage plugin: exposes relay.tools.storage through the scoped registry."""

from __future__ import annotations

from relay.plugins.registry import Plugin
from relay.tools import storage as storetools

OPERATIONS = ("storage.list_objects", "storage.read_object", "storage.plan_upload", "storage.plan_delete")


def build_plugin(world_db: str | None = None) -> Plugin:
    db = world_db
    return Plugin(
        name="storage",
        tools={
            "storage.list_objects": (lambda bucket: storetools.list_objects(db, bucket)) if db else storetools.list_objects,
            "storage.read_object": (lambda bucket, key: storetools.read_object(db, bucket, key)) if db else storetools.read_object,
            "storage.plan_upload": storetools.plan_upload,
            "storage.plan_delete": storetools.plan_delete,
        },
        allowed_operations=set(OPERATIONS),
    )