"""Default progressive local campaign stages. Durations are not shortened for Build time."""

from __future__ import annotations

from typing import Optional

DEFAULT_ROUNDS = (
    {"round": 1, "time_s": 60.0, "max_candidates": None, "label": "all proof-live"},
    {"round": 2, "time_s": 300.0, "max_candidates": 64, "label": "selected survivors"},
    {"round": 3, "time_s": 1800.0, "max_candidates": 16, "label": "deep survivors"},
    {"round": 4, "time_s": 7200.0, "max_candidates": 4, "label": "finalists"},
)


def round_spec(n: int, rounds=DEFAULT_ROUNDS) -> Optional[dict]:
    for rec in rounds:
        if int(rec["round"]) == int(n):
            return dict(rec)
    return None
