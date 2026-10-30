"""Lock the one-shot reserved evaluation.

These boards were first searched after implementation commit
4e2f8e3ca2f4b750443c782e3c7d5513c2ff814d. This test repeats that same
budget. It does not raise a cap or change the evaluator.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.dependency_objective_lookahead import compare_panel_board
from spider.dependency_objective_panel import board_by_id, build_state
from spider.research_actions import tableau_actions

_LOCKED = {
    "distractor-reveal": {
        "status": "ranked",
        "choice": "(0, 2, 1)",
        "baseline": "(5, 6, 1)",
        "legal": ((0, 2, 1), (5, 6, 1)),
        "rows": {
            "(5, 6, 1)": ("exact", 3, "complete", ((0, 2, 1), (0, 1, 1)), 8),
            "(0, 2, 1)": ("exact", 2, "complete", ((0, 1, 1),), 9),
        },
    },
    "three-deep-uncover": {
        "status": "ranked",
        "choice": "(0, 2, 1)",
        "baseline": "(4, 5, 1)",
        "legal": ((0, 2, 1), (2, 3, 1), (4, 5, 1)),
        "rows": {
            "(4, 5, 1)": ("exact", 4, "complete", ((0, 2, 1), (0, 3, 1), (0, 1, 1)), 8),
            "(0, 2, 1)": ("exact", 3, "complete", ((0, 3, 1), (0, 1, 1)), 15),
            "(2, 3, 1)": ("exhausted-no-hit", None, "complete", (), 4),
        },
    },
    "zero-cost-workspace": {
        "status": "inconclusive",
        "choice": "(5, 6, 1)",
        "baseline": "(5, 6, 1)",
        "legal": ((1, 2, 1), (2, 3, 1), (5, 6, 1)),
        "rows": {
            "(5, 6, 1)": ("unknown", None, "unique limit", (), 20),
            "(1, 2, 1)": ("exhausted-no-hit", None, "complete", (), 4),
            "(2, 3, 1)": ("unknown", None, "unique limit", (), 20),
        },
    },
}


def test_reserved_one_shot_results_stay_locked():
    comparable = 0
    improvements = 0
    for board_id, expected in _LOCKED.items():
        board = board_by_id(board_id)
        assert board.role == "reserved"
        state = build_state(board)
        result = compare_panel_board(board)
        assert result.status == expected["status"]
        assert result.choice_id == expected["choice"]
        assert result.baseline_id == expected["baseline"]
        assert result.legal_actions == tuple(tableau_actions(state)) == expected["legal"]
        assert result.pruned == ()
        assert result.rejected_option_ids == ()
        assert result.absolute_g_used_for_proof is False
        assert result.obligations_status == "matched"
        rows = {row.option_id: row for row in result.candidates}
        assert list(rows) == list(expected["rows"])
        resolved = True
        for option_id, (status, total, stop, continuation, unique) in expected["rows"].items():
            row = rows[option_id]
            assert row.status == status
            assert row.total_cost == total
            assert row.continuation_cost is None or row.total_cost == row.prefix_cost + row.continuation_cost
            assert row.stop_reason == stop
            assert row.continuation == continuation
            assert row.unique == unique
            if status in ("unknown", "upper-unfinished"):
                resolved = False
                assert row.total_cost is None or status == "upper-unfinished"
        if resolved:
            comparable += 1
            pilot = rows[result.choice_id]
            baseline = rows[result.baseline_id]
            assert pilot.status == "exact"
            assert baseline.status == "exact"
            assert pilot.total_cost <= baseline.total_cost
            if pilot.total_cost < baseline.total_cost:
                improvements += 1
        if board_id == "zero-cost-workspace":
            assert result.choice_id == result.baseline_id
            assert all(row.total_cost is None for row in result.candidates)
            setup = rows["(2, 3, 1)"]
            bait = rows["(5, 6, 1)"]
            assert setup.zero_cost_actions == 2
            assert bait.zero_cost_actions == 2
            assert setup.kernel_called is True
            assert setup.prefix_cost == 1
    assert comparable == 2
    assert improvements == 2
