"""Progressive skill disclosure: names first, bodies only on selection."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

SCHEMA = "CREATE TABLE IF NOT EXISTS skill_metrics(skill TEXT PRIMARY KEY, loads INTEGER NOT NULL, eager INTEGER NOT NULL);"


def skill_dir() -> Path:
    return Path(__file__).resolve().parent


def list_skills() -> list[dict]:
    """Return names + first-line descriptions without reading full bodies."""
    out: list[dict] = []
    for path in sorted(skill_dir().glob("*/SKILL.md")):
        first = path.read_text(encoding="utf-8").splitlines()[0] if path.exists() else ""
        out.append({"name": path.parent.name, "description": first.lstrip("# ").strip(), "path": str(path)})
    return out


def load_skill(name: str, db: str | Path | None = None, eager: bool = False) -> str:
    body = (skill_dir() / name / "SKILL.md").read_text(encoding="utf-8")
    if db is not None:
        record_disclosure(db, name, eager)
    return body


def disclosure_savings(selected: str, all_bodies: dict[str, str]) -> dict:
    selected_len = len(all_bodies[selected])
    total = sum(len(body) for body in all_bodies.values())
    return {"selected_chars": selected_len, "total_chars": total, "saved_chars": total - selected_len,
            "saved_ratio": round((total - selected_len) / total, 4) if total else 0.0}


def record_disclosure(db: str | Path, skill: str, eager: bool) -> None:
    path = Path(db)
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as conn:
        conn.execute(SCHEMA)
        conn.execute("INSERT OR IGNORE INTO skill_metrics(skill,loads,eager) VALUES(?,0,0)", (skill,))
        conn.execute("UPDATE skill_metrics SET loads=loads+1, eager=eager+? WHERE skill=?", (1 if eager else 0, skill))
        conn.commit()