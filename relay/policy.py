"""Policy gate: approvals decide world writes. Injection text is recorded and ignored."""

from __future__ import annotations

import re

INJECTION_RE = re.compile(r"skip approval|bypass approval|no approval|ignore polic", re.IGNORECASE)


def detect_injection(ticket: str) -> str | None:
    match = INJECTION_RE.search(ticket or "")
    return match.group(0).lower() if match else None


def evaluate(actions: list, approvals: list[dict], requester: str, policy_variant: str = "strict") -> dict:
    """Return approved/blocked/escalated plus reasons. Never invents missing approvals."""
    names = [a.get("approver") for a in approvals if a.get("approved", True)]
    roles = {a.get("approver"): a.get("role", "approver") for a in approvals if a.get("approved", True)}
    reasons: list[str] = []
    if policy_variant == "buggy":
        return {"decision": "approved", "reasons": ["buggy-policy-variant-allows-everything"], "required": []}
    def _field(action, name: str, default: str = "") -> str:
        if isinstance(action, dict):
            value = action.get(name, default)
        else:
            value = getattr(action, name, default)
        return value if isinstance(value, str) else default

    wants_prod = any(_field(a, "environment", "dev") == "prod" for a in actions)
    wants_delete = any(_field(a, "operation") == "delete" for a in actions)
    distinct = [n for n in dict.fromkeys(names) if n]
    if wants_prod and "data_owner" not in set(roles.values()):
        reasons.append("production operations require data-owner approval")
    if wants_delete and len(distinct) < 2:
        reasons.append("delete operations require two distinct approvers")
    if wants_prod and not names:
        reasons.append("production operations require approval")
    if (wants_delete or wants_prod) and not names:
        reasons.append("sensitive operations require approval")
    if reasons:
        decision = "blocked" if names else "paused"
        if requester and requester in distinct and len(distinct) == 1:
            # Requester self-approval escalates for human review; the underlying
            # missing-approval reason is preserved (never fabricated).
            decision = "escalated"
            reasons.append("requester self-approval requires another approver")
        return {"decision": decision, "reasons": reasons, "required": reasons}
    if requester and requester in distinct and len(distinct) == 1:
        return {"decision": "escalated", "reasons": ["requester self-approval requires another approver"], "required": ["independent-approver"]}
    return {"decision": "approved", "reasons": ["non-sensitive run or sufficient approvals present"], "required": []}