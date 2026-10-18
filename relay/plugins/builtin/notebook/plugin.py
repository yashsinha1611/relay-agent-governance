"""Notebook plugin: safe local note helper for registry/scope tests. No network, no code execution."""

from __future__ import annotations

from relay.plugins.registry import Plugin

OPERATIONS = ("notebook.summarize",)


def summarize(text: str) -> str:
    words = (text or "").split()
    return " ".join(words[:24])


def build_plugin() -> Plugin:
    return Plugin(name="notebook", tools={"notebook.summarize": summarize}, allowed_operations=set(OPERATIONS))