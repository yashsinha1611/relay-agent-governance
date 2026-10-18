"""Plugin discovery, registration, lifecycle, and scope enforcement."""

from __future__ import annotations

import sqlite3
import time
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS violations(plugin TEXT NOT NULL, operation TEXT NOT NULL, created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS metrics(plugin TEXT PRIMARY KEY, calls INTEGER NOT NULL, violations INTEGER NOT NULL);
"""


class PluginScopeViolation(PermissionError):
    pass


@dataclass
class Plugin:
    name: str
    tools: dict[str, object] = field(default_factory=dict)
    allowed_operations: set[str] = field(default_factory=set)


class Registry:
    def __init__(self) -> None:
        self._plugins: dict[str, Plugin] = {}

    def register(self, plugin: Plugin) -> None:
        self._plugins[plugin.name] = plugin

    def remove(self, name: str) -> None:
        del self._plugins[name]

    def list(self) -> list[str]:
        return sorted(self._plugins)

    def tool(self, plugin_name: str, tool_name: str):
        plugin = self._plugins[plugin_name]
        return plugin.tools[tool_name]

    def call(self, db: str | Path | None, plugin_name: str, operation: str, *args, **kwargs):
        plugin = self._plugins[plugin_name]
        if operation not in plugin.allowed_operations or operation not in plugin.tools:
            if db is not None:
                record_violation(db, plugin_name, operation)
            raise PluginScopeViolation(f"{plugin_name} may not perform {operation}")
        fn = plugin.tools[operation]
        assert callable(fn)
        result = fn(*args, **kwargs)
        if db is not None:
            record_call(db, plugin_name)
        return result


def _init(db: str | Path) -> Path:
    path = Path(db)
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as conn:
        conn.executescript(SCHEMA)
        conn.commit()
    return path


def record_violation(db: str | Path, plugin: str, operation: str) -> None:
    path = _init(db)
    with closing(sqlite3.connect(path)) as conn:
        conn.execute("INSERT INTO violations(plugin,operation,created) VALUES(?,?,?)", (plugin, operation, time.time()))
        conn.execute("INSERT OR IGNORE INTO metrics(plugin,calls,violations) VALUES(?,0,0)", (plugin,))
        conn.execute("UPDATE metrics SET violations=violations+1 WHERE plugin=?", (plugin,))
        conn.commit()


def record_call(db: str | Path, plugin: str) -> None:
    path = _init(db)
    with closing(sqlite3.connect(path)) as conn:
        conn.execute("INSERT OR IGNORE INTO metrics(plugin,calls,violations) VALUES(?,0,0)", (plugin,))
        conn.execute("UPDATE metrics SET calls=calls+1 WHERE plugin=?", (plugin,))
        conn.commit()


def metrics(db: str | Path) -> dict:
    path = Path(db)
    if not path.exists():
        return {}
    with closing(sqlite3.connect(path)) as conn:
        try:
            rows = conn.execute("SELECT plugin,calls,violations FROM metrics").fetchall()
        except sqlite3.OperationalError:
            return {}
    return {name: {"calls": calls, "violations": violations} for name, calls, violations in rows}


def build_default_registry() -> Registry:
    from relay.plugins.builtin.directory.plugin import build_plugin as build_directory
    from relay.plugins.builtin.notebook.plugin import build_plugin as build_notebook
    from relay.plugins.builtin.storage.plugin import build_plugin as build_storage

    registry = Registry()
    for plugin in (build_storage(), build_directory(), build_notebook()):
        registry.register(plugin)
    return registry