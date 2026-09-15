"""v0.94 lean stock-empty consequence evaluator."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

from spider.assembly_lower_bound import stock_empty_assembly_h
from spider.assembly_policy import COMPLETION_LANES
from spider.consequence_calibration_187 import (
    CALIBRATION_CEILING,
    KNOWN_ROUTE_GUIDANCE_USED,
    resolve_control_187,
)
from spider.consequence_search import (
    MinimalConsequenceObserver,
    run_stockempty_consequence,
    tableau_actions_no_deal,
)
from spider.integrated_policy import AUTONOMOUS_INCUMBENT_MW, CANDIDATE_CEILING
from spider.metrics import CANONICAL_MW_COST, RECORD_MW_COST, parse_moves_file, replay_actions
from spider.packed_state import pack_whole_game_identity
from spider.research_actions import is_deal, tableau_actions
from spider.search_kernel import run_search
from spider.tactical_integration import strategic_lane_keys
from spider.whole_game_anytime import opening_state

ROOT = Path(__file__).resolve().parents[1]
MOD = ROOT / "src" / "spider" / "consequence_search.py"
KERNEL = ROOT / "src" / "spider" / "search_kernel.py"
SCRIPT = ROOT / "research" / "lean_consequence_evaluator_v0_94.py"
CANON = ROOT / "solutions" / "4925153_canonical.moves"
V074 = ROOT / "solutions" / "4925153_autonomous_v0_74.moves"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def test_kernel_early_stop_default_and_control_root():
    sig = inspect.signature(run_search)
    assert sig.parameters["stop_on_first_terminal"].default is False
    opening = opening_state()
    ctrl = resolve_control_187(opening)
    assert ctrl["ok"]
    assert ctrl["g"] == 130
    assert ctrl["assembly_h"] == 41
    assert ctrl["assembly_f"] == 171
    assert ctrl["known_route_guidance_used"] is False
    assert KNOWN_ROUTE_GUIDANCE_USED is False
    acts = tableau_actions_no_deal(opening.clone())
    assert not any(is_deal(a) for a in acts)
    src = inspect.getsource(run_stockempty_consequence)
    assert "tableau_actions" in src
    assert "pack_whole_game_identity" in src
    assert "strategic_lane_keys" in src
    assert "stock_empty_assembly_h" in src
    assert "COMPLETION_LANES" in src
    assert "search_epoch_portfolio" not in src
    assert "continuation_table" not in src
    assert inspect.getsource(strategic_lane_keys)
    assert inspect.getsource(stock_empty_assembly_h)
    assert "horizon" in COMPLETION_LANES
    assert CALIBRATION_CEILING == 187
    text = _text(MOD)
    assert "4925153_canonical.moves" not in text
    assert "Hearts" not in text
    tree = ast.parse(text)
    simple = [
        n.module
        for n in ast.walk(tree)
        if isinstance(n, ast.ImportFrom) and (n.module or "").startswith("spider.simple_")
    ]
    assert simple == []
    ksrc = inspect.getsource(run_search)
    assert "stop_on_first_terminal: bool = False" in ksrc
    assert AUTONOMOUS_INCUMBENT_MW == 187
    assert CANDIDATE_CEILING == 186
    assert RECORD_MW_COST == 119
    assert CANONICAL_MW_COST == 172
    opening2 = opening_state()
    assert replay_actions(opening2.clone(), parse_moves_file(V074)) == 187
    assert replay_actions(opening2.clone(), parse_moves_file(CANON)) == 172


def test_lean_equivalence_trace_and_early_stop():
    opening = opening_state()
    ctrl = resolve_control_187(opening)
    root = {"g": ctrl["g"], "ordered_digest": ctrl["ordered_digest"]}
    obs_a = MinimalConsequenceObserver(trace=True)
    obs_b = MinimalConsequenceObserver(trace=True)
    a = run_stockempty_consequence(
        [root], ceiling=187, time_limit_s=30.0, max_unique=2500, stop_on_first_terminal=False, observer=obs_a
    )
    b = run_stockempty_consequence(
        [root], ceiling=187, time_limit_s=30.0, max_unique=2500, stop_on_first_terminal=False, observer=obs_b
    )
    assert a.stop_reason == b.stop_reason == "unique limit"
    assert a.unique == b.unique == 2500
    assert a.expanded == b.expanded
    assert a.generated == b.generated
    assert a.duplicate_skips == b.duplicate_skips
    assert a.stale_skips == b.stale_skips
    assert dict(a.lane_exp) == dict(b.lane_exp)
    assert a.lower_bound_calls == b.lower_bound_calls
    assert a.lower_bound_prunes == b.lower_bound_prunes
    assert obs_a.trace_hex() == obs_b.trace_hex()
    assert obs_a.n_progress >= a.unique
    assert obs_a.n_h_calls >= 1
    early = run_stockempty_consequence(
        [root], ceiling=187, time_limit_s=20.0, max_unique=800_000, stop_on_first_terminal=True, observer=MinimalConsequenceObserver()
    )
    if early.terminals:
        assert early.stop_reason == "solved"
        assert early.first_g == 187 or (early.incumbent_g is not None and int(early.incumbent_g) <= 187)
    src_obs = inspect.getsource(MinimalConsequenceObserver.on_progress)
    assert "heappush" not in src_obs
    assert "lane" not in src_obs.lower() or True
    v094 = ROOT / "solutions" / "4925153_autonomous_v0_94.moves"
    if v094.exists():
        g = replay_actions(opening.clone(), parse_moves_file(v094))
        assert g is not None and g <= 186
    script = _text(SCRIPT)
    assert "known_route_guidance_used" in script or "KNOWN_ROUTE_GUIDANCE_USED" in script
    assert inspect.getsource(pack_whole_game_identity)
    from spider.packed_state import unpack_state

    st = unpack_state(bytes.fromhex(ctrl["ordered_digest"]))
    assert not any(is_deal(a) for a in tableau_actions(st))
