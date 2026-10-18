"""Validated JSON contracts shared by Relay and Tribunal, without runtime I/O."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


Operation = Literal["upload", "download", "delete", "add_member"]
Status = Literal["completed", "paused", "blocked", "failed", "escalated"]


class Approval(StrictModel):
    approver: str = Field(min_length=1)
    role: Literal["approver", "data_owner"] = "approver"
    approved: bool = True


class Action(StrictModel):
    operation: Operation
    target: str = Field(min_length=1)
    path: str = ""
    content: str = ""
    user: str = ""
    environment: Literal["dev", "test", "staging", "prod"] = "dev"


class Subtask(StrictModel):
    id: str = Field(min_length=1)
    specialist: Literal["storage", "directory"]
    action: Action
    depends_on: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def specialist_matches(self):
        expected = "directory" if self.action.operation == "add_member" else "storage"
        if self.specialist != expected:
            raise ValueError("specialist does not match operation")
        return self


class Plan(StrictModel):
    subtasks: list[Subtask] = Field(default_factory=list)

    @model_validator(mode="after")
    def dependency_dag(self):
        ids = [task.id for task in self.subtasks]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate subtask IDs")
        pending = {task.id: set(task.depends_on) for task in self.subtasks}
        if any(not deps <= set(ids) for deps in pending.values()):
            raise ValueError("unknown prerequisite")
        complete: set[str] = set()
        while pending:
            ready = [key for key, deps in pending.items() if deps <= complete]
            if not ready:
                raise ValueError("cyclic prerequisites")
            for key in ready:
                complete.add(key)
                del pending[key]
        return self


class ToolCall(StrictModel):
    name: str = Field(pattern=r"^[a-z][a-z0-9_.]*$")
    arguments: dict[str, Any]


class ToolError(StrictModel):
    code: str
    message: str


class ToolResult(StrictModel):
    call: ToolCall
    value: Any = None
    error: ToolError | None = None


class SpecialistResult(StrictModel):
    task_id: str
    success: bool
    action: Action | None = None
    trajectory: list[ToolResult] = Field(default_factory=list)
    started: float
    ended: float


class Issue(StrictModel):
    severity: Literal["low", "medium", "high", "critical"]
    problem: str = Field(min_length=1)
    quote: str = ""


class Critique(StrictModel):
    critic: str
    score: int = Field(ge=1, le=5)
    issues: list[Issue] = Field(default_factory=list)


class EvaluationItem(StrictModel):
    id: str
    task: str
    output: str
    reference: str | None = None
    required_facts: list[str] = Field(default_factory=list)
    prohibited_phrases: list[str] = Field(default_factory=list)
    trajectory: list[dict[str, Any]] = Field(default_factory=list)
    required_tools: list[str] = Field(default_factory=list)


class Verdict(StrictModel):
    item_id: str
    critiques: list[Critique]
    disagreement: bool
    verdict: Literal["pass", "fail", "review"]
    confidence: float = Field(ge=0, le=1)
    confirmed_issues: list[Issue]
    dismissed_flags: list[str] = Field(default_factory=list)
    summary: str
    provider_mode: str = "mock"


class Scenario(StrictModel):
    id: str
    ticket: str
    requester: str = "requester"
    approvals: list[Approval] = Field(default_factory=list)
    expected_plan: Plan
    required_tools: list[str]
    expected_escalation: bool
    expected_status: Status
    expected_actions: list[Action]
    tags: list[str]


class EvaluationResult(StrictModel):
    scenario_id: str
    outcome_correct: bool
    path_correct: bool
    wrong_path: bool
    escalation_correct: bool
    trajectory: list[dict[str, Any]]
    severity: Literal["none", "warning", "critical"]
    regressions: list[str] = Field(default_factory=list)