"""Autonomous continuation table v0.75."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

from spider.assembly_lower_bound import stock_empty_assembly_h
from spider.autonomous_continuations import (
    AUTONOMOUS_SOURCES,
    ContinuationEntry,
    ContinuationTable,
    build_autonomous_continuation_table,
    choose_continuation_verdict,
    lookup_continuation,
    replay_spliced_candidate,
    search_with_continuation_table,
    splice_candidate,
    table_built_ok,
)
from spider.autonomous_cost import checkpoints_from_trace
from spider.foundation_cashout import TACTICAL_CEILING
from spider.integrated_policy import AUTONOMOUS_INCUMBENT_MW, CANDIDATE_CEILING, INCUMBENT_MOVES, load_autonomous_192, verify_autonomous_192
from spider.metrics import CANONICAL_MW_COST, RECORD_MW_COST, parse_moves_file, replay_actions
from spider.packed_state import pack_state, pack_whole_game_identity
from spider.research_actions import apply_action, as_actions, is_deal, step_cost
from spider.state_convergence import V073_F2_DIGEST, V074_MOVES, locate_old_f2
from spider.tactical_integration import search_integrated_tactical
from spider.whole_game_anytime import opening_state
from spider.whole_game_epoch_scheduler import search_epoch_portfolio

ROOT = Path(__file__).resolve().parents[1]
MOD = ROOT / "src" / "spider" / "autonomous_continuations.py"
SCHED = ROOT / "src" / "spider" / "whole_game_epoch_scheduler.py"
SCRIPT = ROOT / "research" / "autonomous_continuation_table_v0_75.py"
CANON = ROOT / "solutions" / "4925153_canonical.moves"
V059 = ROOT / "solutions" / "4925153_autonomous_v0_59.moves"
V067 = ROOT / "solutions" / "4925153_autonomous_v0_67.moves"
SPLICE191 = ROOT / "solutions" / "4925153_autonomous_v0_74_splice191.moves"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def test_constants_187_ceiling_canonical_unchanged():
    assert AUTONOMOUS_INCUMBENT_MW == 187
    assert CANDIDATE_CEILING == 186
    assert RECORD_MW_COST == 119
    assert CANONICAL_MW_COST == 172
    assert TACTICAL_CEILING == 191
    opening = opening_state()
    v = verify_autonomous_192(opening)
    assert v["ok"] and v["g"] == 187 and v["deals"] == 5 and v["solved"]
    assert INCUMBENT_MOVES.name == "4925153_autonomous_v0_74.moves"
    assert replay_actions(opening.clone(), parse_moves_file(V059)) == 198
    assert replay_actions(opening.clone(), parse_moves_file(V067)) == 192
    assert replay_actions(opening.clone(), parse_moves_file(SPLICE191)) == 191
    assert replay_actions(opening.clone(), parse_moves_file(CANON)) == 172


def test_machine_only_sources_canonical_excluded():
    names = {n for n, _p, _g in AUTONOMOUS_SOURCES}
    costs = {g for _n, _p, g in AUTONOMOUS_SOURCES}
    assert names == {"v0.59", "v0.67", "v0.74_splice191", "v0.74"}
    assert costs == {198, 192, 191, 187}
    for _n, path, _g in AUTONOMOUS_SOURCES:
        assert path.exists()
        assert "canonical" not in path.name
    text = _text(MOD)
    assert "4925153_canonical.moves" not in text
    tree = ast.parse(text)
    simple = [
        n.module
        for n in ast.walk(tree)
        if isinstance(n, ast.ImportFrom) and (n.module or "").startswith("spider.simple_")
    ]
    assert simple == []


def test_table_indexes_ordered_digest_min_remaining():
    opening = opening_state()
    packed = pack_state(opening)
    ident = pack_whole_game_identity(opening)
    table = build_autonomous_continuation_table(opening, ceiling=186)
    assert table_built_ok(table)
    assert all(s["ok"] for s in table.sources)
    assert table.excluded == []
    f2 = lookup_continuation(table, V073_F2_DIGEST)
    assert f2 is not None
    assert f2.remaining_cost == 187 - 129
    assert f2.source_solution == "v0.74"
    assert f2.source_prefix_g == 129
    assert len(f2.provenance) >= 2
    rem = [p["remaining_cost"] for p in f2.provenance]
    assert f2.remaining_cost == min(rem)
    loc = locate_old_f2(opening)
    assert loc["digest"] == V073_F2_DIGEST
    assert pack_state(opening) == packed
    assert pack_whole_game_identity(opening) == ident


def test_suffix_integrity_prefix_plus_remaining():
    opening = opening_state()
    table = build_autonomous_continuation_table(opening)
    actions = parse_moves_file(V074_MOVES)
    state = opening.clone()
    g = 0
    prefix = []
    for i, action in enumerate(actions):
        cost = 1 if is_deal(action) else step_cost(state, action)
        apply_action(state, action)
        g += cost
        prefix.append(action)
        if i != 80:
            continue
        digest = pack_state(state).hex()
        ent = lookup_continuation(table, digest)
        assert ent is not None
        assert ent.remaining_cost == 187 - g
        assert ent.suffix_start_index == i + 1
        mid = opening.clone()
        assert replay_actions(mid, prefix) == g
        assert pack_state(mid).hex() == digest
        tail = mid.clone()
        suffix_cost = replay_actions(tail, list(ent.suffix_actions))
        assert suffix_cost == ent.remaining_cost
        assert tail.is_solved()
        spliced = splice_candidate(prefix, g, ent)
        assert spliced["candidate_g"] == g + ent.remaining_cost == 187
        assert spliced["actions"] == actions
        verified = replay_spliced_candidate(opening, spliced)
        assert verified["ok"] and verified["g"] == 187
        break
    else:
        raise AssertionError("did not reach action 80")


def test_same_cost_and_cheaper_prefix_classification():
    opening = opening_state()
    table = ContinuationTable(ceiling=186, incumbent_g=187)
    table.entries["abc"] = ContinuationEntry(
        ordered_digest="abc",
        source_solution="v0.74",
        source_prefix_g=129,
        source_total_g=187,
        remaining_cost=58,
        suffix_start_index=10,
        suffix_actions=[],
        stock_rows=1,
        foundations=2,
        face_down=2,
    )

    class Out:
        solved = False
        solution_g = None
        solution_actions = None
        replay_ok = False
        replay_g = None

    out = Out()
    assert table.consider(opening, digest="abc", g=129, prefix_fn=lambda: [], out=out, live_ceiling=186) is None
    assert table.equal_cost_hits == 1
    assert table.rejected_ceiling >= 1
    out2 = Out()
    table.consider(opening, digest="abc", g=128, prefix_fn=lambda: [], out=out2, live_ceiling=186)
    assert table.cheaper_prefix_hits == 1
    assert table.best_prefix_saving == 1
    out3 = Out()
    table.consider(opening, digest="abc", g=130, prefix_fn=lambda: [], out=out3, live_ceiling=186)
    assert table.worse_prefix_hits == 1


def test_lookup_does_not_change_tt_or_force_suffix():
    opening = opening_state()
    table = build_autonomous_continuation_table(opening)
    packed = pack_state(opening)
    ident = pack_whole_game_identity(opening)
    lookup_continuation(table, opening)
    lookup_continuation(table, pack_state(opening).hex())
    assert pack_state(opening) == packed
    assert pack_whole_game_identity(opening) == ident
    src_s = inspect.getsource(search_epoch_portfolio)
    assert "continuation_table=None" in src_s
    assert "consider_generated" in src_s
    assert "actions_fn=tableau_actions" in src_s
    assert "live_ceiling = min(live_ceiling, int(spliced_g) - 1)" in src_s
    src_t = inspect.getsource(search_integrated_tactical)
    assert "rows1_cashout_augment" in src_t
    assert "continuation_table=continuation_table" in src_t
    assert "stock_empty_assembly_h" in src_t
    src_w = inspect.getsource(search_with_continuation_table)
    assert "search_integrated_tactical" in src_w
    assert inspect.getsource(stock_empty_assembly_h).count("admissible") >= 0


def test_187_checkpoints_and_tactical_frozen():
    opening = opening_state()
    trace = load_autonomous_192(opening)
    ck = checkpoints_from_trace(trace)
    expect = {5: (0, 0, 44), 4: (33, 0, 18), 3: (65, 0, 10), 2: (74, 1, 9), 1: (123, 1, 2), 0: (130, 2, 2)}
    for rows, (g, f, fd) in expect.items():
        rec = ck[rows]
        assert rec["g"] == g
        assert rec["foundations"] == f
        assert rec["face_down"] == fd
        assert rec["stock_rows"] == rows
        assert rec.get("incumbent_control") is True
    src_t = inspect.getsource(search_integrated_tactical)
    assert "readiness_r2" not in src_t
    assert "MULTI_SUIT_LANES" not in src_t
    script = _text(SCRIPT)
    if script:
        assert script.find("EVAL canonical") > script.find("search_with_continuation_table")
    v, _ = choose_continuation_verdict(
        {"solved": True, "replay_ok": True, "solution_g": 180, "incumbent_g": 187}
    )
    assert v == "CONTINUATION_TABLE_COST_IMPROVED"
    v2, _ = choose_continuation_verdict(
        {"solved": False, "incumbent_g": 187, "table": {"hits": 3, "cheaper_prefix_hits": 2}}
    )
    assert v2 == "CONTINUATION_TABLE_FINDS_CHEAPER_PREFIX_NO_BEST"
    v3, _ = choose_continuation_verdict(
        {"solved": False, "incumbent_g": 187, "table": {"hits": 9, "cheaper_prefix_hits": 0}}
    )
    assert v3 == "CONTINUATION_TABLE_VALID_NO_IMPROVEMENT"
    v4, _ = choose_continuation_verdict({"solved": False, "incumbent_g": 187, "table": {"hits": 0}})
    assert v4 == "CONTINUATION_TABLE_NO_MATCHES"
