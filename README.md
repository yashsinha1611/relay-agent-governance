# Relay — Offline-First Governed LangGraph Orchestration

A production-oriented, offline-first, governed LangGraph orchestration project.
Defaults to deterministic **mock/offline mode**; no provider SDK or network call
unless `LLM_PROVIDER` is explicitly set to a real provider.

This is a standalone build of the `relay` project (plus its required `shared`
typed-boundary foundation). Tribunal lives in a separate repository.

## Layout

```
relay-project/
  relay/              LangGraph orchestration project
    __main__.py       CLI: demo | run | resume | eval | stats | trace
    core.py           RelayRunner facade + RelayConfig
    graph.py          compiled LangGraph workflow (build_graph / build_resume_graph)
    tools/            typed storage + directory tools backed by world.db
    memory/           SQLite-backed memory store + TF-IDF index
    obs/              SQLite + JSONL tracing
    evals/            evaluation pipeline, persistence, HTML/MD reports
    plugins/          plugin registry + built-in storage/directory/notebook plugins
    skills/           progressive skill disclosure (SKILL.md bodies)
    flows/            sequential, map-reduce, plan-execute-replan, saga
    mcp.py            offline MCP adapter
    replay.py         persisted replay and fork from SQLite checkpoints
    data/             scenarios.json, phase5_flows.json, scenarios_from_tribunal.json
    tests/            acceptance + behavioral tests
    tests.py / test.py direct test entrypoints
  shared/             typed schemas + deterministic LLM provider (required by relay)
    schemas.py        plans, subtasks, tool calls, actions, critiques, scenarios
    llm/provider.py   MockChatModel, LLM_PROVIDER selection, no silent fallback
```

## Environment

Python 3.11+; Pydantic 2, LangGraph 1.2, PyYAML 6. Tests use stdlib `unittest`.

Run from this folder. In PowerShell, ensure offline mode before verification:

```powershell
Remove-Item Env:LLM_PROVIDER -ErrorAction SilentlyContinue
```

`LLM_PROVIDER=mock` also selects offline mode. `LLM_PROVIDER=openai` requires an
explicit model and an `OPENAI_API_KEY`; unknown providers fail without fallback.
Do not commit credentials — see `.env.example`.

## Relay CLI

```powershell
# New run (mock/offline by default)
py -m relay --state-dir ./relay/state run --ticket 'upload report.csv to acme-dev-raw content hello' --requester amy --thread-id demo1

# Pause on production, then resume with data-owner approval
py -m relay --state-dir ./relay/state run --ticket 'upload report.csv to acme-prod-curated content hello' --requester amy --thread-id prod1
py -m relay --state-dir ./relay/state resume --thread-id prod1 --approver dana --approve --role data_owner

# Delete requires two distinct approvers
py -m relay --state-dir ./relay/state run --ticket 'delete notes.txt from acme-dev-raw' --requester amy --thread-id del1
py -m relay --state-dir ./relay/state resume --thread-id del1 --approver amy --approve
py -m relay --state-dir ./relay/state resume --thread-id del1 --approver zed --approve

# Eval (exit 0 = clean, 1 = warning, 2 = critical)
py -m relay --state-dir ./relay/state eval          # current run vs baseline
py -m relay --state-dir ./relay/state eval --baseline  # write a baseline

# Stats / trace / replay
py -m relay --state-dir ./relay/state stats --thread-id demo1
py -m relay --state-dir ./relay/state trace --thread-id demo1
py -m relay --state-dir ./relay/state demo --ticket 'upload report.csv to acme-dev-raw content hello'
```

## Real-provider opt-in (not committed)

Copy `.env.example` to `.env` and fill only the provider you use:

```
LLM_PROVIDER=openai
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o
```

`.env` is gitignored and never committed. With `LLM_PROVIDER` unset, Relay never
makes a network or provider call.

## Tests

```powershell
Remove-Item Env:LLM_PROVIDER -ErrorAction SilentlyContinue
py -m unittest discover -s shared/tests -t .
py -m unittest discover -s relay/tests -t .
# or
py -m relay.tests
```

## Security invariants

- Default provider is mock/offline; no internet/provider calls unless `LLM_PROVIDER` is explicitly a real provider.
- Tool arguments validated before execution; real tool execution against `world.db` (never intent recording).
- NotFound produces failure, never invented success.
- Specialist budget: exactly five tool steps; reviewer rejection cap: exactly two.
- World writes transactional and only after policy approval; blocked/rejected states never modify `world.db`.
- Delete requires two distinct approvers; production requires data-owner approval; requester self-approval escalates.
- Injection text ("skip approval", "bypass approval") is recorded and ignored.
- Resume does not re-execute completed graph nodes; replay/fork load checkpoint history from SQLite.
- No secrets or provider credentials stored.

## Generated artifacts (do not commit)

Databases (`*.db`), traces, reports, caches, and virtual environments are generated
at runtime and excluded by `.gitignore`.
