"""Default progressive local campaign stages. Durations are not shortened for Build time."""

from __future__ import annotations

from typing import Optional

DEFAULT_ROUNDS = (
    {"round": 1, "time_s": 60.0, "max_candidates": None, "label": "60s"},
    {"round": 2, "time_s": 300.0, "max_candidates": None, "label": "5 minutes"},
    {"round": 3, "time_s": 1800.0, "max_candidates": None, "label": "30 minutes"},
    {"round": 4, "time_s": 7200.0, "max_candidates": None, "label": "2 hours"},
    {"round": 5, "time_s": 28800.0, "max_candidates": None, "label": "8 hours"},
    {"round": 6, "time_s": 86400.0, "max_candidates": None, "label": "24 hours"},
    {"round": 7, "time_s": 86400.0, "max_candidates": None, "label": "REPEAT 24H", "repeat": True},
)


def round_spec(n: int, rounds=DEFAULT_ROUNDS) -> Optional[dict]:
    for rec in rounds:
        if int(rec["round"]) == int(n):
            return dict(rec)
    return None


def next_round_for_node(node: dict, rounds=DEFAULT_ROUNDS) -> dict:
    """Next deeper unattempted round from this node's own history.

    0 -> 60s, 60s -> 5m, 5m -> 30m, 30m -> 2h, 2h -> 8h, 8h -> 24h.
    After 24h: REPEAT 24H (honest 24h jobs, not a fake 7-day UNTIL STOPPED).
    """

    deepest = float(node.get("deepest_budget_s") or 0.0)
    for rec in rounds:
        if rec.get("repeat"):
            continue
        if float(rec["time_s"]) > deepest + 1e-6:
            return dict(rec)
    for rec in rounds:
        if rec.get("repeat"):
            return dict(rec)
    return dict(rounds[-1])
