"""Search-result categories for v0.106.

TIME_LIMIT is not EXHAUSTED. A depth budget is reported as NODE_LIMIT with
the raw stop reason left intact.
"""

from __future__ import annotations

from typing import Optional

SPEC_CATEGORIES = (
    "SOLVED_VALID",
    "EXHAUSTED",
    "TIME_LIMIT",
    "NODE_LIMIT",
    "MEMORY_LIMIT",
    "POLICY_BLOCKED",
    "INVALID",
    "ERROR",
)


def classify_stop(stop_reason: str, replay: Optional[dict] = None, *, policy_blocked: bool = False) -> str:
    if policy_blocked:
        return "POLICY_BLOCKED"
    if replay is not None:
        if not replay.get("ok"):
            return "INVALID"
        return "SOLVED_VALID"
    if stop_reason == "complete":
        return "EXHAUSTED"
    if stop_reason in ("time limit", "experiment budget"):
        return "TIME_LIMIT"
    if stop_reason in ("unique limit", "depth limit"):
        return "NODE_LIMIT"
    if stop_reason == "rss abort":
        return "MEMORY_LIMIT"
    return "ERROR"
