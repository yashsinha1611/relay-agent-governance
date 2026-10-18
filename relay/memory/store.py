"""SQLite episode store with a deterministic TF-IDF retrieval index."""

from __future__ import annotations

import json
import math
import re
import sqlite3
from collections import Counter
from contextlib import closing
from pathlib import Path

TOKEN_RE = re.compile(r"[a-z0-9]+")

SCHEMA = """
CREATE TABLE IF NOT EXISTS episodes(id INTEGER PRIMARY KEY AUTOINCREMENT, ticket TEXT NOT NULL, plan_json TEXT NOT NULL, outcome TEXT NOT NULL, summary TEXT NOT NULL, requester TEXT NOT NULL, metadata_json TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT (datetime('now')));
CREATE TABLE IF NOT EXISTS terms(term TEXT NOT NULL, episode_id INTEGER NOT NULL, tf INTEGER NOT NULL, PRIMARY KEY(term, episode_id));
"""


def tokenize(text: str) -> list[str]:
    return TOKEN_RE.findall((text or "").lower())


def init_memory(path: str | Path) -> Path:
    db = Path(path)
    db.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(db)) as conn:
        conn.executescript(SCHEMA)
        conn.commit()
    return db


def persist_episode(db: str | Path, ticket: str, plan: dict, outcome: str, summary: str, requester: str, metadata: dict | None = None) -> int:
    """Persist an episode and update the term index in the same transaction."""
    db = init_memory(db)
    text = " ".join([ticket, summary, json.dumps(plan, sort_keys=True), outcome])
    counts = Counter(tokenize(text))
    with closing(sqlite3.connect(db)) as conn:
        cursor = conn.execute(
            "INSERT INTO episodes(ticket,plan_json,outcome,summary,requester,metadata_json) VALUES(?,?,?,?,?,?)",
            (ticket, json.dumps(plan, sort_keys=True), outcome, summary, requester, json.dumps(metadata or {}, sort_keys=True)),
        )
        episode_id = int(cursor.lastrowid)
        conn.executemany(
            "INSERT OR REPLACE INTO terms(term,episode_id,tf) VALUES(?,?,?)",
            [(term, episode_id, tf) for term, tf in counts.items()],
        )
        conn.commit()
    return episode_id


def retrieve(db: str | Path, query: str, limit: int = 3) -> list[dict]:
    """TF-IDF cosine-ish ranking. Empty DB returns []. No network."""
    db_path = Path(db)
    if not db_path.exists():
        return []
    with closing(sqlite3.connect(db_path)) as conn:
        try:
            episodes = conn.execute("SELECT id,ticket,summary,outcome,requester FROM episodes ORDER BY id").fetchall()
            if not episodes:
                return []
            total = conn.execute("SELECT COUNT(*) FROM episodes").fetchone()[0] or 1
            df_rows = conn.execute("SELECT term, COUNT(*) FROM terms GROUP BY term").fetchall()
        except sqlite3.OperationalError:
            return []
    df = {term: count for term, count in df_rows}
    query_counts = Counter(tokenize(query))
    scored: list[tuple[float, tuple]] = []
    for episode_id, ticket, summary, outcome, requester in episodes:
        text = f"{ticket} {summary} {outcome}"
        doc_counts = Counter(tokenize(text))
        score = 0.0
        for term, qtf in query_counts.items():
            if term not in doc_counts:
                continue
            idf = math.log((1 + total) / (1 + df.get(term, 0))) + 1.0
            score += qtf * doc_counts[term] * idf * idf
        # Normalize by document length so short relevant episodes win.
        score /= 1.0 + math.log(1.0 + sum(doc_counts.values()))
        if score > 0:
            scored.append((score, (episode_id, ticket, summary, outcome, requester)))
    scored.sort(key=lambda item: (-item[0], item[1][0]))
    return [
        {"id": eid, "ticket": ticket, "summary": summary, "outcome": outcome, "requester": requester, "score": round(score, 4)}
        for score, (eid, ticket, summary, outcome, requester) in scored[:limit]
    ]