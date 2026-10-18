"""HTML/Markdown reports regenerated from evals.db alone."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path


def load_run(db: str | Path, run_id: str) -> dict:
    with closing(sqlite3.connect(db)) as conn:
        row = conn.execute("SELECT results_json,summary_json,created,baseline FROM runs WHERE run_id=?", (run_id,)).fetchone()
    if row is None:
        raise KeyError(f"unknown run {run_id}")
    return {"run_id": run_id, "results": json.loads(row[0]), "summary": json.loads(row[1]), "created": row[2], "baseline": bool(row[3])}


def render(db: str | Path, run_id: str, out_dir: str | Path | None = None) -> dict:
    run = load_run(db, run_id)
    out = Path(out_dir or Path(db).parent / "reports")
    out.mkdir(parents=True, exist_ok=True)
    rows = "\n".join(
        f"<tr><td>{r['scenario_id']}</td><td>{r['status']}</td><td>{r['expected_status']}</td>"
        f"<td>{r['severity']}</td><td>{','.join(r['regressions'])}</td><td>{len(r['trajectory'])}</td></tr>"
        for r in run["results"]
    )
    html = f"<html><body><h1>Relay eval {run_id}</h1><p>{json.dumps(run['summary'])}</p><table>{rows}</table></body></html>"
    md = f"# Relay eval {run_id}\n\n{json.dumps(run['summary'], indent=2)}\n\n" + "\n".join(
        f"- {r['scenario_id']}: {r['status']} vs {r['expected_status']} ({r['severity']})" for r in run["results"]
    )
    (out / f"{run_id}.html").write_text(html, encoding="utf-8")
    (out / f"{run_id}.md").write_text(md, encoding="utf-8")
    return {"html": str(out / f"{run_id}.html"), "md": str(out / f"{run_id}.md")}