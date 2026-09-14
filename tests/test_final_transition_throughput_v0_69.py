"""Final-transition harvest throughput v0.69."""

from __future__ import annotations

import ast
import inspect
import random
from pathlib import Path

from spider.assembly_policy import COMPLETION_LANES
from spider.deal_preview import preview_next_deal
from spider.final_deal_transition import (
    IncrementalPareto,
    TRANSITION_CATS,
    TRANSITION_HARVEST_CATS,
    TransitionTracker,
    TransitionTrackerLegacy,
    pareto_preview,
)
from spider.integrated_policy import (
    AUTONOMOUS_INCUMBENT_MW,
    CANDIDATE_CEILING,
    load_autonomous_192,
    search_integrated_optimisation,
    verify_autonomous_192,
)
from spider.metrics import parse_moves_file, replay_actions
from spider.operational_policy import search_operational_optimisation
from spider.packed_state import pack_state, pack_whole_game_identity
from spider.research_actions import as_actions, is_deal
from spider.whole_game_anytime import opening_state
from spider.whole_game_epoch_scheduler import _Top, harvest_portfolio, search_epoch_portfolio

ROOT = Path(__file__).resolve().parents[1]
MOD = ROOT / "src" / "spider" / "final_deal_transition.py"
POLICY = ROOT / "src" / "spider" / "integrated_policy.py"
SCHED = ROOT / "src" / "spider" / "whole_game_epoch_scheduler.py"
KERNEL = ROOT / "src" / "spider" / "search_kernel.py"
SCRIPT = ROOT / "research" / "final_transition_throughput_v0_69.py"
ARTEFACT = ROOT / "docs" / "research" / "final_transition_throughput_v0_69.json"
V067 = ROOT / "solutions" / "4925153_autonomous_v0_67.moves"
V059 = ROOT / "solutions" / "4925153_autonomous_v0_59.moves"
CANON = ROOT / "solutions" / "4925153_canonical.moves"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _simple_imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [
        n.module
        for n in ast.walk(tree)
        if isinstance(n, ast.ImportFrom) and (n.module or "").startswith("spider.simple_")
    ]


def _rec(ident, *, g=130, F=2, fd=2, legal=8, bounds=20, comps=30, op=False, extra=0):
    return {
        "ident": ident,
        "whole_game_identity": ident,
        "ordered_digest": ident,
        "g": g,
        "foundations": F,
        "face_down": fd,
        "empty_n": 1,
        "bonds": 4,
        "stock_rows": 1,
        "n_ready": 1 if op else 0,
        "cover": 3,
        "preview": {
            "ok": True,
            "post_g": g + 1,
            "foundations": F,
            "face_down": fd,
            "legal_tableau": legal,
            "boundaries": bounds,
            "visible_components": comps,
            "component_layers": extra,
            "same_suit": extra % 4,
            "rank_ok": extra % 3,
            "mixed": 9 - (extra % 4),
            "op_defined": op,
            "op_key": [fd, extra, g] if op else None,
        },
    }


def test_incremental_pareto_equals_full_on_random_and_edges():
    rng = random.Random(69)
    for case in range(80):
        n = rng.randint(4, 40)
        rows = []
        for i in range(n):
            rows.append(
                _rec(
                    f"{case}:{i}",
                    g=120 + rng.randint(0, 20),
                    F=rng.randint(1, 3),
                    fd=rng.randint(0, 6),
                    legal=rng.randint(0, 20),
                    bounds=rng.randint(0, 40),
                    comps=rng.randint(5, 50),
                    op=bool(rng.randint(0, 1)),
                    extra=rng.randint(0, 12),
                )
            )
        full = {r.get("ident") for r in pareto_preview(rows)}
        inc = IncrementalPareto()
        order = list(rows)
        rng.shuffle(order)
        for rec in order:
            inc.add(rec)
        assert inc.ident_set() == full

    a = _rec("a", legal=10, bounds=5, op=True, extra=1)
    b = _rec("b", legal=4, bounds=30, op=True, extra=9)
    c = _rec("c", legal=10, bounds=5, op=False, extra=1)
    d = _rec("d", g=130, legal=10, bounds=5, op=True, extra=1)
    # d identical vec to a except ident — both nondominated
    inc = IncrementalPareto()
    for rec in (b, a, c, d):
        inc.add(rec)
    assert inc.ident_set() == {r["ident"] for r in pareto_preview([a, b, c, d])}
    # late dominator: worse first, then better
    worse = _rec("w", legal=2, bounds=40, g=150, op=False)
    better = _rec("g", legal=20, bounds=1, g=130, op=False)
    inc2 = IncrementalPareto()
    inc2.add(worse)
    inc2.add(better)
    assert inc2.ident_set() == {"g"}
    inc3 = IncrementalPareto()
    inc3.add(better)
    inc3.add(worse)
    assert inc3.ident_set() == {"g"}
    # duplicates
    x = _rec("x", legal=7, bounds=8)
    y = _rec("x", legal=7, bounds=8)
    inc4 = IncrementalPareto()
    inc4.add(x)
    inc4.add(y)
    assert "x" in inc4.ident_set()
    # large front of incomparable points
    front = [_rec(f"f{i}", g=100 + i, legal=i, bounds=50 - i, op=False) for i in range(25)]
    inc5 = IncrementalPareto()
    for rec in front:
        inc5.add(rec)
    assert inc5.ident_set() == {r["ident"] for r in pareto_preview(front)}


def test_transition_categories_match_legacy_except_documented_pareto():
    rng = random.Random(7)
    corpus = [
        _rec(
            f"c{i}",
            g=125 + rng.randint(0, 15),
            F=2,
            fd=rng.randint(0, 4),
            legal=rng.randint(3, 18),
            bounds=rng.randint(8, 36),
            comps=rng.randint(15, 45),
            op=i % 3 == 0,
            extra=i % 11,
        )
        for i in range(80)
    ]
    tops_old = {cat: _Top() for cat in TRANSITION_HARVEST_CATS}
    tops_new = {cat: _Top() for cat in TRANSITION_HARVEST_CATS}
    old = TransitionTrackerLegacy()
    new = TransitionTracker()
    for rec in corpus:
        old(tops_old, rec, 125, {})
        new(tops_new, rec, 125, {})
    new.finalize(tops_new, [], 125, 1)
    for cat in ("post_deal_mobility", "post_deal_consolidation", "post_deal_operational", "post_deal_reception"):
        old_ids = [r["ident"] for r in tops_old[cat].best()]
        new_ids = [r["ident"] for r in tops_new[cat].best()]
        assert old_ids == new_ids, cat
    exact = {r["ident"] for r in pareto_preview(corpus)}
    assert new.front.ident_set() == exact
    # legacy truncates the pool, so its Pareto may be a subset of exact
    legacy_ids = {r["ident"] for r in tops_old["post_deal_pareto"].best()}
    assert legacy_ids <= exact or old.n_pool_truncations == 0


def test_finalize_hook_default_off_and_identity_untouched():
    src = inspect.getsource(search_epoch_portfolio)
    assert "finalize_track=None" in src
    opening = opening_state()
    packed = pack_state(opening)
    ident = pack_whole_game_identity(opening)
    res = search_epoch_portfolio(
        opening=opening,
        max_unique=8,
        time_limit_s=0.4,
        rss_abort_mb=4096,
        cost_ceiling=191,
        portfolio_width=4,
    )
    assert res.candidate_ceiling == 191
    preview_next_deal(opening, pre_g=0)
    assert pack_state(opening) == packed
    assert pack_whole_game_identity(opening) == ident
    kern = _text(KERNEL)
    assert "post_deal_pareto" not in kern
    assert "IncrementalPareto" not in kern


def test_no_canonical_ceiling_192_replay_assembly_lanes():
    for path in (MOD, POLICY):
        text = _text(path)
        assert "4925153_canonical.moves" not in text
        assert _simple_imports(path) == []
    src = inspect.getsource(search_operational_optimisation)
    assert "incumbent_g - 1" in src
    assert "durability" not in src
    assert "finalize_track=finalize_track" in src
    src_i = inspect.getsource(search_integrated_optimisation)
    assert "finalize_track=tracker.finalize" in src_i
    assert "completion" in COMPLETION_LANES
    assert set(TRANSITION_CATS) <= set(TRANSITION_HARVEST_CATS)
    opening = opening_state()
    v = verify_autonomous_192(opening)
    assert v["ok"] and v["g"] == AUTONOMOUS_INCUMBENT_MW == 187
    assert CANDIDATE_CEILING == 186
    trace = load_autonomous_192(opening)
    from spider.autonomous_cost import checkpoints_from_trace

    ck = checkpoints_from_trace(trace)
    assert 1 in ck
    rec = ck[1]
    end = opening.clone()
    g = replay_actions(end, as_actions(rec["full_actions"]))
    assert g == rec["g"]
    assert rec["stock_rows"] == 1
    assert pack_state(end).hex() == rec["ordered_digest"]
    assert rec.get("incumbent_control") is True


def test_script_canonical_after_search_and_old_solutions():
    script = _text(SCRIPT)
    if script:
        search_at = script.find("search_integrated_optimisation(")
        eval_at = script.find("EVAL canonical")
        assert search_at != -1
        assert eval_at > search_at
    opening = opening_state()
    e198 = opening.clone()
    assert replay_actions(e198, parse_moves_file(V059)) == 198
    e172 = opening.clone()
    assert replay_actions(e172, parse_moves_file(CANON)) == 172
    e192 = opening.clone()
    assert replay_actions(e192, parse_moves_file(V067)) == 192


def test_artefact_terminal_if_present():
    if not ARTEFACT.exists():
        return
    import json

    from spider.healthy_f2 import parse_stored_actions

    data = json.loads(ARTEFACT.read_text(encoding="utf-8"))
    if data.get("solved") and data.get("solution_actions"):
        opening = opening_state()
        actions = parse_stored_actions(data["solution_actions"])
        end = opening.clone()
        g = replay_actions(end, actions)
        assert end.is_solved()
        assert g < 192
        assert sum(1 for a in actions if is_deal(a)) == 5
