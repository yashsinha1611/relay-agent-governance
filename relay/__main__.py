"""Relay CLI: demo/run/resume/eval/stats/trace via RelayRunner and persisted services."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from shared.llm.provider import ModelConfig
from relay.core import RelayConfig, RelayRunner


def _parse_kv(items: list[str] | None) -> dict:
    out: dict = {}
    for item in items or []:
        key, _, value = item.partition("=")
        out[key.strip()] = value.strip()
    return out


def _approvals(args) -> list[dict]:
    approvals = [{"approver": name.strip(), "role": "approver", "approved": True} for name in (args.approve or []) if name.strip()]
    if args.approver:
        # --approver always carries the data-owner role (needed for prod resume,
        # where no --ticket is present). --approve carries the plain approver role.
        approvals.append({"approver": args.approver, "role": "data_owner", "approved": True})
    return approvals


def _runner(args) -> RelayRunner:
    return RelayRunner(RelayConfig(state_dir=args.state_dir, policy_variant=args.policy_variant, model_config=ModelConfig()))


def cmd_demo(args) -> int:
    runner = _runner(args)
    out = runner.run(args.ticket or "upload report.csv to acme-dev-raw content hello", requester=args.requester, approvals=_approvals(args), thread_id=args.thread_id or "demo")
    print(json.dumps(out, indent=2, sort_keys=True, default=str))
    return 0


def cmd_run(args) -> int:
    runner = _runner(args)
    out = runner.run(args.ticket or "", requester=args.requester, approvals=_approvals(args), thread_id=args.thread_id or "cli-run")
    print(json.dumps(out, indent=2, sort_keys=True, default=str))
    return 0


def cmd_resume(args) -> int:
    runner = _runner(args)
    out = runner.resume(args.thread_id, _approvals(args))
    print(json.dumps(out, indent=2, sort_keys=True, default=str))
    return 0


def cmd_eval(args) -> int:
    from relay.evals.pipeline import compare_against_baseline, run_all

    result = run_all(args.state_dir, baseline=args.baseline, policy_variant=args.policy_variant)
    if not args.baseline:
        cmp = compare_against_baseline(Path(args.state_dir) / "evals.db", result["run_id"])
        result["baseline_comparison"] = cmp
        code = cmp["exit_code"]
    else:
        code = result["summary"]["exit_code"]
    print(json.dumps({"run_id": result["run_id"], "summary": result["summary"], "exit_code": code}, indent=2, sort_keys=True, default=str))
    return code


def cmd_stats(args) -> int:
    from relay.obs.tracing import list_traces

    traces = list_traces(Path(args.state_dir) / "traces.db", args.thread_id or None)
    print(json.dumps({"state_dir": args.state_dir, "traces": len(traces), "items": traces[:50]}, indent=2, sort_keys=True, default=str))
    return 0


def cmd_trace(args) -> int:
    from relay.obs.tracing import get_trace, list_traces

    db = Path(args.state_dir) / "traces.db"
    trace = get_trace(db, args.thread_id)
    if trace is None:
        # Accept a thread ID by resolving to its latest trace.
        items = list_traces(db, args.thread_id)
        if items:
            trace = get_trace(db, items[-1]["trace_id"])
    if trace is None:
        print(json.dumps({"error": f"unknown trace {args.thread_id}"}), file=sys.stderr)
        return 1
    print(json.dumps(trace, indent=2, sort_keys=True, default=str))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="relay")
    parser.add_argument("--state-dir", default="relay/state")
    parser.add_argument("--policy-variant", default="strict")
    subs = parser.add_subparsers(dest="command", required=True)
    for name in ("demo", "run", "resume"):
        sub = subs.add_parser(name)
        sub.add_argument("--ticket", default="")
        sub.add_argument("--requester", default="requester")
        sub.add_argument("--approver", default="")
        sub.add_argument("--approve", action="append", default=[])
        sub.add_argument("--thread-id", default="")
        sub.set_defaults(func={"demo": cmd_demo, "run": cmd_run, "resume": cmd_resume}[name])
    ev = subs.add_parser("eval")
    ev.add_argument("--baseline", action="store_true")
    ev.set_defaults(func=cmd_eval)
    st = subs.add_parser("stats")
    st.add_argument("--thread-id", default="")
    st.set_defaults(func=cmd_stats)
    tr = subs.add_parser("trace")
    tr.add_argument("--thread-id", required=True)
    tr.set_defaults(func=cmd_trace)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())