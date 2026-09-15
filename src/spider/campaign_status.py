"""Campaign outcome labels. A timeout is not failure and is never PROOF_DEAD."""

from __future__ import annotations

SOLVED = "SOLVED"
PROOF_DEAD = "PROOF_DEAD"
EXHAUSTED = "EXHAUSTED"
KNOWN_CLOSED = "KNOWN_CLOSED"
LOWER_G_REOPENING = "LOWER_G_REOPENING"
UNRESOLVED_TIME = "UNRESOLVED_TIME"
UNRESOLVED_UNIQUE = "UNRESOLVED_UNIQUE"
CANCELLED = "CANCELLED"
FAILED_CONTRACT = "FAILED_CONTRACT"
OPEN = "OPEN"
GENERATION_UNRESOLVED_TIME = "GENERATION_UNRESOLVED_TIME"
PROOF_DEAD_185 = "PROOF_DEAD_185"

OUTCOMES = (
    SOLVED,
    PROOF_DEAD,
    PROOF_DEAD_185,
    EXHAUSTED,
    KNOWN_CLOSED,
    LOWER_G_REOPENING,
    UNRESOLVED_TIME,
    UNRESOLVED_UNIQUE,
    GENERATION_UNRESOLVED_TIME,
    CANCELLED,
    FAILED_CONTRACT,
    OPEN,
)


def proof_dead_label(ceiling: int) -> str:
    return f"PROOF_DEAD_{int(ceiling)}"


def classify_outcome(result: dict, *, ceiling: int, assembly_f=None, cancelled: bool = False) -> str:
    """Map a search result to an explicit campaign status.

    Time/unique limits are UNRESOLVED_*. Proof-dead is only g+h > ceiling.
    """

    if cancelled or result.get("cancelled"):
        return CANCELLED
    if result.get("contract_fail") or result.get("status") == "failed" or result.get("outcome") == FAILED_CONTRACT:
        return FAILED_CONTRACT
    if result.get("solved") and result.get("terminal_g") is not None:
        return SOLVED
    if result.get("lower_g_reopening"):
        return LOWER_G_REOPENING
    if result.get("known_closed"):
        return KNOWN_CLOSED
    stop = str(result.get("stop_reason") or "")
    if stop == "complete":
        return EXHAUSTED
    if assembly_f is not None and int(assembly_f) > int(ceiling):
        return proof_dead_label(ceiling)
    if stop == "unique limit":
        return UNRESOLVED_UNIQUE
    if stop in ("time limit", "rss abort"):
        return UNRESOLVED_TIME
    if stop == "solved":
        return SOLVED
    return UNRESOLVED_TIME


def status_is_unresolved(status: str) -> bool:
    return status in (UNRESOLVED_TIME, UNRESOLVED_UNIQUE, OPEN, GENERATION_UNRESOLVED_TIME, LOWER_G_REOPENING)


def status_is_dead_or_failed(status: str) -> bool:
    return status in (PROOF_DEAD, FAILED_CONTRACT) or str(status).startswith("PROOF_DEAD")
