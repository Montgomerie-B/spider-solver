"""Offline audit of option provenance, ancestry, and published routes.

The synthetic boards are fixtures. The 172 and 185 files are replayed.
Nothing here starts a search or rebuilds the eight-root portfolio.
"""

from __future__ import annotations

import inspect
import subprocess
import sys
from dataclasses import replace
from functools import lru_cache
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.cards import Card
from spider.dependency_options import (
    AncestorClaim,
    build_option,
    kernel_lower_bound,
    obligations_match_state,
    outcome_signature,
    prefer_option_actions,
    rebuild_obligations,
    select_dependency_portfolio,
)
from spider.dependency_options_audit import audit_verified_routes
from spider.engine import Column, SpiderState
from spider.human_strategy.evaluation import admissible_remaining
from spider.packed_state import (
    pack_post_stock_symmetry_state,
    pack_state,
    pack_whole_game_identity,
    permute_tableau_columns,
)
from spider.research_actions import apply_action, step_cost, tableau_actions
from spider.rules import deal_cost

CANONICAL_SHA256 = "18338A08576AD24E9AF1F4BA2E7DB3E28768788DD511E823193B1937F3FEEF33"
AUTONOMOUS_SHA256 = "B19C56E957AC2666298A80118D54FF7FCA6C8114ED7D27590E2E98A017D4FB73"


def _cards(text: str):
    return [Card.parse(token) for token in text.split() if token]


def _columns(face_up):
    return [Column([], _cards(face_up[index])) for index in range(10)]


def _board(column4: str = "ks") -> SpiderState:
    face_up = {
        0: "8c 3h",
        1: "9c",
        2: "4d",
        3: "kd 8c",
        4: column4,
        5: "kh",
        6: "kd",
        7: "kc",
        8: "ks",
        9: "kh",
    }
    columns = []
    for index in range(10):
        down = _cards("4d") if index == 0 else []
        columns.append(Column(down, _cards(face_up[index])))
    return SpiderState(columns, _cards("ad"), [])


def _named(state, source_g=0):
    obligations = rebuild_obligations(state)
    preserve = build_option(
        state,
        ((0, 2, 1),),
        source_g=source_g,
        structural_name="preserve-receiver",
        obligations=obligations,
    )
    spend = build_option(
        state,
        ((3, 1, 1),),
        source_g=source_g,
        structural_name="spend-only-receiver",
        obligations=obligations,
    )
    return obligations, preserve, spend


def _reject(option, obligations, **changes):
    pick = select_dependency_portfolio((replace(option, **changes),), obligations, limit=1)
    assert pick.chosen == ()
    assert pick.obligations_status == "not_applied"
    assert pick.diverse_ancestor_available is False


def test_replay_checks_cost_g_h_and_f_independently():
    source = _board()
    obligations, preserve, spend = _named(source)
    pick = select_dependency_portfolio((preserve, spend), obligations, limit=2)
    assert pick.chosen[0].option_id == "preserve-receiver"
    assert pick.obligations_status == "matched"

    _reject(preserve, obligations, cost=preserve.cost + 1)
    _reject(preserve, obligations, target_g=preserve.target_g + 1)
    _reject(preserve, obligations, h_target=preserve.h_target + 1)
    _reject(preserve, obligations, f_target=preserve.f_target + 1)
    _reject(
        preserve,
        obligations,
        h_target=preserve.h_target + 3,
        f_target=preserve.target_g + preserve.h_target + 3,
    )
    _reject(preserve, obligations, finishability_proof=True)
    _reject(preserve, obligations, replay_ok=False)

    assert spend.dependency_penalty == 4
    assert spend.f_target == spend.target_g + spend.h_target
    assert spend.f_target != spend.target_g + spend.h_target + spend.dependency_penalty
    assert kernel_lower_bound(source, 0) == admissible_remaining(source)
    assert "dependency_penalty" not in inspect.signature(kernel_lower_bound).parameters
    assert "g" in inspect.signature(kernel_lower_bound).parameters


def test_a_foreign_obligation_graph_does_not_change_the_winner():
    source = _board("9c")
    obligations, preserve, spend = _named(source)
    foreign = rebuild_obligations(_board())
    assert obligations_match_state(source, obligations)
    assert not obligations_match_state(source, foreign)
    assert {node.obligation_id for node in foreign} != {node.obligation_id for node in obligations}

    matched = select_dependency_portfolio((preserve, spend), obligations, limit=2)
    refused = select_dependency_portfolio((preserve, spend), foreign, limit=2)
    assert matched.obligations_status == "matched"
    assert matched.chosen[0].option_id == "spend-only-receiver"
    assert refused.obligations_status == "refused"
    assert refused.protected_ids == ()
    assert refused.chosen[0].option_id == "spend-only-receiver"
    assert refused.receive_protection == "not_present"

    mutated = tuple(
        replace(node, requires_any=(("not-a-landing",), ("also-not",)))
        if node.obligation_id == "join:c:8:col0"
        else node
        for node in rebuild_obligations(_board())
    )
    assert {node.obligation_id for node in mutated} == {
        node.obligation_id for node in rebuild_obligations(_board())
    }
    assert not obligations_match_state(_board(), mutated)
    size_one = _board()
    size_obligations, size_preserve, size_spend = _named(size_one)
    structural = select_dependency_portfolio(
        (size_preserve, size_spend), mutated, limit=2
    )
    assert structural.obligations_status == "refused"
    assert structural.protected_ids == ()


def test_source_signatures_tie_while_outcome_signatures_differ():
    source = _board()
    obligations, preserve, spend = _named(source)
    pick = select_dependency_portfolio((preserve, spend), obligations, limit=2)
    assert pick.source_signatures[0] == pick.source_signatures[1]
    assert pick.outcome_signatures[0] != pick.outcome_signatures[1]
    assert pick.outcome_signatures == (
        outcome_signature(pick.chosen[0]),
        outcome_signature(pick.chosen[1]),
    )
    assert pick.chosen[0].source_pack == pick.chosen[1].source_pack
    assert pick.chosen[0].target_pack != pick.chosen[1].target_pack


def test_distinct_packs_are_not_distinct_ancestors_without_a_verified_prefix():
    opening = _board()
    obligations, opening_option, _spend = _named(opening)
    continued = opening.clone()
    apply_action(continued, (0, 2, 1))
    continued_obligations = rebuild_obligations(continued)
    continued_option = build_option(
        continued,
        ((0, 1, 1),),
        source_g=1,
        structural_name="after-preserve",
        obligations=continued_obligations,
    )
    assert opening_option.source_pack != continued_option.source_pack
    assert len(opening.stock) % 10 != 0

    stock_board = _receive_board()
    assert len(stock_board.stock) % 10 == 0
    stock_obligations, _stock_spend, stock_deal = _receive_options(stock_board)
    other_stock = _zero_cost_board()
    other_stock = SpiderState(
        other_stock.columns,
        _cards("as 5s 5h 5d 5c 4s 4h 4d 4c 3s"),
        [],
    )
    assert len(other_stock.stock) % 10 == 0
    other_stock_option = build_option(
        other_stock,
        ((0, 2, 1),),
        source_g=0,
        structural_name="same-epoch-other-pack",
        obligations=rebuild_obligations(other_stock),
    )
    assert stock_deal.source_pack != other_stock_option.source_pack
    unmarked = select_dependency_portfolio(
        (stock_deal, other_stock_option),
        stock_obligations,
        limit=2,
    )
    assert unmarked.diverse_ancestor_available is False
    assert unmarked.ancestor_status == "not_established"
    assert unmarked.verified_checkpoint_packs == ()

    checkpoint = opening_option.source_pack
    claims = (
        AncestorClaim(checkpoint, (), opening_option.source_pack, "opening"),
        AncestorClaim(checkpoint, ((0, 2, 1),), continued_option.source_pack, "later"),
        AncestorClaim(checkpoint, ((0, 1, 1),), opening_option.source_pack, "illegal"),
    )
    shared = select_dependency_portfolio(
        (opening_option, continued_option),
        obligations,
        limit=2,
        ancestor_claims=claims,
    )
    assert shared.diverse_ancestor_available is False
    assert shared.ancestor_status == "one_verified"
    assert shared.verified_checkpoint_packs == (checkpoint,)
    assert shared.rejected_ancestor_claims == 1

    other = _zero_cost_board()
    other_obligations = rebuild_obligations(other)
    other_option = build_option(
        other,
        ((0, 2, 1),),
        source_g=0,
        structural_name="zero-cost-park",
        obligations=other_obligations,
    )
    positive = select_dependency_portfolio(
        (opening_option, other_option),
        obligations,
        limit=2,
        ancestor_claims=(
            AncestorClaim(opening_option.source_pack, (), opening_option.source_pack, "a"),
            AncestorClaim(other_option.source_pack, (), other_option.source_pack, "b"),
        ),
    )
    assert opening_option.source_pack != other_option.source_pack
    assert positive.diverse_ancestor_available is True
    assert positive.ancestor_status == "diverse_verified"
    assert positive.verified_checkpoint_packs == tuple(
        sorted((opening_option.source_pack, other_option.source_pack))
    )
    assert positive.rejected_ancestor_claims == 0


def test_receive_singletons_are_not_protected():
    source = _receive_board()
    obligations, spend, deal = _receive_options(source)
    receive_ids = tuple(
        node.obligation_id for node in obligations if node.kind == "RECEIVE" and node.requires_any
    )
    assert receive_ids
    assert all(len(node.requires_any[0]) == 1 for node in obligations if node.obligation_id in receive_ids)
    pick = select_dependency_portfolio((spend, deal), obligations, limit=2)
    assert pick.obligations_status == "matched"
    assert pick.receive_protection == "unsupported"
    assert pick.unsupported_receive_ids == tuple(sorted(receive_ids))
    assert all(not item.startswith("receive:") for item in pick.protected_ids)
    assert pick.protected_ids
    for option in (spend, deal):
        assert all(not item.startswith("receive:") for item in option.blocks)
        assert all(not item.startswith("receive:") for item in option.enables)
        assert all(not item.startswith("receive:") for item in option.broken_dependencies)


def test_zero_cost_transfer_stays_legal_and_a_deal_costs_one():
    source = _zero_cost_board()
    obligations = rebuild_obligations(source)
    option = build_option(
        source,
        ((0, 2, 1),),
        source_g=0,
        structural_name="park-eight",
        obligations=obligations,
    )
    assert step_cost(source, (0, 2, 1)) == 0
    assert option.cost == 0
    assert option.target_g == 0
    assert option.f_target == option.h_target
    assert (0, 2, 1) in tableau_actions(source)
    admitted = select_dependency_portfolio((option,), obligations, limit=1)
    assert admitted.chosen[0].cost == 0
    _reject(option, obligations, cost=1)
    _reject(option, obligations, cost=1, target_g=1)

    dealing = _receive_board()
    deal_obligations, _spend, deal = _receive_options(dealing)
    assert deal.actions == (("deal",),)
    assert deal.cost == deal_cost() == 1
    assert deal.target_g == deal.source_g + 1
    assert deal.f_target == deal.target_g + deal.h_target
    _reject(deal, deal_obligations, cost=0)


def test_moving_an_interval_changes_its_column_bound_join_id():
    source = _zero_cost_board()
    obligations = rebuild_obligations(source)
    option = build_option(
        source,
        ((0, 2, 1),),
        source_g=0,
        structural_name="park-eight",
        obligations=obligations,
    )
    after = source.clone()
    assert apply_action(after, (0, 2, 1)) == 0
    source_ids = {node.obligation_id for node in obligations}
    after_ids = {node.obligation_id for node in rebuild_obligations(after)}
    assert "join:c:8:col0" in source_ids
    assert "join:c:8:col0" not in after_ids
    assert any(item.startswith("join:c:8:col2") for item in after_ids)
    assert after.can_move(2, 1, 1) is True
    # The column id changes. The intact run still has its receiver, so the
    # source JOIN is not a break. docs/dependency_contract_continuity_pr3.md.
    assert "join:c:8:col0" not in option.broken_dependencies
    assert option.blocks == ()
    assert option.dependency_penalty == 0


def test_size_two_preserves_feasibility_without_minimising_two_stage_cost():
    source = _board("9c")
    obligations, preserve, spend = _named(source)
    pick = select_dependency_portfolio((preserve, spend), obligations, limit=2)
    assert pick.chosen[0].option_id == "spend-only-receiver"
    assert preserve.cost == 1
    assert spend.cost == 1

    after_preserve = source.clone()
    assert apply_action(after_preserve, (0, 2, 1)) == 1
    assert apply_action(after_preserve, (0, 1, 1)) == 1
    preserve_then_reveal = 2

    after_spend = source.clone()
    assert apply_action(after_spend, (3, 1, 1)) == 1
    assert apply_action(after_spend, (0, 2, 1)) == 1
    assert apply_action(after_spend, (0, 4, 1)) == 1
    spend_then_reveal = 3

    assert preserve_then_reveal == 2
    assert spend_then_reveal == 3
    assert pick.chosen[0].cost != spend_then_reveal
    assert kernel_lower_bound(source, 0) == admissible_remaining(source)
    assert kernel_lower_bound(after_spend, 3) == admissible_remaining(after_spend)


def test_preference_is_a_permutation_and_stock_identity_stays_ordered():
    source = _board()
    _obligations, preserve, _spend = _named(source)
    generated = tableau_actions(source)
    preferred = prefer_option_actions(source, generated, preserve)
    assert set(preferred) == set(tuple(action) for action in generated)
    assert len(preferred) == len(generated)
    bogus = replace(preserve, actions=((9, 8, 1),))
    untouched = prefer_option_actions(source, generated, bogus)
    assert untouched == [tuple(action) for action in generated]
    assert (9, 8, 1) not in untouched

    assert source.stock
    assert pack_whole_game_identity(source) == pack_state(source)
    swapped = permute_tableau_columns(source, (1, 0, 2, 3, 4, 5, 6, 7, 8, 9))
    assert pack_state(source) != pack_state(swapped)
    assert pack_whole_game_identity(swapped) == pack_state(swapped)
    with pytest.raises(ValueError, match="stock"):
        pack_post_stock_symmetry_state(source)

    stock_ten = _receive_board()
    assert len(stock_ten.stock) == 10
    assert pack_whole_game_identity(stock_ten) == pack_state(stock_ten)


def test_the_audit_module_does_not_name_a_search():
    source = Path(audit_verified_routes.__code__.co_filename).read_text(encoding="utf-8")
    assert "run_search" not in source
    assert "discover_macros" not in source


@lru_cache(maxsize=1)
def _audit():
    return audit_verified_routes(ROOT)


def test_verified_routes_and_published_roots_replay_offline():
    audit = _audit()
    assert audit.canonical_sha256 == CANONICAL_SHA256
    assert audit.autonomous_sha256 == AUTONOMOUS_SHA256
    assert audit.canonical_actions == 174
    assert audit.autonomous_actions == 189
    assert audit.canonical_deals[4] == 151
    assert audit.canonical_terminal.g == 172
    assert audit.autonomous_terminal.g == 185
    assert audit.canonical_terminal.foundations == 8
    assert audit.autonomous_terminal.foundations == 8
    assert audit.canonical_terminal.stock == 0
    assert audit.autonomous_terminal.stock == 0
    assert audit.canonical_solved is True
    assert audit.autonomous_solved is True
    assert audit.canonical_terminal.f == 172 + audit.canonical_terminal.h
    assert audit.autonomous_terminal.f == 185 + audit.autonomous_terminal.h

    prepared = audit.checkpoint_140
    assert prepared.actions_applied == 140
    assert prepared.g == 139
    assert prepared.stock == 10
    assert prepared.empty_columns == 2
    assert prepared.two_spaces is True
    assert prepared.foundations == 2
    assert prepared.face_down == 3
    assert prepared.f == prepared.g + prepared.h

    before_fifth = audit.checkpoint_151
    assert before_fifth.g == 149
    assert before_fifth.stock == 10
    posted = audit.checkpoint_152
    assert posted.g == 150
    assert posted.h == 18
    assert posted.f == 168
    assert posted.stock == 0

    assert [item.stock for item in audit.contrasts] == [50, 40, 30, 20, 10, 0]
    assert audit.contrasts[0].same_pack is True
    assert audit.contrasts[0].same_signature is True
    for item in audit.contrasts[1:]:
        assert item.same_pack is False
        assert item.canonical.f == item.canonical.g + item.canonical.h
        assert item.autonomous.f == item.autonomous.g + item.autonomous.h

    assert len(audit.roots) == 8
    assert audit.shared_macro_source_signature is True
    assert audit.distinct_macro_target_packs == 8
    for root in audit.roots:
        assert root.replay_ok is True
        assert root.matches_published is True
        assert root.g == root.published_g
        assert root.h == root.published_h
        assert root.f == root.published_f
        assert root.face_down == 3
        assert root.stock == 0
        assert "5h 4h 3h" in root.heart_runs
        assert root.option_cost == root.g - 139
        assert root.option_target_g == root.g
        assert root.option_h == root.h
        assert root.option_f == root.f
        assert root.source_pack == prepared.pack_hex
        assert root.target_pack != root.source_pack

    terminal = audit.root0_terminal
    assert terminal.replay_ok is True
    assert terminal.discrepancy == ""
    assert terminal.g == 154
    assert terminal.h == 17
    assert terminal.f == 171
    assert terminal.face_down == 2
    assert terminal.stock == 0
    assert terminal.foundations == 2
    assert tuple(terminal.foundation_suits) == ("s", "d")
    assert terminal.bonds == 55
    assert terminal.empty_columns == 0
    assert terminal.legal_tableau == 22
    assert "kh qh jh 10h 9h 8h 7h" in terminal.heart_runs

    assert audit.macro_ancestry.status == "one_verified"
    assert audit.macro_ancestry.diverse is False
    assert audit.macro_ancestry.verified_checkpoints == 1
    assert audit.macro_ancestry.distinct_source_packs == 1
    assert audit.macro_ancestry_without_claims.status == "not_established"
    assert audit.macro_ancestry_without_claims.diverse is False

    assert audit.post_deal_ancestry.status == "one_verified"
    assert audit.post_deal_ancestry.diverse is False
    assert audit.post_deal_ancestry.verified_checkpoints == 1
    assert audit.post_deal_ancestry.distinct_source_packs == 8
    assert audit.post_deal_ancestry.rejected_claims == 0
    assert audit.post_deal_ancestry_without_claims.status == "not_established"
    assert audit.post_deal_ancestry_without_claims.diverse is False
    assert audit.post_deal_ancestry_without_claims.distinct_source_packs == 8

    assert audit.route_pair_ancestry.status == "one_verified"
    assert audit.route_pair_ancestry.diverse is False
    assert audit.route_pair_ancestry.distinct_source_packs == 2
    assert audit.route_pair_ancestry.verified_checkpoints == 1
    assert audit.route_pair_depths[0] == 140

    named = (
        "artifacts/stock_boundary_v0_133/results.json",
        "artifacts/purposeful_macro_v0_134/results.json",
        "artifacts/origin_fair_v0_135/results.json",
        "artifacts/post_deal_milestone_v0_136/results.json",
    )
    assert audit.portfolio_files_opened == ()
    assert set(audit.portfolio_files_present) | set(audit.portfolio_files_missing) == set(named)
    assert audit.portfolio_files_present == tuple(path for path in named if (ROOT / path).is_file())
    assert "artifacts/" in (ROOT / ".gitignore").read_text(encoding="utf-8")
    tracked = subprocess.run(
        ["git", "ls-files", "--", *named],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert tracked.stdout.strip() == ""
    assert "20,000" in audit.v132_citation
    assert "does not rerun" in audit.v132_citation


def _zero_cost_board() -> SpiderState:
    face_up = {
        0: "8c",
        1: "9c",
        2: "",
        3: "kd",
        4: "kc",
        5: "ks",
        6: "kh",
        7: "kd",
        8: "kc",
        9: "ks",
    }
    return SpiderState(_columns(face_up), _cards("ad"), [])


def _receive_board() -> SpiderState:
    columns = [
        Column([], _cards("2h")),
        Column([], _cards("9c")),
        Column([], _cards("kd")),
        Column([], _cards("kd 8c")),
        Column([], _cards("kc")),
        Column([], _cards("ks")),
        Column([], _cards("kh")),
        Column([], _cards("kd")),
        Column([], _cards("kc")),
        Column([], _cards("ks")),
    ]
    stock = _cards("as 5s 5h 5d 5c 4s 4h 4d 4c 3s")
    return SpiderState(columns, stock, [])


def _receive_options(state):
    obligations = rebuild_obligations(state)
    spend = build_option(
        state,
        ((3, 1, 1),),
        source_g=0,
        structural_name="spend-club",
        obligations=obligations,
    )
    deal = build_option(
        state,
        (("deal",),),
        source_g=0,
        structural_name="deal-row",
        obligations=obligations,
    )
    return obligations, spend, deal
