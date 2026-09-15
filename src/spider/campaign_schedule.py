"""Default progressive local campaign stages. Durations are not shortened for Build time."""

from __future__ import annotations

from typing import Optional

DEFAULT_ROUNDS = (
    {"round": 1, "time_s": 60.0, "max_candidates": None, "label": "all unresolved"},
    {"round": 2, "time_s": 300.0, "max_candidates": None, "label": "5 minutes"},
    {"round": 3, "time_s": 1800.0, "max_candidates": None, "label": "30 minutes"},
    {"round": 4, "time_s": 7200.0, "max_candidates": None, "label": "2 hours"},
    {"round": 5, "time_s": 28800.0, "max_candidates": None, "label": "8 hours"},
    {"round": 6, "time_s": 86400.0, "max_candidates": None, "label": "24 hours"},
    {"round": 7, "time_s": 604800.0, "max_candidates": None, "label": "UNTIL STOPPED"},
)


def round_spec(n: int, rounds=DEFAULT_ROUNDS) -> Optional[dict]:
    for rec in rounds:
        if int(rec["round"]) == int(n):
            return dict(rec)
    return None
