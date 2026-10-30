"""Decision-field admission and JOIN continuity.

The boards are fixtures. Nothing here searches a deal, scores a second
stage, or changes the legal move generator. Card literals stay in this
file. The reusable module does not contain them.
"""

from __future__ import annotations

import inspect
import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.cards import Card
from spider.dependency_options import (
    AncestorClaim,
    SourceCostClaim,
    build_option,
    kernel_lower_bound,
    rebuild_obligations,
    select_dependency_portfolio,
    verify_source_cost_claim,
)
from spider.engine import Column, SpiderState
from spider.human_strategy.evaluation import admissible_remaining
from spider.research_actions import apply_action, step_cost, tableau_actions


def _cards(text: str):
    return [Card.parse(token) for token in text.split() if token]


def _state(face_up, stock="ad", face_down=None) -> SpiderState:
    columns = []
    for index in range(10):
        down = ""
        if face_down is not None and index in face_down:
            down = face_down[index]
        columns.append(Column(_cards(down), _cards(face_up[index])))
    return SpiderState(columns, _cards(stock), [])


def _size_one(column4="ks") -> SpiderState:
    return _state(
        {
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
        },
        face_down={0: "4d"},
    )


def _named(state, actions, source_g=0):
    obligations = rebuild_obligations(state)
    options = tuple(
        build_option(
            state,
            (action,),
            source_g=source_g,
            structural_name=name,
            obligations=obligations,
        )
        for name, action in actions
    )
    return obligations, options


def _reject(option, obligations, **changes):
    forged = replace(option, **changes)
    pick = select_dependency_portfolio((forged,), obligations, limit=1)
    assert pick.chosen == ()
    assert pick.obligations_status == "not_applied"
    assert pick.source_g_provenance == "unestablished"
    assert pick.absolute_g_used_for_proof is False


def test_the_reusable_module_has_no_fixture_cards():
    source = Path(build_option.__code__.co_filename).read_text(encoding="utf-8")
    assert "8c" not in source
    assert "9c" not in source
    assert "run_search" not in source
    assert "discover_macros" not in source


def test_forged_selector_fields_are_rejected_one_at_a_time():
    source = _size_one()
    obligations, (preserve, spend) = _named(
        source,
        (("preserve-receiver", (0, 2, 1)), ("spend-only-receiver", (3, 1, 1))),
    )
    assert preserve.enables == ("join:c:8:col0", "reveal:col0:depth0")
    assert spend.broken_dependencies == ("join:c:8:col0", "reveal:col0:depth0")
    assert spend.blocks == spend.broken_dependencies
    assert spend.dependency_penalty == 4
    assert spend.target_bonds == 1
    assert preserve.target_bonds == 0
    assert preserve.source_g_provenance == "unestablished"

    _reject(preserve, obligations, enables=())
    _reject(preserve, obligations, blocks=("join:c:8:col0",))
    _reject(preserve, obligations, broken_dependencies=("join:c:8:col0",))
    _reject(preserve, obligations, dependency_penalty=4)
    _reject(preserve, obligations, target_bonds=5)
    _reject(preserve, obligations, outstanding_obligations=())
    _reject(preserve, obligations, unresolved_dependencies=("join:c:8:col0",))
    _reject(preserve, obligations, source_g_provenance="opening_verified")
    _reject(spend, obligations, enables=("join:c:8:col0", "reveal:col0:depth0"))
    _reject(spend, obligations, blocks=())
    _reject(spend, obligations, broken_dependencies=())
    _reject(spend, obligations, dependency_penalty=0)
    _reject(spend, obligations, target_bonds=0)
    _reject(spend, obligations, unresolved_dependencies=())

    genuine = select_dependency_portfolio((preserve, spend), obligations, limit=2)
    assert genuine.chosen[0].option_id == "preserve-receiver"
    assert genuine.chosen[1].option_id == "spend-only-receiver"
    assert genuine.source_g_provenance == "unestablished"
    assert genuine.absolute_g_used_for_proof is False
    assert "dependency_penalty" not in inspect.signature(kernel_lower_bound).parameters
    assert kernel_lower_bound(source, 5) == admissible_remaining(source)


def test_forged_spend_cannot_outrank_the_preserver():
    source = _size_one()
    obligations, (preserve, spend) = _named(
        source,
        (("preserve-receiver", (0, 2, 1)), ("spend-only-receiver", (3, 1, 1))),
    )
    forged = replace(
        spend,
        enables=("join:c:8:col0", "reveal:col0:depth0"),
        blocks=(),
        broken_dependencies=(),
        dependency_penalty=0,
        target_bonds=99,
        unresolved_dependencies=(),
    )
    pick = select_dependency_portfolio((forged, preserve), obligations, limit=2)
    assert pick.chosen == (preserve,)
    assert pick.chosen[0].option_id == "preserve-receiver"
    assert pick.chosen[0].actions == ((0, 2, 1),)
    assert pick.chosen[0].dependency_penalty == 0
    assert pick.chosen[0].target_bonds == 0
    assert "spend-only-receiver" not in {item.option_id for item in pick.chosen}
    assert set(tableau_actions(source)) == {(0, 2, 1), (3, 1, 1)}


def test_incremental_g_is_not_an_opening_cost():
    source = _size_one()
    obligations, (preserve, spend) = _named(
        source,
        (("preserve-receiver", (0, 2, 1)), ("spend-only-receiver", (3, 1, 1))),
    )
    shifted = replace(
        preserve,
        source_g=preserve.source_g + 5,
        target_g=preserve.target_g + 5,
        f_target=preserve.f_target + 5,
    )
    assert shifted.source_pack == preserve.source_pack
    assert shifted.target_g - shifted.source_g == shifted.cost == 1
    pair = select_dependency_portfolio((shifted, spend), obligations, limit=2)
    assert [item.option_id for item in pair.chosen] == [
        "preserve-receiver",
        "spend-only-receiver",
    ]
    assert pair.chosen[0].source_g == 5
    assert pair.chosen[0].source_g_provenance == "unestablished"
    assert pair.source_g_provenance == "unestablished"
    assert pair.absolute_g_used_for_proof is False
    assert pair.rejected_source_cost_claims == 0

    false_opening = SourceCostClaim(preserve.source_pack, (), preserve.source_pack, 5)
    assert verify_source_cost_claim(false_opening) is False
    refused = select_dependency_portfolio(
        (shifted,),
        obligations,
        limit=1,
        source_cost_claims=(false_opening,),
    )
    assert refused.chosen[0] is shifted
    assert refused.source_g_provenance == "unestablished"
    assert refused.rejected_source_cost_claims == 1
    assert refused.absolute_g_used_for_proof is False


def test_a_source_cost_claim_is_not_an_ancestor_claim():
    source = _size_one()
    obligations, (preserve, _spend) = _named(
        source,
        (("preserve-receiver", (0, 2, 1)), ("spend-only-receiver", (3, 1, 1))),
    )
    opening = SourceCostClaim(preserve.source_pack, (), preserve.source_pack, 0)
    assert verify_source_cost_claim(opening) is True
    declared = select_dependency_portfolio(
        (preserve,),
        obligations,
        limit=1,
        source_cost_claims=(opening,),
    )
    assert declared.chosen[0].option_id == "preserve-receiver"
    assert declared.chosen[0].source_g_provenance == "unestablished"
    assert declared.source_g_provenance == "opening_verified"
    assert declared.absolute_g_used_for_proof is False
    assert declared.ancestor_status == "not_established"

    continued = source.clone()
    assert apply_action(continued, (0, 2, 1)) == 1
    continued_obligations = rebuild_obligations(continued)
    later = build_option(
        continued,
        ((0, 1, 1),),
        source_g=1,
        structural_name="after-preserve",
        obligations=continued_obligations,
    )
    assert later.cost == 1
    assert later.target_g == 2
    ancestor = AncestorClaim(preserve.source_pack, ((0, 2, 1),), later.source_pack, "later")
    relative = select_dependency_portfolio(
        (later,),
        continued_obligations,
        limit=1,
        ancestor_claims=(ancestor,),
    )
    assert relative.ancestor_status == "one_verified"
    assert relative.source_g_provenance == "checkpoint_relative"
    assert relative.absolute_g_used_for_proof is False

    tied = SourceCostClaim(preserve.source_pack, ((0, 2, 1),), later.source_pack, 1)
    assert verify_source_cost_claim(tied) is True
    absolute = select_dependency_portfolio(
        (later,),
        continued_obligations,
        limit=1,
        ancestor_claims=(ancestor,),
        source_cost_claims=(tied,),
    )
    assert absolute.source_g_provenance == "opening_verified"
    assert absolute.absolute_g_used_for_proof is False
    assert absolute.chosen[0].actions == ((0, 1, 1),)

    overstated = replace(
        later,
        source_g=6,
        target_g=later.target_g + 5,
        f_target=later.f_target + 5,
    )
    mismatched = SourceCostClaim(preserve.source_pack, ((0, 2, 1),), later.source_pack, 6)
    assert verify_source_cost_claim(mismatched) is False
    still = select_dependency_portfolio(
        (overstated,),
        continued_obligations,
        limit=1,
        ancestor_claims=(ancestor,),
        source_cost_claims=(mismatched,),
    )
    assert still.chosen[0].source_g == 6
    assert still.chosen[0].target_g - still.chosen[0].source_g == 1
    assert still.source_g_provenance == "checkpoint_relative"
    assert still.rejected_source_cost_claims == 1
    assert still.absolute_g_used_for_proof is False
    assert overstated.source_pack == later.source_pack


def test_zero_cost_relocation_keeps_the_join():
    source = _state(
        {
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
    )
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
    assert "join:c:8:col0" not in option.broken_dependencies
    assert "join:c:8:col0" not in option.blocks
    assert "join:c:8:col0" not in option.unresolved_dependencies
    assert option.dependency_penalty == 0
    assert option.unresolved_dependencies == ()
    after = source.clone()
    assert apply_action(after, (0, 2, 1)) == 0
    after_ids = {node.obligation_id for node in rebuild_obligations(after)}
    assert "join:c:8:col0" not in after_ids
    assert "join:c:8:col2" in after_ids
    assert after.can_move(2, 1, 1) is True
    assert (0, 2, 1) in tableau_actions(source)
    admitted = select_dependency_portfolio((option,), obligations, limit=1)
    assert admitted.chosen[0].cost == 0
    assert admitted.chosen[0].dependency_penalty == 0


def test_size_one_spend_still_breaks_and_size_two_does_not():
    source = _size_one()
    obligations, (preserve, spend) = _named(
        source,
        (("preserve-receiver", (0, 2, 1)), ("spend-only-receiver", (3, 1, 1))),
    )
    assert spend.broken_dependencies == ("join:c:8:col0", "reveal:col0:depth0")
    assert spend.blocks == spend.broken_dependencies
    assert spend.enables == ()
    assert spend.dependency_penalty == 4
    assert "join:c:8:col3" in spend.unresolved_dependencies
    assert "join:c:8:col3" not in spend.broken_dependencies
    assert "join:c:8:col3" not in spend.enables
    assert preserve.enables == ("join:c:8:col0", "reveal:col0:depth0")
    assert preserve.broken_dependencies == ()
    assert preserve.dependency_penalty == 0
    size_one = select_dependency_portfolio((preserve, spend), obligations, limit=2)
    assert size_one.chosen[0].option_id == "preserve-receiver"

    source_or = _size_one("9c")
    obligations_or, (preserve_or, spend_or) = _named(
        source_or,
        (("preserve-receiver", (0, 2, 1)), ("spend-only-receiver", (3, 1, 1))),
    )
    assert spend_or.broken_dependencies == ()
    assert spend_or.blocks == ()
    assert spend_or.dependency_penalty == 0
    assert "join:c:8:col0" not in spend_or.broken_dependencies
    assert "join:c:8:col0" not in spend_or.unresolved_dependencies
    assert set(tableau_actions(source_or)) == {(0, 2, 1), (3, 1, 1), (3, 4, 1)}
    size_two = select_dependency_portfolio((preserve_or, spend_or), obligations_or, limit=2)
    assert size_two.chosen[0].option_id == "spend-only-receiver"
    assert size_two.chosen[0].cost == 1
    assert size_two.chosen[0].target_bonds == 1
    assert size_two.chosen[0].dependency_penalty == 0


def test_held_out_relocation_uses_another_suit_and_column():
    face_up = {
        0: "kh",
        1: "ks",
        2: "kd",
        3: "",
        4: "kc",
        5: "6d",
        6: "kh",
        7: "ks",
        8: "7d",
        9: "kc",
    }
    source = _state(face_up)
    obligations = rebuild_obligations(source)
    option = build_option(
        source,
        ((5, 3, 1),),
        source_g=0,
        structural_name="park-six",
        obligations=obligations,
    )
    assert step_cost(source, (5, 3, 1)) == 0
    assert option.cost == 0
    assert "join:d:6:col5" not in option.broken_dependencies
    assert "join:d:6:col5" not in option.blocks
    assert "join:d:6:col5" not in option.unresolved_dependencies
    assert option.dependency_penalty == 0
    after = source.clone()
    assert apply_action(after, (5, 3, 1)) == 0
    after_ids = {node.obligation_id for node in rebuild_obligations(after)}
    assert "join:d:6:col5" not in after_ids
    assert "join:d:6:col3" in after_ids
    assert after.can_move(3, 8, 1) is True
    assert (5, 3, 1) in tableau_actions(source)


def test_duplicate_rank_follows_the_moved_copy():
    source = _state(
        {
            0: "8c",
            1: "9c 8c",
            2: "",
            3: "8c",
            4: "9c",
            5: "kh",
            6: "ks",
            7: "kd",
            8: "kc",
            9: "kh",
        }
    )
    obligations = rebuild_obligations(source)
    option = build_option(
        source,
        ((0, 2, 1),),
        source_g=0,
        structural_name="move-one-copy",
        obligations=obligations,
    )
    assert option.cost == 0
    assert "join:c:8:col0" not in option.broken_dependencies
    assert "join:c:8:col0" not in option.unresolved_dependencies
    assert "join:c:8:col0" not in option.enables
    assert "join:c:8:col3" not in option.broken_dependencies
    assert "join:c:8:col3" not in option.unresolved_dependencies
    assert "join:c:8:col3" not in option.enables
    assert option.dependency_penalty == 0
    after = source.clone()
    assert apply_action(after, (0, 2, 1)) == 0
    assert [(card.rank, card.suit) for card in after.columns[2].face_up] == [(8, "c")]
    assert [(card.rank, card.suit) for card in after.columns[3].face_up] == [(8, "c")]
    assert [(card.rank, card.suit) for card in after.columns[1].face_up] == [(9, "c"), (8, "c")]
    after_ids = {node.obligation_id for node in rebuild_obligations(after)}
    assert "join:c:8:col2" in after_ids
    assert "join:c:8:col3" in after_ids
    assert "join:c:8:col0" not in after_ids
    assert after.can_move(2, 4, 1) is True
    assert after.can_move(3, 4, 1) is True


def test_split_merge_and_removal_stay_unresolved():
    split_source = _state(
        {
            0: "9s 8s",
            1: "9h",
            2: "",
            3: "kd",
            4: "kc",
            5: "ks",
            6: "kh",
            7: "kd",
            8: "kc",
            9: "ks",
        }
    )
    split_obligations = rebuild_obligations(split_source)
    split = build_option(
        split_source,
        ((0, 1, 1),),
        source_g=0,
        structural_name="split-run",
        obligations=split_obligations,
    )
    assert step_cost(split_source, (0, 1, 1)) == 1
    assert "join:s:9:col0" in split.unresolved_dependencies
    assert "join:s:9:col0" not in split.broken_dependencies
    assert "join:s:9:col0" not in split.enables
    assert "join:s:9:col0" not in split.blocks

    removed_source = _state(
        {
            0: "kc qc jc 10c 9c 8c 7c 6c 5c 4c 3c 2c",
            1: "ac",
            2: "kh",
            3: "ks",
            4: "kd",
            5: "kh",
            6: "ks",
            7: "kd",
            8: "kc",
            9: "kh",
        }
    )
    removed = build_option(
        removed_source,
        ((1, 0, 1),),
        source_g=0,
        structural_name="complete-clubs",
        obligations=rebuild_obligations(removed_source),
    )
    finished = removed_source.clone()
    assert apply_action(finished, (1, 0, 1)) == 1
    assert len(finished.foundations) == 1
    assert "join:c:13:col0" in removed.unresolved_dependencies
    assert "join:c:1:col1" in removed.unresolved_dependencies
    assert "join:c:13:col0" not in removed.broken_dependencies
    assert "join:c:1:col1" not in removed.broken_dependencies
    assert "join:c:13:col0" not in removed.enables
    assert "join:c:1:col1" not in removed.enables
    assert removed.dependency_penalty == 0
