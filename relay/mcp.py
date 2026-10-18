"""Offline MCP adapter: validates names/arguments, executes approved local tools only."""

from __future__ import annotations

from shared.schemas import ToolCall, ToolError, ToolResult
from relay.tools import directory as dirtools
from relay.tools import storage as storetools

SCHEMAS: dict[str, dict[str, type]] = {
    "storage.list_objects": {"bucket": str},
    "storage.read_object": {"bucket": str, "key": str},
    "storage.plan_upload": {"bucket": str, "key": str, "content": str},
    "storage.plan_delete": {"bucket": str, "key": str},
    "directory.lookup_user": {"username": str},
}


class MCPValidationError(ValueError):
    pass


def _validate(name: str, arguments: dict) -> None:
    if name not in SCHEMAS:
        raise MCPValidationError(f"unknown MCP tool {name!r}")
    schema = SCHEMAS[name]
    if set(arguments) != set(schema):
        raise MCPValidationError(f"invalid arguments for {name}: expected {sorted(schema)}")
    for key, kind in schema.items():
        if not isinstance(arguments[key], kind) or not arguments[key]:
            raise MCPValidationError(f"invalid argument {key!r} for {name}")


def invoke(world_db: str, call: ToolCall) -> ToolResult:
    """Validate then execute a local tool. Never contacts a remote MCP server."""
    _validate(call.name, call.arguments)
    args = call.arguments
    try:
        # Domain validation (e.g. bucket grammar) runs here so invalid values
        # surface as typed tool errors, while structural problems raise above.
        if call.name.startswith("storage."):
            storetools.parse_bucket(args["bucket"])
        if call.name == "storage.list_objects":
            value = storetools.list_objects(world_db, args["bucket"])
        elif call.name == "storage.read_object":
            value = storetools.read_object(world_db, args["bucket"], args["key"])
        elif call.name == "storage.plan_upload":
            value = storetools.plan_upload(args["bucket"], args["key"], args["content"]).model_dump(mode="json")
        elif call.name == "storage.plan_delete":
            value = storetools.plan_delete(args["bucket"], args["key"]).model_dump(mode="json")
        elif call.name == "directory.lookup_user":
            value = dirtools.lookup_user(world_db, args["username"])
        else:  # pragma: no cover - schema gate above forbids this
            raise MCPValidationError(f"unapproved MCP tool {call.name}")
        return ToolResult(call=call, value=value, error=None)
    except Exception as exc:  # noqa: BLE001 - typed error surface
        code = getattr(exc, "code", type(exc).__name__)
        return ToolResult(call=call, value=None, error=ToolError(code=code, message=str(exc)))