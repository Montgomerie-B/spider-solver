"""Counterfactual continuation tests for v0.106.

The long searches are not run here. A tiny budget only checks that an
unresolved run is not reported as a cheaper solution.
"""

from __future__ import annotations

import json
import subprocess
import sys
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.cards import Card
from spider.deal import load_deal
from spider.engine import Column, SpiderState
from spider.counterfactual.boundaries import (
    checkpoint_from_actions,
    disorder_without_readiness,
    parse_canonical,
    structurally_promising,
)
from spider.counterfactual.budget import resolve_profile
from spider.counterfactual.classify import classify_stop
from spider.counterfactual.experiment import (
    BASELINE_MW,
    CounterfactualError,
    _child_row,
    interpret,
    one_ply,
    rank_tableau_moves,
    reconstruct_roots,
    reference_horizon,
    run_policy_search,
    validate_route,
)
from spider.counterfactual.report import build_answers
from spider.counterfactual.runner import survivor_sort_key
from spider.counterfactual.suffixes import index_route, retain_cheapest, validate_splice
from spider.counterfactual.policies import (
    POLICIES,
    focus_suit_boundaries,
    policy_actions,
    rank_discontinuities,
    same_suit_bonds,
    soft_lane_key,
    suit_boundaries,
)
from spider.counterfactual.report import render_report
from spider.forensics.structure import experimental_debt_score
from spider.metrics import parse_moves_file, replay_actions_detailed
from spider.packed_state import pack_state, unpack_state
from spider.research_actions import all_legal_actions, apply_action
from spider.search_kernel import SearchLimits, run_search

DEAL = ROOT / "deals" / "4925153.txt"
CANON = ROOT / "solutions" / "4925153_canonical.moves"
AUTO = ROOT / "solutions" / "4925153_autonomous_185.moves"
TOOL = ROOT / "tools" / "counterfactual_continuations.py"
PACKAGE = ROOT / "src" / "spider" / "counterfactual"


def _card(text: str) -> Card:
    return Card.parse(text)


def _column(down, up) -> Column:
    return Column([_card(token) for token in down], [_card(token) for token in up])


def _state(columns, stock) -> SpiderState:
    while len(columns) < 10:
        columns.append(_column([], ["KS"]))
    return SpiderState(columns[:10], [_card(token) for token in stock])


def _focus_state() -> SpiderState:
    columns = [
        _column([], ["QH"]),
        _column([], ["AS"]),
        _column([], ["KS"]),
        _column([], ["KH"]),
        _column([], ["2S"]),
        _column([], ["QS"]),
        _column([], ["KS"]),
        _column([], ["KS"]),
        _column([], ["KS"]),
        _column([], ["KS"]),
    ]
    stock = ["5C"] * 10
    return _state(columns, stock)


@lru_cache(maxsize=1)
def _roots():
    return reconstruct_roots(DEAL, parse_moves_file(AUTO), focus_column=4)


def test_both_routes_replay_to_the_known_corrected_totals():
    human = validate_route(DEAL, CANON, expected_mw=172, expected_actions=174)
    machine = validate_route(DEAL, AUTO, expected_mw=185, expected_actions=189)
    assert human["solved"] and machine["solved"]
    assert human["foundations"] == 8 and machine["foundations"] == 8
    assert human["stock_remaining"] == 0 and machine["stock_remaining"] == 0
    assert human["stock_deals"] == 5 and machine["stock_deals"] == 5


def test_action_25_root_matches_the_reported_column_4_move():
    root = _roots()["A"]
    effect = root["original_action_effect"]
    assert root["action_index"] == 25
    assert root["original_action"] == "move 6 4 1"
    assert effect["internal"] == [6, 4, 1]
    assert root["deals_completed"] == 0
    assert root["phase"] == "pre-SD1"
    assert root["prefix_count"] == 24
    assert root["cumulative_g"] + root["suffix_remaining_mw"] == BASELINE_MW
    assert effect["cost"] == 1
    assert effect["suit_boundaries_before"] == 0
    assert effect["suit_boundaries_after"] == 1
    assert effect["disorder_before"] == 0
    assert effect["disorder_after"] == 1
    assert effect["bonds_delta"] == 0
    assert effect["face_down_delta"] == 0
    assert len(root["snapshot"]["layout"]) == 10
    assert len(root["snapshot"]["experimental_debt_vector"]) == 10
    assert root["snapshot"]["readiness_n_ready"] is not None
    assert "#" in root["snapshot"]["layout"][3]["face_up"][0]


def test_post_sd3_root_is_g_74_and_the_pre_deal_g_is_73():
    root = _roots()["B"]
    reference = reference_horizon(DEAL, parse_moves_file(CANON), 3, focus_index=3)
    assert root["deals_completed"] == 3
    assert root["phase"] == "post-SD3"
    assert root["g_before_this_deal"] == 73
    assert root["this_deal_cost"] == 1
    assert root["cumulative_g"] == 74
    assert root["cumulative_g"] + root["suffix_remaining_mw"] == BASELINE_MW
    assert root["suffix_remaining_mw"] == 111
    assert reference["g_before_deal"] == 100
    assert reference["cumulative_g"] == 101
    assert reference["cumulative_g"] - root["cumulative_g"] == 27
    assert root["original_action"] is None
    assert root["snapshot"]["stock_rows_remaining"] == 2


def test_wrong_action_25_refuses_before_search():
    actions = parse_moves_file(AUTO)
    actions[24] = ("deal",)
    try:
        reconstruct_roots(DEAL, actions, focus_column=4)
    except CounterfactualError as exc:
        assert exc.code == 1
        assert "move 6 4 1" in str(exc)
    else:
        raise AssertionError("a different action 25 was accepted")


def test_c1_hides_only_focus_boundary_increases_until_the_next_deal():
    state = _focus_state()
    store = pack_state(state)
    stock_len = len(state.stock)
    before = state.enumerate_legal_actions()
    allowed = policy_actions(
        "hard",
        state,
        focus_index=3,
        root_stock_len=stock_len,
        root_store=store,
        forbidden=None,
    )
    after = state.enumerate_legal_actions()
    assert before == after
    assert (5, 3, 1) in before
    assert (5, 3, 1) not in allowed
    assert (0, 3, 1) in allowed
    assert (1, 4, 1) in allowed
    assert ("deal",) in allowed
    lifted = policy_actions(
        "hard",
        state,
        focus_index=3,
        root_stock_len=stock_len + 10,
        root_store=store,
        forbidden=None,
    )
    assert (5, 3, 1) in lifted
    assert focus_suit_boundaries(state, 3) == suit_boundaries(state.columns[3].face_up)


def test_suppress_one_drops_only_the_root_action():
    state = _focus_state()
    store = pack_state(state)
    forbidden = (5, 3, 1)
    allowed = policy_actions(
        "suppress_one",
        state,
        focus_index=3,
        root_stock_len=len(state.stock),
        root_store=store,
        forbidden=forbidden,
    )
    assert forbidden not in allowed
    assert (0, 3, 1) in allowed
    elsewhere = policy_actions(
        "suppress_one",
        state,
        focus_index=3,
        root_stock_len=len(state.stock),
        root_store=b"not-the-root",
        forbidden=forbidden,
    )
    assert forbidden in elsewhere
    assert ("deal",) in allowed


def test_real_root_a_policies_hide_the_recorded_move_only_where_specified():
    root = _roots()["A"]
    control = one_ply(root, focus_index=3, kind="control")
    hard = one_ply(root, focus_index=3, kind="hard")
    soft = one_ply(root, focus_index=3, kind="soft")
    suppressed = one_ply(root, focus_index=3, kind="suppress_one")
    assert control["hidden_count"] == 0 and control["original_allowed"] is True
    assert soft["hidden_count"] == 0 and soft["original_allowed"] is True
    assert hard["original_allowed"] is False
    state = unpack_state(bytes.fromhex(root["ordered_digest"]))
    allowed = policy_actions(
        "hard",
        state,
        focus_index=3,
        root_stock_len=len(state.stock),
        root_store=bytes.fromhex(root["ordered_digest"]),
        forbidden=root["suffix_actions_internal"][0],
    )
    assert (5, 3, 1) in state.enumerate_legal_actions()
    assert (5, 3, 1) not in allowed
    assert suppressed["hidden_count"] == 1
    assert suppressed["hidden_sample"] == ["move 6 4 1"]
    screened = rank_tableau_moves(root, focus_index=3, kind="hard", rank_mode="construction")
    assert all(row["canonical"] != "move 6 4 1" for row in screened["rows"])
    assert all(row["canonical"] != "deal" for row in screened["rows"])
    assert screened["deal_legal"] is True


def test_soft_key_is_g_primary_and_is_not_the_debt_score():
    state = _focus_state()
    low = soft_lane_key(state, 4, 3)
    high = soft_lane_key(state, 9, 3)
    assert low[0] == 4 and high[0] == 9
    assert low < high
    assert len(low) == 4
    assert low == (
        4,
        suit_boundaries(state.columns[3].face_up),
        rank_discontinuities(state.columns[3].face_up),
        -same_suit_bonds(state),
    )
    debt = experimental_debt_score(
        {
            "suit_boundaries": 4,
            "rank_discontinuities": 4,
            "buried_face_up": 4,
            "component_layers": 4,
            "immobile_exposed": 4,
        }
    )
    assert debt not in low
    assert {policy["name"] for policy in POLICIES} == {"C0", "C1", "C2", "A-suppress"}


def test_tiny_budget_stays_unresolved_and_does_not_claim_a_cheaper_line():
    root = _roots()["B"]
    policy = next(policy for policy in POLICIES if policy["name"] == "C0")
    result = run_policy_search(
        root,
        policy,
        deal_path=DEAL,
        ceiling=184,
        time_limit_s=0.15,
        max_unique=40,
        focus_index=3,
    )
    assert result["status"] in {"TIME_LIMIT", "NODE_LIMIT", "MEMORY_LIMIT"}
    assert result["continuation"] == []
    assert result["replay"] is None
    assert result["terminal_g"] is None
    lines = interpret(
        [
            {
                "name": "B",
                "searches": [result],
                "candidate_screens": [],
            }
        ]
    )
    assert lines[0].startswith("No policy produced")
    assert "cheaper than 185" in lines[0]


def test_report_quotes_the_budget_result_without_a_false_improvement():
    document = {
        "spec_note": "ended at the local experimental bound",
        "reference": {
            "mobilityware_moves": 172,
            "actions": 174,
            "solved": True,
            "foundations": 8,
            "stock_remaining": 0,
            "stock_deals": 5,
        },
        "baseline": {
            "mobilityware_moves": 185,
            "actions": 189,
            "solved": True,
            "foundations": 8,
            "stock_remaining": 0,
            "stock_deals": 5,
        },
        "local_ceiling": 184,
        "ceiling_rule": "local experimental bound",
        "policies": [{"name": "C0", "kind": "control", "summary": "Unmodified legal actions."}],
        "search": {
            "kernel": "spider.search_kernel.run_search",
            "root_worker": "same limits",
            "candidate_screen": "small set",
            "stock_empty_worker_reason": "stock remains",
            "time_limit_s": 8,
            "max_unique": 5000,
            "candidate_width": 3,
            "candidate_time_s": 5,
            "candidate_unique": 2500,
            "widen_passes_experiment_b": 2,
            "candidate_rank": "construction lane",
            "population": "Visited states are discarded.",
        },
        "experiments": [
            {
                "name": "B",
                "priority": "higher",
                "stock_horizon": {
                    "machine_g_before_deal": 73,
                    "machine_g_after_deal": 74,
                    "reference_g_before_deal": 100,
                    "reference_g_after_deal": 101,
                    "machine_ahead_by": 27,
                    "note": "not an ancestor",
                },
                "root": {
                    "title": "immediately after SD3",
                    "phase": "post-SD3",
                    "saved_when": "after this stock deal",
                    "action_index": 80,
                    "cumulative_g": 74,
                    "state_hash": "abc",
                    "focus_column": 4,
                    "focus_disorder": 7,
                    "focus_suit_boundaries": 4,
                    "focus_rank_discontinuities": 3,
                    "focus_experimental_debt": 20,
                    "suffix_count": 10,
                    "suffix_remaining_mw": 111,
                    "suffix_head": ["move 1 2 1"],
                    "g_before_this_deal": 73,
                    "this_deal_cost": 1,
                    "hypothesis": "downstream decisions",
                    "snapshot": {
                        "stock_rows_remaining": 2,
                        "foundations": 0,
                        "face_down": 10,
                        "experimental_debt_vector": [0, 0, 1],
                        "experimental_debt_sum": 1,
                        "readiness_n_ready": 0,
                        "layout": [{"column": 1, "face_down": ["AS#A"], "face_up": ["KH#A"]}],
                    },
                },
                "searches": [
                    {
                        "policy": "C0",
                        "status": "unresolved_time",
                        "stop_reason": "time limit",
                        "expanded": 3,
                        "unique": 4,
                        "elapsed_s": 0.1,
                        "terminal_g": None,
                        "probe": {"max_foundations": 0},
                    }
                ],
                "one_ply": {
                    "C0": {
                        "engine_legal": 2,
                        "policy_allowed": 2,
                        "hidden_count": 0,
                        "hidden_sample": [],
                        "original_allowed": True,
                        "original_rank": None,
                    }
                },
                "candidate_screens": [
                    {
                        "policy": "C0",
                        "rank_mode": "construction",
                        "enumerated_tableau": 2,
                        "unique_children": 2,
                        "retained": 1,
                        "note": "A cleaner child is not a cheaper solution.",
                        "batches": [
                            {
                                "results": [
                                    {
                                        "screen_rank": 1,
                                        "canonical": "move 1 2 1",
                                        "cost": 1,
                                        "suit_boundary_delta": 0,
                                        "bonds_delta": 1,
                                        "face_down_delta": 0,
                                        "search": {
                                            "status": "unresolved_unique",
                                            "stop_reason": "unique limit",
                                        },
                                    }
                                ]
                            }
                        ],
                    }
                ],
            }
        ],
        "interpretation": [
            "No policy produced a complete continuation whose independent replay is cheaper than 185."
        ],
        "limitations": ["A structurally cleaner column is supporting evidence only."],
    }
    text = render_report(document)
    assert "cheaper than 185" in text
    assert "supporting evidence only" in text
    assert "73" in text and "74" in text
    assert "238.5" not in text
    assert "local experimental bound" in text


def test_package_does_not_import_campaign_or_play_lab_writers():
    text = "\n".join(path.read_text(encoding="utf-8") for path in PACKAGE.rglob("*.py"))
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("import ") or stripped.startswith("from "):
            assert "play_session" not in stripped
            assert "campaign_autonomous" not in stripped
            assert "production_ceiling" not in stripped
    diff = subprocess.check_output(
        [
            "git",
            "diff",
            "--name-only",
            "HEAD",
            "--",
            "src/spider/engine.py",
            "src/spider/rules.py",
            "solutions/4925153_canonical.moves",
            "solutions/4925153_autonomous_185.moves",
        ],
        cwd=ROOT,
        text=True,
    )
    assert diff.strip() == ""


def test_cli_smoke_exits_zero_without_claiming_an_improvement(tmp_path):
    out = tmp_path / "out.json"
    report = tmp_path / "out.md"
    proc = subprocess.run(
        [
            sys.executable,
            str(TOOL),
            "--deal",
            str(DEAL),
            "--baseline",
            str(AUTO),
            "--reference",
            str(CANON),
            "--out",
            str(out),
            "--report",
            str(report),
            "--time-s",
            "0.05",
            "--max-unique",
            "30",
            "--widen",
            "1",
            "--candidate-width",
            "1",
            "--candidate-time-s",
            "0.05",
            "--candidate-unique",
            "20",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    document = json.loads(out.read_text(encoding="utf-8"))
    assert document["schema"] == "spider-counterfactual-continuations-0.106"
    assert document["experiments"][0]["name"] == "B"
    assert "cheaper than 185" in report.read_text(encoding="utf-8")
    assert "No policy produced" in proc.stdout


def test_cli_rejects_a_baseline_that_is_not_the_185(tmp_path):
    proc = subprocess.run(
        [
            sys.executable,
            str(TOOL),
            "--deal",
            str(DEAL),
            "--baseline",
            str(CANON),
            "--reference",
            str(AUTO),
            "--out",
            str(tmp_path / "no.json"),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert proc.returncode == 2


def test_prefixes_replay_to_the_recorded_roots_and_g():
    actions = parse_moves_file(AUTO)
    roots = _roots()
    assert roots["A"]["action_index"] == 25
    assert roots["A"]["cumulative_g"] == 24
    assert roots["B"]["cumulative_g"] == 74
    assert roots["B"]["g_before_this_deal"] == 73
    for name in ("A", "B"):
        root = roots[name]
        state = SpiderState.from_cards(list(load_deal(DEAL)))
        counters = replay_actions_detailed(state, root["prefix_actions_internal"])
        assert counters["mobilityware_moves"] == root["cumulative_g"]
        assert pack_state(state).hex() == root["ordered_digest"]
        assert root["cumulative_g"] + root["suffix_remaining_mw"] == 185
    fresh = SpiderState.from_cards(list(load_deal(DEAL)))
    full = replay_actions_detailed(fresh, actions)
    assert full["mobilityware_moves"] == 185
    assert fresh.is_solved()


def test_soft_policy_removes_no_legal_move_and_deal_order_is_unchanged():
    columns = [
        _column([], ["QH"]),
        _column([], ["AS"]),
        _column([], ["KS"]),
        _column([], ["KH"]),
        _column([], ["2S"]),
        _column([], ["QS"]),
        _column([], ["KS"]),
        _column([], ["KS"]),
        _column([], ["KS"]),
        _column([], ["KS"]),
    ]
    state = SpiderState(columns, [_card(token) for token in ["AH", "2H", "3H", "4H", "5H", "6H", "7H", "8H", "9H", "10H"]])
    store = pack_state(state)
    legal = all_legal_actions(state)
    soft = policy_actions(
        "soft", state, focus_index=3, root_stock_len=len(state.stock), root_store=store, forbidden=None
    )
    control = policy_actions(
        "control", state, focus_index=3, root_stock_len=len(state.stock), root_store=store, forbidden=None
    )
    assert soft == legal
    assert control == legal
    dealt = [(card.rank, card.suit) for card in state.stock[-10:]]
    left = state.clone()
    right = state.clone()
    assert apply_action(left, ("deal",)) == 1
    assert apply_action(right, ("deal",)) == 1
    assert pack_state(left) == pack_state(right)
    for index, card in enumerate(dealt):
        top = left.columns[index].face_up[-1]
        assert (top.rank, top.suit) == card


def test_zero_cost_whole_column_move_keeps_zero_in_the_child_account():
    columns = [
        _column([], ["KH", "QH"]),
        _column([], []),
        _column([], ["KS"]),
        _column([], ["KD"]),
        _column([], ["KC"]),
        _column([], ["JS"]),
        _column([], ["JD"]),
        _column([], ["JC"]),
        _column([], ["JH"]),
        _column([], ["10S"]),
    ]
    state = SpiderState(columns, [_card("5C")] * 10)
    whole = (0, 1, 2)
    partial = (0, 1, 1)
    assert apply_action(state.clone(), whole) == 0
    assert apply_action(state.clone(), partial) == 1
    whole_row = _child_row(state, whole, 3, 10)
    partial_row = _child_row(state, partial, 3, 10)
    assert whole_row["cost"] == 0
    assert whole_row["soft_key"][0] == 10
    assert partial_row["cost"] == 1
    digest = pack_state(state).hex()
    ranked = rank_tableau_moves(
        {
            "ordered_digest": digest,
            "cumulative_g": 10,
            "name": "Z",
            "suffix_actions_internal": [("deal",)],
        },
        focus_index=3,
        kind="control",
        rank_mode="construction",
    )
    zeros = [row for row in ranked["rows"] if row["canonical"] == "move 1 2 2"]
    assert len(zeros) == 1
    assert zeros[0]["cost"] == 0
    assert zeros[0]["child_g"] == 10


def test_exact_suffix_reuse_accepts_only_the_packed_state():
    actions = parse_moves_file(AUTO)
    catalog = index_route(DEAL, actions)
    opening = SpiderState.from_cards(list(load_deal(DEAL)))
    opening_store = pack_state(opening)
    whole = validate_splice(DEAL, [], actions, opening_store, 0)
    assert whole["ok"] is True
    assert whole["total_mw"] == 185
    assert whole["improves_on_baseline"] is False
    root = _roots()["A"]
    matched = validate_splice(
        DEAL,
        root["prefix_actions_internal"],
        root["suffix_actions_internal"],
        bytes.fromhex(root["ordered_digest"]),
        root["cumulative_g"],
    )
    assert matched["ok"] is True
    assert matched["total_mw"] == 185
    mismatched = validate_splice(
        DEAL,
        root["prefix_actions_internal"],
        root["suffix_actions_internal"],
        b"\x00" * 8,
        root["cumulative_g"],
    )
    assert mismatched["ok"] is False
    broken = list(root["suffix_actions_internal"])
    broken[0] = ("deal",) if broken[0] != ("deal",) else (0, 1, 1)
    rejected = validate_splice(
        DEAL,
        root["prefix_actions_internal"],
        broken,
        bytes.fromhex(root["ordered_digest"]),
        root["cumulative_g"],
    )
    assert rejected["ok"] is False


def test_duplicate_states_keep_the_cheapest_ancestry():
    store = b"same"
    best = retain_cheapest(
        [
            {"store": store, "g": 9, "name": "late"},
            {"store": store, "g": 4, "name": "early"},
            {"store": store, "g": 6, "name": "middle"},
            {"store": b"other", "g": 1, "name": "other"},
        ]
    )
    assert best[store]["name"] == "early"
    assert best[b"other"]["name"] == "other"


def test_time_limit_is_not_exhaustion_and_depth_limit_is_a_node_limit():
    assert classify_stop("time limit") == "TIME_LIMIT"
    assert classify_stop("experiment budget") == "TIME_LIMIT"
    assert classify_stop("complete") == "EXHAUSTED"
    assert classify_stop("unique limit") == "NODE_LIMIT"
    assert classify_stop("depth limit") == "NODE_LIMIT"
    assert classify_stop("rss abort") == "MEMORY_LIMIT"
    assert classify_stop("time limit") != classify_stop("complete")
    assert classify_stop("solved", {"ok": False}) == "INVALID"
    assert classify_stop("solved", {"ok": True}) == "SOLVED_VALID"
    state = _focus_state()
    digest = pack_state(state).hex()

    def once(max_depth, unique):
        limits = SearchLimits(
            max_unique=unique,
            time_limit_s=5.0,
            cost_ceiling=40,
            rss_abort_mb=8192,
            max_depth=max_depth,
        )
        return run_search(
            [{"g": 0, "ordered_digest": digest}],
            limits=limits,
            identity_fn=pack_state,
            store_fn=pack_state,
            unpack_fn=unpack_state,
            lane_names=("cost",),
            lane_key_fns=[lambda st, g: (int(g),)],
            is_terminal=lambda st: st.is_solved(),
            actions_fn=all_legal_actions,
            stop_on_first_terminal=True,
        )

    omitted = SearchLimits(max_unique=25, time_limit_s=5.0, cost_ceiling=40, rss_abort_mb=8192)
    explicit = SearchLimits(max_unique=25, time_limit_s=5.0, cost_ceiling=40, rss_abort_mb=8192, max_depth=None)
    assert omitted.max_depth is None and explicit.max_depth is None
    first = once(None, 25)
    second = once(None, 25)
    assert (first.unique, first.expanded, first.generated, first.stop_reason) == (
        second.unique,
        second.expanded,
        second.generated,
        second.stop_reason,
    )
    assert first.stop_reason == "unique limit"
    shallow = once(1, 500)
    assert shallow.expanded == 1
    assert shallow.hit_depth_limit is True
    assert shallow.depth_skips > 0
    assert shallow.stop_reason == "depth limit"
    blocked = run_search(
        [{"g": 0, "ordered_digest": digest}],
        limits=SearchLimits(max_unique=100, time_limit_s=5.0, cost_ceiling=0, rss_abort_mb=8192),
        identity_fn=pack_state,
        store_fn=pack_state,
        unpack_fn=unpack_state,
        lane_names=("cost",),
        lane_key_fns=[lambda st, g: (int(g),)],
        is_terminal=lambda st: st.is_solved(),
        actions_fn=all_legal_actions,
        stop_on_first_terminal=True,
    )
    assert blocked.stop_reason == "complete"
    assert classify_stop(blocked.stop_reason) == "EXHAUSTED"


def test_survivor_order_uses_the_185_hit_and_not_the_172_or_the_debt_score():
    plain = {"watch": {"max_bonds_seen": 3, "stock_boundaries": []}, "probe": {"max_foundations": 1, "g_at_max_foundations": 8}}
    with_reference = {
        "watch": {
            "max_bonds_seen": 3,
            "reference_suffix_hit": {"g": 1, "source": "reference-172"},
            "stock_boundaries": [{"immediate_deal": False, "face_down": 4, "focus_disorder": 1}],
        },
        "probe": {"max_foundations": 1, "g_at_max_foundations": 8},
    }
    with_baseline = {
        "watch": {
            "max_bonds_seen": 0,
            "baseline_suffix_hit": {"g": 3, "source": "baseline-185"},
            "stock_boundaries": [{"immediate_deal": False, "face_down": 20, "focus_disorder": 9}],
        },
        "probe": {"max_foundations": 0, "g_at_max_foundations": 99},
    }
    tidy = {
        "watch": {
            "max_bonds_seen": 3,
            "stock_boundaries": [{"immediate_deal": False, "face_down": 4, "focus_disorder": 0}],
        },
        "probe": {"max_foundations": 1, "g_at_max_foundations": 8},
    }
    assert survivor_sort_key(with_baseline) < survivor_sort_key(plain)
    assert survivor_sort_key(with_reference)[0] == survivor_sort_key(plain)[0]
    assert survivor_sort_key(tidy) < survivor_sort_key(with_reference)
    assert 36 not in survivor_sort_key(plain)


def test_checkpoint_from_the_experiment_root_counts_the_forced_move():
    state = _focus_state()
    dealt = checkpoint_from_actions(state, [("deal",)], label="earliest_stock_boundary", root_g=4, focus_index=3)
    assert dealt["cumulative_g"] == 5
    assert dealt["g_since_root"] == 1
    assert dealt["immediate_deal"] is True
    assert dealt["stock_cards"] == 0
    assert parse_canonical("deal") == ("deal",)
    assert parse_canonical("move 6 4 1") == (5, 3, 1)


def test_profile_deadline_skip_is_time_limit_and_workers_stay_one(tmp_path):
    from spider.counterfactual.runner import run_profile

    profile = resolve_profile(
        "screen",
        {
            "workers": 4,
            "total_time_s": 0.0,
            "deep_survivors": 0,
            "screen_time_s": 0.0,
            "root_time_s": 0.0,
        },
    )
    assert profile["workers_used"] == 1
    assert profile["workers_requested"] == 4
    document = run_profile(
        DEAL,
        AUTO,
        CANON,
        roots=["post-sd3"],
        policy="C0",
        profile_name="screen",
        overrides={
            "total_time_s": 0.0,
            "deep_survivors": 0,
            "screen_time_s": 0.0,
            "root_time_s": 0.0,
            "candidate_width": 2,
        },
        artifact_dir=tmp_path,
    )
    assert document["profile"]["workers_used"] == 1
    assert document["local_ceiling"] == 184
    assert document["mode"] == "profile"
    searches = document["experiments"][0]["searches"]
    assert searches
    assert all(item["status"] == "TIME_LIMIT" for item in searches)
    assert all(item["stop_reason"] == "experiment budget" for item in searches)
    assert all(item["expanded"] == 0 for item in searches)
    text = json.dumps(document)
    assert "production_ceiling" not in text
    assert "238.5" not in text


def test_lower_disorder_without_more_bonds_is_not_structural_readiness():
    original = {
        "focus_disorder": 7,
        "same_suit_bonds": 19,
        "rehandle_card_events": 31,
        "face_down": 2,
    }
    tidy_unready = {
        "immediate_deal": False,
        "focus_disorder": 3,
        "same_suit_bonds": 15,
        "rehandle_card_events": 0,
        "face_down": 19,
    }
    ready = {
        "immediate_deal": False,
        "focus_disorder": 4,
        "same_suit_bonds": 22,
        "rehandle_card_events": 4,
        "face_down": 2,
    }
    assert structurally_promising(ready, original)
    assert not structurally_promising(tidy_unready, original)
    assert disorder_without_readiness(tidy_unready, original)
    assert not structurally_promising(dict(ready, immediate_deal=True), original)
    assert not disorder_without_readiness(dict(tidy_unready, immediate_deal=True), original)


def test_profile_report_is_deterministic_and_keeps_budget_categories_distinct():
    document = {
        "mode": "profile",
        "spec_note": "Sections 7 through 17 govern this run.",
        "git": {"branch": "local/counterfactual-continuations-v0-106", "head": "abc"},
        "reference": {
            "mobilityware_moves": 172,
            "actions": 174,
            "moves_sha256": "ref",
            "solved": True,
            "foundations": 8,
            "stock_remaining": 0,
            "stock_deals": 5,
        },
        "baseline": {
            "mobilityware_moves": 185,
            "actions": 189,
            "moves_sha256": "base",
            "solved": True,
            "foundations": 8,
            "stock_remaining": 0,
            "stock_deals": 5,
        },
        "local_ceiling": 184,
        "ceiling_rule": "local experimental bound",
        "profile": {
            "name": "screen",
            "total_time_s": 1,
            "root_time_s": 1,
            "root_unique": 10,
            "screen_time_s": 1,
            "screen_unique": 10,
            "candidate_width": 1,
            "deep_survivors": 0,
            "deep_time_s": 0,
            "deep_unique": 10,
            "max_depth": 4,
            "rss_abort_mb": 2048,
        },
        "resource_settings": {
            "workers_requested": 1,
            "workers_used": 1,
            "workers_note": "One search runs at a time.",
            "search_width_used": 1,
            "search_width_note": "One best-g lane.",
            "elapsed_s": 1.0,
            "peak_rss_mb": 10,
        },
        "policies": [{"name": "C0", "kind": "control", "summary": "Unmodified legal actions."}],
        "experiments": [
            {
                "name": "B",
                "root_key": "post-sd3",
                "elapsed_s": 1.0,
                "budget_s": 1.0,
                "stock_horizon": {
                    "machine_g_before_deal": 73,
                    "machine_g_after_deal": 74,
                    "reference_g_before_deal": 100,
                    "reference_g_after_deal": 101,
                    "machine_ahead_by": 27,
                    "note": "not an ancestor",
                },
                "root": {
                    "title": "immediately after SD3",
                    "phase": "post-SD3",
                    "action_index": 78,
                    "cumulative_g": 74,
                    "state_hash": "abc",
                    "focus_column": 4,
                    "focus_disorder": 7,
                },
                "one_ply": {
                    "C0": {"policy_allowed": 13, "engine_legal": 13, "hidden_count": 0, "hidden_sample": []},
                    "C1": {
                        "policy_allowed": 11,
                        "engine_legal": 13,
                        "hidden_count": 2,
                        "hidden_sample": ["move 3 4 1"],
                    },
                    "C2": {"policy_allowed": 13, "engine_legal": 13, "hidden_count": 0, "hidden_sample": []},
                },
                "original_boundary": {
                    "kind": "original_suffix_next_stock_boundary",
                    "cumulative_g": 122,
                    "g_since_root": 48,
                    "action_count": 40,
                    "focus_disorder": 7,
                    "same_suit_bonds": 10,
                    "rehandle_card_events": 3,
                },
                "searches": [
                    {
                        "policy": "C0",
                        "role": "root_worker",
                        "status": "TIME_LIMIT",
                        "stop_reason": "time limit",
                        "terminal_g": None,
                        "improves_on_baseline": False,
                        "effort": {"elapsed_s": 0.2, "expanded": 10, "unique": 20},
                        "planned": {"max_unique": 20, "time_limit_s": 0.2},
                        "probe": {"max_foundations": 1, "min_focus_suit_boundaries_seen": 4},
                        "continuation": [],
                    }
                ],
                "candidate_screens": [],
                "deep_searches": [],
                "comparisons": [
                    {
                        "name": "reference-suffix",
                        "policy": "REFERENCE_SUFFIX",
                        "stage": "known-line",
                        "status": "REFERENCE_SUFFIX",
                        "stop_reason": "",
                        "effort": {},
                        "probe": {},
                        "boundary": {
                            "kind": "original_suffix_next_stock_boundary",
                            "label": "original",
                            "cumulative_g": 122,
                            "g_since_root": 48,
                            "face_down": 9,
                            "foundations": 1,
                            "same_suit_bonds": 10,
                            "empty_columns": 0,
                            "focus_disorder": 7,
                            "rehandle_card_events": 3,
                            "deal_legal": True,
                        },
                        "immediate_deal": False,
                        "debt_moved_to_column_7_or_8": False,
                        "terminal_g": None,
                    },
                    {
                        "name": "C0-root",
                        "policy": "C0",
                        "stage": "root",
                        "status": "TIME_LIMIT",
                        "stop_reason": "time limit",
                        "effort": {"elapsed_s": 0.2, "expanded": 10, "unique": 20},
                        "probe": {"max_foundations": 1},
                        "boundary": {"label": "earliest_stock_boundary", "immediate_deal": True, "cumulative_g": 75},
                        "immediate_deal": True,
                        "structurally_promising": False,
                        "debt_moved_to_column_7_or_8": False,
                        "terminal_g": None,
                    },
                ],
            }
        ],
        "interpretation": [
            "No policy produced a complete continuation whose independent replay is cheaper than 185."
        ],
        "limitations": ["TIME_LIMIT is not EXHAUSTED."],
    }
    answers = build_answers(document)
    document["answers"] = answers
    document["outcome"] = answers["outcome"]
    assert answers["outcome"] == "Inconclusive"
    first = render_report(document)
    second = render_report(document)
    assert first == second
    assert "No intervention produced a replay-verified solution at corrected MW 184 or below." in first
    assert "TIME_LIMIT is not EXHAUSTED." in first
    assert "Structurally promising, terminal value unresolved." not in first
    assert "238.5" not in first
    solved = json.loads(json.dumps(document))
    solved["experiments"][0]["searches"][0]["status"] = "SOLVED_VALID"
    solved["experiments"][0]["searches"][0]["improves_on_baseline"] = True
    solved["experiments"][0]["searches"][0]["terminal_g"] = 180
    solved["experiments"][0]["searches"][0]["improvement_vs_baseline"] = 5
    solved["experiments"][0]["searches"][0]["replay"] = {"ok": True, "total_mw": 180, "foundations": 8, "explicit_actions": 100}
    solved.pop("answers", None)
    positive = build_answers(solved)
    assert positive["outcome"] == "Positive"
    assert positive["questions"][7]["answer"].startswith("Yes.")
    mixed = json.loads(json.dumps(document))
    mixed["experiments"][0]["original_boundary"]["face_down"] = 9
    mixed["experiments"][0]["comparisons"][1]["immediate_deal"] = False
    mixed["experiments"][0]["comparisons"][1]["boundary"] = {
        "label": "best_scored_stock_boundary",
        "immediate_deal": False,
        "focus_disorder": 4,
        "same_suit_bonds": 14,
        "rehandle_card_events": 1,
        "face_down": 8,
        "cumulative_g": 90,
        "g_since_root": 16,
    }
    mixed.pop("answers", None)
    mixed_answers = build_answers(mixed)
    assert mixed_answers["outcome"] == "Mixed"
    mixed["answers"] = mixed_answers
    mixed["outcome"] = mixed_answers["outcome"]
    mixed_text = render_report(mixed)
    assert "Structurally promising, terminal value unresolved." in mixed_text
    misleading = json.loads(json.dumps(document))
    misleading["experiments"][0]["original_boundary"]["face_down"] = 9
    misleading["experiments"][0]["comparisons"][1]["immediate_deal"] = False
    misleading["experiments"][0]["comparisons"][1]["boundary"] = {
        "label": "best_scored_stock_boundary",
        "immediate_deal": False,
        "focus_disorder": 3,
        "same_suit_bonds": 8,
        "rehandle_card_events": 0,
        "face_down": 12,
        "cumulative_g": 80,
        "g_since_root": 6,
    }
    misleading.pop("answers", None)
    misleading_answers = build_answers(misleading)
    assert misleading_answers["outcome"] == "Inconclusive"
    assert misleading_answers["misleading"]
    assert "not structural readiness" in misleading_answers["misleading"][0]
    misleading["answers"] = misleading_answers
    misleading["outcome"] = misleading_answers["outcome"]
    misleading_text = render_report(misleading)
    assert "Structurally promising, terminal value unresolved." not in misleading_text
    assert "Where structural metrics misled" in misleading_text
    assert "not structural readiness" in misleading_text
    negative = json.loads(json.dumps(document))
    negative["experiments"][0]["searches"][0]["status"] = "EXHAUSTED"
    negative["experiments"][0]["comparisons"][1]["status"] = "EXHAUSTED"
    negative.pop("answers", None)
    assert build_answers(negative)["outcome"] == "Negative"


def test_profile_cli_honours_a_tiny_budget_and_does_not_launch_deep(tmp_path):
    out = tmp_path / "pilot.json"
    report = tmp_path / "pilot.md"
    proc = subprocess.run(
        [
            sys.executable,
            str(TOOL),
            "--deal",
            "4925153",
            "--root",
            "pre-action-25",
            "--policy",
            "C0",
            "--profile",
            "screen",
            "--out",
            str(out),
            "--report",
            str(report),
            "--total-time-s",
            "3",
            "--root-time-s",
            "0.2",
            "--screen-time-s",
            "0.15",
            "--root-unique",
            "40",
            "--screen-unique",
            "30",
            "--candidate-width",
            "1",
            "--deep-survivors",
            "0",
            "--max-depth",
            "8",
            "--workers",
            "4",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    document = json.loads(out.read_text(encoding="utf-8"))
    assert document["mode"] == "profile"
    assert document["profile"]["name"] == "screen"
    assert document["profile"]["workers_used"] == 1
    assert document["profile"]["workers_requested"] == 4
    assert document["experiments"][0]["name"] == "A"
    assert document["experiments"][0]["elapsed_s"] <= 5
    for search in document["experiments"][0]["searches"]:
        assert search["unique"] <= 40
        assert search["status"] in {
            "TIME_LIMIT",
            "NODE_LIMIT",
            "MEMORY_LIMIT",
            "EXHAUSTED",
            "SOLVED_VALID",
            "POLICY_BLOCKED",
            "INVALID",
            "ERROR",
        }
    text = report.read_text(encoding="utf-8")
    assert "No intervention produced a replay-verified solution at corrected MW 184 or below." in text
    assert "238.5" not in text
    assert "production_ceiling" not in text
    assert not (tmp_path / "moves").exists()
    assert "No policy produced" in proc.stdout

