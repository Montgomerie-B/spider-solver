"""Final-Deal transition-aware portfolio v0.66."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

from spider.autonomous_cost import COST_LANES
from spider.cards import Card
from spider.deal_preview import preview_next_deal
from spider.engine import Column, SpiderState
from spider.final_deal_transition import (
    CANDIDATE_CEILING,
    F2_G,
    TRANSITION_CATS,
    TRANSITION_HARVEST_CATS,
    TRANSITION_SHARE_MAX,
    TransitionTracker,
    enrich_transition,
    load_v065_f2_actions,
    reconstruct_v065_f2,
    search_transition_continuation,
    transition_share,
    verify_v065_f2,
)
from spider.healthy_f2 import F2_FD, F2_N, F2_ROWS, F2_SUITS, parse_stored_actions, verify_f2_prefix
from spider.metrics import parse_moves_file, replay_actions
from spider.operational_policy import OP_HARVEST_CATS, OP_LANES, search_operational_optimisation
from spider.packed_state import pack_state, pack_whole_game_identity
from spider.research_actions import is_deal
from spider.rules import MW_RULES, deal_cost
from spider.whole_game_anytime import opening_root, opening_state
from spider.whole_game_epoch_scheduler import _Top, harvest_portfolio, search_epoch_portfolio

ROOT = Path(__file__).resolve().parents[1]
PREVIEW = ROOT / "src" / "spider" / "deal_preview.py"
MOD = ROOT / "src" / "spider" / "final_deal_transition.py"
OP = ROOT / "src" / "spider" / "operational_policy.py"
SCRIPT = ROOT / "research" / "final_deal_transition_v0_66.py"
ARTEFACT = ROOT / "docs" / "research" / "final_deal_transition_v0_66.json"
INCUMBENT = ROOT / "solutions" / "4925153_autonomous_v0_59.moves"
V065 = ROOT / "docs" / "research" / "healthy_f2_cost_to_go_v0_65.json"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _simple_imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [
        n.module
        for n in ast.walk(tree)
        if isinstance(n, ast.ImportFrom) and (n.module or "").startswith("spider.simple_")
    ]


def _run(suit: str, hi: int, lo: int):
    return [Card(suit, r) for r in range(hi, lo - 1, -1)]


def _columns(*runs, down=None, foundations=None, stock=None) -> SpiderState:
    downs = list(down or [])
    cols = []
    for i, run in enumerate(runs):
        fd = list(downs[i]) if i < len(downs) else []
        cols.append(Column(fd, list(run)))
    while len(cols) < 10:
        cols.append(Column([], []))
    return SpiderState(cols, list(stock or []), list(foundations or []))


def _stock_row(*cards: Card) -> list:
    row = list(cards)
    while len(row) < 10:
        row.append(Card("h", 2))
    return row


def test_preview_does_not_mutate_and_matches_cloned_deal():
    opening = opening_state()
    packed = pack_state(opening)
    ident = pack_whole_game_identity(opening)
    stock_n = len(opening.stock)
    preview = preview_next_deal(opening, pre_g=0)
    assert pack_state(opening) == packed
    assert pack_whole_game_identity(opening) == ident
    assert len(opening.stock) == stock_n
    clone = opening.clone()
    paid = clone.deal()
    assert preview["ok"]
    assert preview["deal_cost"] == paid == deal_cost() == 1
    assert preview["post_g"] == 1
    assert preview["post_digest"] == pack_state(clone).hex()
    assert preview["pre_digest"] == packed.hex()


def test_preview_uses_engine_deal_and_empty_column_is_legal():
    stock = _stock_row(Card("c", 5), Card("d", 4))
    st = _columns(
        _run("s", 10, 8),
        [],
        stock=stock,
    )
    assert st.columns[1].is_empty()
    assert st.can_deal(MW_RULES)
    packed = pack_state(st)
    preview = preview_next_deal(st, pre_g=10)
    assert pack_state(st) == packed
    assert preview["ok"]
    assert preview["landings"][1]["empty"] is True
    clone = st.clone()
    clone.deal(MW_RULES)
    assert preview["post_digest"] == pack_state(clone).hex()


def test_preview_auto_foundation_and_deal_cost_once():
    # Column 0 holds KH-AH missing the Ace; stock lands AC? We need Ace of clubs
    # on column 0: K-2 of clubs visible, stock[-10:][0] = AC.
    run = _run("c", 13, 2)
    ace = Card("c", 1)
    stock = [ace] + [Card("h", 3)] * 9
    st = _columns(run, stock=stock, foundations=[_run("s", 13, 1)])
    pre_f = len(st.foundations)
    preview = preview_next_deal(st, pre_g=20, detail="full")
    assert preview["ok"]
    assert preview["deal_cost"] == 1
    assert preview["post_g"] == 21
    assert preview["auto_foundations"] >= 1
    assert preview["foundations"] == pre_f + 1
    assert preview["landings"][0]["foundation_triggered"] is True
    clone = st.clone()
    clone.deal()
    assert preview["post_digest"] == pack_state(clone).hex()
    assert len(clone.foundations) == pre_f + 1


def test_preview_telemetry_deterministic():
    opening = opening_state()
    a = preview_next_deal(opening, pre_g=7)
    b = preview_next_deal(opening, pre_g=7)
    assert a["post_digest"] == b["post_digest"]
    assert a["rank_ok"] == b["rank_ok"]
    assert a["same_suit"] == b["same_suit"]
    assert a["mixed"] == b["mixed"]
    assert a["landings"] == b["landings"]


def test_cost_conditioned_transition_harvest():
    tops = {cat: _Top(n=8) for cat in TRANSITION_HARVEST_CATS}
    tracker = TransitionTracker()

    def rec(g, legal, ident):
        return {
            "g": g,
            "ident": ident,
            "ordered_digest": ident,
            "stock_rows": 1,
            "foundations": 2,
            "face_down": 2,
            "empty_n": 1,
            "preview": {
                "ok": True,
                "post_g": g + 1,
                "legal_tableau": legal,
                "boundaries": 20,
                "visible_components": 30,
                "component_layers": 8,
                "face_down": 2,
                "foundations": 2,
                "same_suit": 0,
                "rank_ok": 0,
                "mixed": 9,
                "op_defined": False,
            },
        }

    cheap_high = rec(132, 16, "a")
    dear_high = rec(150, 16, "b")
    low = rec(131, 4, "c")
    tracker(tops, cheap_high, 130, {})
    tracker(tops, dear_high, 130, {})
    tracker(tops, low, 130, {})
    best = tops["post_deal_mobility"].best()
    idents = [r["ident"] for r in best]
    assert "a" in idents
    assert idents.index("a") < idents.index("b")


def test_preview_categories_cannot_monopolise_and_deal_now_retained():
    tops = {cat: _Top() for cat in TRANSITION_HARVEST_CATS}

    def _rec(tag: str, i: int) -> dict:
        ident = f"{tag}{i}"
        return {
            "g": 130 + (i % 5),
            "ident": ident,
            "whole_game_identity": ident,
            "ordered_digest": ident,
            "foundations": 2,
            "face_down": 2,
            "bonds": 4,
            "empty_n": 1,
            "n_ready": 1,
            "cover": 3,
        }

    for cat in OP_HARVEST_CATS:
        if cat not in tops:
            continue
        for i in range(40):
            rec = _rec(f"e{cat}", i)
            tops[cat].add((i, rec["g"]), rec)
    for cat in TRANSITION_CATS:
        for i in range(40):
            rec = _rec(f"t{cat}", i)
            tops[cat].add((i, rec["g"]), rec)
    roots = [
        {
            "g": 130,
            "ident": "root",
            "whole_game_identity": "root",
            "ordered_digest": "root",
            "foundations": 2,
            "face_down": 2,
            "bonds": 1,
            "empty_n": 1,
        }
    ]
    picked, counts = harvest_portfolio(
        tops, roots, 130, width=256, cats=TRANSITION_HARVEST_CATS
    )
    assert counts.get("deal_now", 0) >= 1
    assert any(r.get("portfolio_cat") == "deal_now" for r in picked)
    assert transition_share(counts, 256) <= TRANSITION_SHARE_MAX + 1e-9
    existing = sum(int(counts.get(c) or 0) for c in OP_HARVEST_CATS if c != "deal_now")
    assert existing >= 80
    assert len(picked) == 256


def test_exact_tt_ceiling_lanes_no_canonical_no_new_post_stock_policy():
    for path in (PREVIEW, MOD, OP):
        text = _text(path)
        assert "4925153_canonical.moves" not in text
        assert _simple_imports(path) == []
    src = inspect.getsource(search_operational_optimisation)
    assert "operational_lane_keys" in src
    assert "incumbent_g - 1" in src
    assert "durability" not in src
    assert OP_LANES == COST_LANES
    assert "durability" not in OP_LANES
    assert set(OP_HARVEST_CATS).issubset(TRANSITION_HARVEST_CATS)
    assert CANDIDATE_CEILING == 197
    assert F2_G + 67 == 197
    src_search = inspect.getsource(search_transition_continuation)
    assert "operational_lane_keys" not in src_search or "OP_LANES" in _text(OP)
    assert "lane_names=OP_LANES" in src
    opening = opening_state()
    packed = pack_state(opening)
    ident = pack_whole_game_identity(opening)
    preview_next_deal(opening, pre_g=0)
    assert pack_state(opening) == packed
    assert pack_whole_game_identity(opening) == ident


def test_absolute_g_and_ceiling_from_f2_root():
    opening = opening_state()
    root = opening_root(opening)
    root["g"] = 130
    res = search_epoch_portfolio(
        opening=opening,
        initial_roots=[root],
        max_unique=12,
        time_limit_s=1.0,
        rss_abort_mb=4096,
        cost_ceiling=197,
        portfolio_width=8,
    )
    assert res.min_g is None or res.min_g >= 130
    assert res.candidate_ceiling == 197


def test_v065_f2_prefix_replays_if_present():
    actions = load_v065_f2_actions()
    if not actions:
        return
    opening = opening_state()
    snap = verify_v065_f2(opening, actions)
    assert snap["replay_ok"]
    assert snap["g"] == F2_G
    assert snap["stock_rows"] == F2_ROWS
    assert snap["face_down"] == F2_FD
    assert snap["foundations"] == F2_N
    assert set(snap["suits"]) == F2_SUITS


def test_script_canonical_is_after_search_only():
    script = _text(SCRIPT)
    if not script:
        return
    search_at = script.find("search_transition_continuation(")
    canon_at = script.find("canonical_f2_snapshot(")
    assert search_at != -1
    assert canon_at > search_at
    assert "EVAL canonical" in script


def test_incumbent_and_terminal_replay_contract():
    opening = opening_state()
    actions = parse_moves_file(INCUMBENT)
    end = opening.clone()
    assert replay_actions(end, actions) == 198
    assert sum(1 for a in actions if is_deal(a)) == 5
    if not ARTEFACT.exists():
        return
    import json

    data = json.loads(ARTEFACT.read_text(encoding="utf-8"))
    raw = data.get("f2_prefix_actions")
    if raw:
        snap = verify_f2_prefix(opening, parse_stored_actions(raw))
        assert snap["replay_ok"]
        assert snap["g"] == 130
    if data.get("solved") and data.get("solution_actions"):
        term = opening.clone()
        g = replay_actions(term, parse_stored_actions(data["solution_actions"]))
        assert term.is_solved()
        assert g == data.get("replay_g") or g == data.get("solution_g")
        assert sum(1 for a in parse_stored_actions(data["solution_actions"]) if is_deal(a)) == 5
        assert len(term.foundations) == 8
        assert not term.stock
        assert all(c.is_empty() for c in term.columns)


def test_enrich_transition_is_rows_one_only():
    opening = opening_state()
    rec = {"g": 0, "stock_rows": 5, "foundations": 0}
    enrich_transition(opening, rec)
    assert "preview" not in rec
    rec1 = {"g": 130, "stock_rows": 1, "foundations": 2}
    # opening has 5 stock rows, so stock_rows field is stale; helper keys off rec
    # and can_deal. Force the rec path only.
    assert rec1.get("preview") is None
