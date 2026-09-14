"""State-convergence 191 splice and focused endgame v0.74."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

from spider.assembly_lower_bound import stock_empty_assembly_h
from spider.foundation_cashout import TACTICAL_CEILING
from spider.integrated_policy import AUTONOMOUS_INCUMBENT_MW, CANDIDATE_CEILING, INCUMBENT_MOVES, verify_autonomous_192
from spider.metrics import CANONICAL_MW_COST, RECORD_MW_COST, parse_moves_file, replay_actions
from spider.packed_state import pack_state, pack_whole_game_identity, unpack_state
from spider.research_actions import apply_action, as_actions, is_deal, step_cost, stock_rows
from spider.search_kernel import SearchLimits, run_search
from spider.state_convergence import (
    FOCUSED_ROOT_G,
    NEW_F2_G,
    OLD_F2_G,
    PARENT_INCUMBENT_G,
    SPLICED_G,
    V074_BEST_MOVES,
    V074_MOVES,
    V074_SPLICE_MOVES,
    apply_final_deal,
    build_verified_191,
    locate_old_f2,
    old_actual_post_sd5,
    old_post_sd5,
    reconstruct_v073_prefix,
    search_focused_endgame,
    splice_candidate,
    verify_old_192,
    verify_suffix_sequence,
    v073_f2_digest,
)
from spider.whole_game_anytime import opening_state

ROOT = Path(__file__).resolve().parents[1]
MOD = ROOT / "src" / "spider" / "state_convergence.py"
SCRIPT = ROOT / "research" / "state_convergence_endgame_v0_74.py"
KERNEL = ROOT / "src" / "spider" / "search_kernel.py"
V067 = ROOT / "solutions" / "4925153_autonomous_v0_67.moves"
CANON = ROOT / "solutions" / "4925153_canonical.moves"
V059 = ROOT / "solutions" / "4925153_autonomous_v0_59.moves"
BEST = ROOT / "solutions" / "4925153_autonomous_v0_74_best.moves"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def test_constants_promoted_canonical_unchanged():
    assert AUTONOMOUS_INCUMBENT_MW == 187
    assert CANDIDATE_CEILING == 186
    assert SPLICED_G == 191
    assert RECORD_MW_COST == 119
    assert CANONICAL_MW_COST == 172
    assert PARENT_INCUMBENT_G == 192
    assert TACTICAL_CEILING == 191
    opening = opening_state()
    assert replay_actions(opening.clone(), parse_moves_file(V067)) == 192
    assert replay_actions(opening.clone(), parse_moves_file(CANON)) == 172
    assert replay_actions(opening.clone(), parse_moves_file(V059)) == 198
    if V074_SPLICE_MOVES.exists():
        assert replay_actions(opening.clone(), parse_moves_file(V074_SPLICE_MOVES)) == 191


def test_old_192_and_unique_f2_digest():
    opening = opening_state()
    v = verify_old_192(opening)
    assert v["ok"] and v["g"] == 192 and v["deals"] == 5
    loc = locate_old_f2(opening)
    assert loc["ok"]
    assert loc["n_hits"] == 1
    assert loc["g"] == OLD_F2_G == 130
    assert loc["stock_rows"] == 1
    assert loc["face_down"] == 2
    assert loc["foundations"] == 2
    assert set(loc["foundation_suits"]) == {"s", "d"}
    assert loc["digest"] == v073_f2_digest()


def test_reconstruct_v073_prefix_g129():
    opening = opening_state()
    pre = reconstruct_v073_prefix(opening, time_limit_s=15.0)
    assert pre["ok"], pre.get("reason")
    assert pre["g"] == NEW_F2_G == 129
    assert pre["digest"] == v073_f2_digest()
    assert pre["stock_rows"] == 1
    assert pre["face_down"] == 2
    assert pre["foundations"] == 2
    assert pre["checkpoint_g"] == 123
    assert pre["n_tactical"] >= 1
    assert not any(is_deal(a) for a in as_actions(pre["tactical_actions"]))


def test_splice_191_if_artefact_present():
    splice = V074_SPLICE_MOVES if V074_SPLICE_MOVES.exists() else V074_MOVES
    if not splice.exists():
        return
    opening = opening_state()
    end = opening.clone()
    actions = parse_moves_file(splice)
    g = replay_actions(end, actions)
    assert g == 191
    assert end.is_solved()
    assert sum(1 for a in actions if is_deal(a)) == 5
    assert not end.stock
    assert all(c.is_empty() for c in end.columns)
    loc = locate_old_f2(opening)
    prefix_n = None
    state = opening.clone()
    gg = 0
    for i, action in enumerate(actions):
        cost = 1 if is_deal(action) else step_cost(state, action)
        apply_action(state, action)
        gg += cost
        if pack_state(state).hex() == loc["digest"]:
            prefix_n = i + 1
            assert gg == NEW_F2_G == 129
            break
    assert prefix_n is not None
    suffix = as_actions(loc["suffix"])
    prefix = actions[:prefix_n]
    assert actions[prefix_n:] == suffix
    assert splice_candidate(prefix, suffix) == actions
    assert len(prefix) + len(suffix) == len(actions)
    seq = verify_suffix_sequence(opening, prefix, suffix)
    assert seq["ok"]
    assert seq["terminal_new_g"] == 191
    assert seq["terminal_old_g"] == 192


def test_focused_root_post_sd5_if_artefact_present():
    splice = V074_SPLICE_MOVES if V074_SPLICE_MOVES.exists() else V074_MOVES
    if not splice.exists():
        return
    opening = opening_state()
    loc = locate_old_f2(opening)
    actions = parse_moves_file(splice)
    state = opening.clone()
    g = 0
    prefix = []
    for action in actions:
        cost = 1 if is_deal(action) else step_cost(state, action)
        apply_action(state, action)
        g += cost
        prefix.append(action)
        if pack_state(state).hex() == loc["digest"]:
            break
    focused = apply_final_deal(opening, prefix)
    old_post = old_post_sd5(opening, loc)
    actual = old_actual_post_sd5(opening, loc)
    assert focused["ok"]
    assert focused["g"] == FOCUSED_ROOT_G == 130
    assert focused["stock_rows"] == 0
    assert old_post["ok"]
    assert old_post["g"] == 131
    assert focused["ordered_digest"] == old_post["ordered_digest"]
    assert actual["ok"]
    assert actual["deal_suffix_index"] != 0
    assert focused["ordered_digest"] != actual["ordered_digest"]
    unpacked = unpack_state(bytes.fromhex(focused["ordered_digest"]))
    h = stock_empty_assembly_h(unpacked, focused["g"])
    assert focused["assembly_h"] == h
    src = inspect.getsource(search_focused_endgame)
    assert "No suffix" in src
    assert "incumbent_by_rows={}" in src
    assert "epoch_augment_fn=None" in src
    assert "canonical" not in src.lower()
    assert "cost_ceiling=SPLICED_G - 1" in src
    assert "V067" not in src


def test_no_canonical_and_assembly_bound_frozen():
    text = _text(MOD)
    assert "4925153_canonical.moves" not in text
    tree = ast.parse(text)
    simple = [
        n.module
        for n in ast.walk(tree)
        if isinstance(n, ast.ImportFrom) and (n.module or "").startswith("spider.simple_")
    ]
    assert simple == []
    src = inspect.getsource(search_focused_endgame)
    assert "stock_empty_assembly_h" in src
    assert "pack_whole_game_identity" in _text(MOD)
    kern = _text(KERNEL)
    assert "pack_post_stock_symmetry_state" in kern
    assert "int(g) + h > int(ceiling)" in kern
    sched = _text(ROOT / "src" / "spider" / "whole_game_epoch_scheduler.py")
    assert "identity_fn=pack_whole_game_identity" in sched
    script = _text(SCRIPT)
    if script:
        assert script.find("EVAL canonical") > script.find("search_focused_endgame")
    opening = opening_state()
    ident = pack_whole_game_identity(opening)
    assert ident == pack_state(opening) or bool(opening.stock)
    four = unpack_state(pack_state(opening))
    assert stock_empty_assembly_h(opening, 0) == stock_empty_assembly_h(four, 0) == 0


def test_proof_prune_ceiling_190_and_tt_unchanged():
    src = inspect.getsource(search_focused_endgame)
    assert "cost_ceiling=SPLICED_G - 1" in src
    assert SPLICED_G - 1 == 190
    opening = opening_state()
    packed = pack_state(opening)
    ident = pack_whole_game_identity(opening)
    kr = run_search(
        [{"g": 0, "ordered_digest": packed.hex(), "whole_game_identity": ident.hex(), "ident": ident.hex()}],
        limits=SearchLimits(max_unique=2, time_limit_s=0.05, cost_ceiling=190),
        identity_fn=pack_whole_game_identity,
        lower_bound_fn=stock_empty_assembly_h,
    )
    assert kr.unique >= 1
    assert pack_state(opening) == packed
    assert pack_whole_game_identity(opening) == ident


def test_script_and_splice_helpers():
    assert splice_candidate([("deal",)], [(0, 1, 1)]) == [("deal",), (0, 1, 1)]
    src = inspect.getsource(build_verified_191)
    assert "reconstruct_v073_prefix" in src
    assert "replay_spliced" in src
    assert "verify_suffix_sequence" in src
    script = _text(SCRIPT)
    assert "incumbent_by_rows={}" in _text(MOD)
    assert "4925153_canonical.moves" in script
    assert script.find("EVAL canonical") > script.find("SEARCH focused")


def test_improved_candidate_replay_if_present():
    path = V074_BEST_MOVES if V074_BEST_MOVES.exists() else BEST
    if not path.exists() and V074_MOVES.exists():
        path = V074_MOVES
    if not path.exists():
        return
    opening = opening_state()
    actions = parse_moves_file(path)
    end = opening.clone()
    g = replay_actions(end, actions)
    assert g <= 190
    assert g == AUTONOMOUS_INCUMBENT_MW == 187
    assert end.is_solved()
    assert sum(1 for a in actions if is_deal(a)) == 5
    assert not end.stock
    assert all(c.is_empty() for c in end.columns)
    v = verify_autonomous_192(opening)
    assert v["ok"] and v["g"] == 187
    assert INCUMBENT_MOVES.name == "4925153_autonomous_v0_74.moves"
    assert replay_actions(opening.clone(), parse_moves_file(V074_MOVES)) == 187
