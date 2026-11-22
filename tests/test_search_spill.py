"""A spilled frontier continues the same search past the RAM copy."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.research_actions import all_legal_actions, opening_from_deal
from spider.packed_state import pack_state, unpack_state
from spider.search_kernel import SearchLimits, run_search
from spider.search_spill import FrontierSpill

DEAL = ROOT / "deals" / "4925153.txt"


def _run(path, unique, *, fraction):
    opening = opening_from_deal(DEAL)
    return run_search(
        [{"g": 0, "ordered_digest": pack_state(opening).hex()}],
        limits=SearchLimits(
            max_unique=unique,
            time_limit_s=30,
            rss_abort_mb=8192,
            cost_ceiling=300,
            spill_dir=None if path is None else str(path),
            spill_rss_fraction=fraction,
        ),
        identity_fn=pack_state,
        store_fn=pack_state,
        unpack_fn=unpack_state,
        lane_names=("cost",),
        lane_key_fns=[lambda _state, g: (int(g),)],
        actions_fn=all_legal_actions,
        is_terminal=lambda _state: False,
        representation="compact",
    )


def _signature(result):
    return sorted(
        (int(node.parent), int(node.g), None if node.action is None else tuple(node.action))
        for node in result.nodes
    )


def test_spilled_search_matches_memory_and_resumes(tmp_path):
    memory = _run(None, 8, fraction=0.72)
    assert memory.stop_reason == "unique limit"
    assert memory.unique == 8
    spilled_path = tmp_path / "frontier.sqlite"
    spilled = _run(spilled_path, 8, fraction=0.0)
    assert spilled.stop_reason == "unique limit"
    assert spilled.unique == 8
    assert _signature(spilled) == _signature(memory)
    stored = FrontierSpill.peek(spilled_path)
    assert stored["resumable"] is True
    assert stored["unique"] == 8
    del spilled
    resumed = _run(spilled_path, 14, fraction=0.0)
    assert resumed.unique > 8
    assert resumed.stop_reason == "unique limit"
    assert resumed.unique == 14
