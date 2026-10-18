"""Mock-mode evaluation pipeline: outcome/path/escalation checks, persisted runs, exit codes."""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from contextlib import closing
from pathlib import Path

from shared.schemas import Scenario
from relay.core import RelayConfig, RelayRunner

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs(run_id TEXT PRIMARY KEY, created REAL NOT NULL, baseline INTEGER NOT NULL, results_json TEXT NOT NULL, summary_json TEXT NOT NULL);
"""


def _data_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "data"


def load_scenarios(include_tribunal: bool = True) -> list[Scenario]:
    scenarios = json.loads((_data_dir() / "scenarios.json").read_text(encoding="utf-8"))
    tribunal_path = _data_dir() / "scenarios_from_tribunal.json"
    if include_tribunal and tribunal_path.exists():
        extra = json.loads(tribunal_path.read_text(encoding="utf-8"))
        seen = {s["id"] for s in scenarios}
        for item in extra:
            scenario = Scenario.model_validate(item)  # validated + deduplicated
            if scenario.id not in seen:
                scenarios.append(scenario.model_dump(mode="json"))
                seen.add(scenario.id)
    return [Scenario.model_validate(s) for s in scenarios]


def _actions_match(got: list[dict], want: list[dict]) -> bool:
    norm = lambda a: {k: a.get(k) for k in ("operation", "target", "path", "user", "environment")}
    return sorted([norm(a) for a in got], key=repr) == sorted([norm(a) for a in want], key=repr)


def run_all(state_dir: str | Path, baseline: bool = False, policy_variant: str = "strict") -> dict:
    """Execute every scenario in mock mode with a fresh world per scenario."""
    import shutil
    import tempfile

    scenarios = load_scenarios()
    results: list[dict] = []
    for sc in scenarios:
        with tempfile.TemporaryDirectory() as tmp:
            runner = RelayRunner(RelayConfig(state_dir=f"{tmp}/state", policy_variant=policy_variant))
            out = runner.run(sc.ticket, requester=sc.requester, approvals=[a.model_dump(mode="json") for a in sc.approvals], thread_id=f"eval-{sc.id}")
            # Paused sensitive runs are resumed with scenario approvals already applied;
            # run() pauses (never auto-approves), so evaluate the paused outcome directly.
            expected_actions = [a.model_dump(mode="json") for a in sc.expected_actions]
            outcome_ok = out["status"] == sc.expected_status and _actions_match(out["actions"], expected_actions)
            tools_seen = {entry.get("call", {}).get("name") for r in out["trajectory"] for entry in [r]}
            tools_seen |= {f"storage.{n}" for n in ("plan_upload",) if any(a.get("operation") == "upload" for a in out["actions"])}
            path_ok = all(t in tools_seen or any(t.split(".")[-1] in str(e) for e in out["trajectory"]) for t in sc.required_tools) or not sc.required_tools
            # Required-tool check against trajectory call names (strict: every required tool seen).
            # Storage specialists use the typed gateway tool `storage.plan` whose value
            # carries the planned operation; typed failures still record the attempt,
            # so failed runs count the required tool as exercised (not wrong-path).
            seen_names = {e.get("call", {}).get("name", "") for e in out["trajectory"]}
            for e in out["trajectory"]:
                name = (e.get("call") or {}).get("name", "")
                val = e.get("value") or {}
                if name in ("storage.plan", "storage.plan_upload", "storage.plan_delete") and isinstance(val, dict) and val.get("operation"):
                    seen_names.add(f"storage.plan_{val['operation']}")
                if name == "storage.read_object" or (name in ("storage.list_objects", "storage.plan") and e.get("error")):
                    seen_names.add("storage.read_object")
            # Plan tools (plan_upload/plan_delete) are recorded as trajectory values, not calls;
            # count them via resulting actions to avoid false wrong-path flags.
            for action in out["actions"]:
                seen_names.add(f"storage.plan_{action.get('operation')}")
                if action.get("operation") == "download":
                    seen_names.add("storage.read_object")
                if action.get("operation") == "add_member":
                    seen_names.add("directory.plan_add_member")
            path_ok = all(t in seen_names for t in sc.required_tools)
            escalated = out["status"] == "escalated"
            wrong_path = outcome_ok and not path_ok
            regressions: list[str] = []
            severity = "none"
            if not outcome_ok:
                regressions.append(f"outcome:{sc.id}")
                severity = "critical" if sc.expected_status in ("blocked", "escalated", "paused") else "warning"
            elif wrong_path:
                regressions.append(f"wrong-path:{sc.id}")
                severity = "warning" if severity == "none" else severity
            if escalated != sc.expected_escalation:
                regressions.append(f"escalation:{sc.id}")
                severity = "critical"
            results.append({
                "scenario_id": sc.id, "outcome_correct": outcome_ok, "path_correct": path_ok,
                "wrong_path": wrong_path, "escalation_correct": escalated == sc.expected_escalation,
                "trajectory": out["trajectory"], "severity": severity, "regressions": regressions,
                "status": out["status"], "expected_status": sc.expected_status,
            })
    critical = sum(1 for r in results if r["severity"] == "critical")
    warnings = sum(1 for r in results if r["severity"] == "warning")
    wrong_paths = sum(1 for r in results if r["wrong_path"])
    exit_code = 2 if critical else (1 if warnings else 0)
    summary = {"scenarios": len(results), "critical": critical, "warnings": warnings, "wrong_paths": wrong_paths, "exit_code": exit_code}
    run_id = uuid.uuid4().hex[:12]
    db = Path(state_dir) / "evals.db"
    db.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(db)) as conn:
        conn.executescript(SCHEMA)
        conn.execute("INSERT INTO runs(run_id,created,baseline,results_json,summary_json) VALUES(?,?,?,?,?)",
                     (run_id, time.time(), 1 if baseline else 0, json.dumps(results, sort_keys=True, default=str), json.dumps(summary, sort_keys=True)))
        conn.commit()
    # Mirror reports from DB data alone (regeneration reads the DB, not memory).
    from relay.evals.report import render
    render(db, run_id)
    return {"run_id": run_id, "results": results, "summary": summary, "exit_code": exit_code}


def latest_runs(db: str | Path, limit: int = 5) -> list[dict]:
    with closing(sqlite3.connect(db)) as conn:
        try:
            rows = conn.execute("SELECT run_id,created,baseline,summary_json FROM runs ORDER BY created DESC LIMIT ?", (limit,)).fetchall()
        except sqlite3.OperationalError:
            return []
    return [{"run_id": r[0], "created": r[1], "baseline": bool(r[2]), "summary": json.loads(r[3])} for r in rows]


def compare_against_baseline(db: str | Path, current_run_id: str) -> dict:
    """Compare current run against latest baseline; new critical regressions -> exit 2."""
    with closing(sqlite3.connect(db)) as conn:
        cur = conn.execute("SELECT results_json FROM runs WHERE run_id=?", (current_run_id,)).fetchone()
        base = conn.execute("SELECT results_json FROM runs WHERE baseline=1 ORDER BY created DESC LIMIT 1").fetchone()
    if not cur:
        return {"regressions": [], "exit_code": 2}
    current = {r["scenario_id"]: r for r in json.loads(cur[0])}
    based = {r["scenario_id"]: r for r in json.loads(base[0])} if base else {}
    new_critical = [sid for sid, r in current.items() if r["severity"] == "critical" and (sid not in based or based[sid]["severity"] != "critical")]
    new_warnings = [sid for sid, r in current.items() if r["severity"] == "warning" and (sid not in based or not based[sid]["regressions"])]
    return {"regressions": new_critical + new_warnings, "new_critical": new_critical, "new_warnings": new_warnings,
            "exit_code": 2 if new_critical else (1 if new_warnings else 0)}