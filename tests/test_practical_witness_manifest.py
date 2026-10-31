"""Lock the authenticated 4925153 roots and the predeclared play budgets.

These checks replay the canonical route only to authenticate starting
positions. They do not launch either policy arm.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.metrics import CANONICAL_MOBILITYWARE_MOVES
from spider.packed_state import pack_state
from spider.practical_witness_manifest import (
    ACCEPTED_CANONICAL_SHA256,
    ACCEPTED_DEAL_SHA256,
    CANONICAL_SHA256_CRLF,
    CANONICAL_SHA256_LF,
    DEAL_SHA256_CRLF,
    DEAL_SHA256_LF,
    EPISODE_ADDITIONAL_PAID,
    EPISODE_PLANNING_DECISIONS,
    EPISODE_PRIMITIVE_ACTIONS,
    EPISODE_PROBE_IDENTITIES,
    EPISODE_RSS_MB,
    EPISODE_WALL_S,
    PREPARATION_BUDGET_S,
    PROBE_COST_CEILING,
    PROBE_MAX_UNIQUE,
    PROBE_SLOTS,
    PROBE_TIME_LIMIT_S,
    REVEAL_GOAL,
    FrozenRoot,
    PlayManifest,
    ProvenanceBlocker,
    materialize_root,
    mode_order,
    policy_specification,
    prepare_manifest,
)
from spider.research_actions import apply_action, step_cost

_PACKS = {
    "opening": (
        "53504b310100003205013a2c36083502050115191b11282d05013b273a070c040501"
        "31122d1a16170401260d13343d04010c3c020305040118360a2a2804011214320406"
        "040123062b383904013123153b37131a2233193717013325290b1c22343c3d381b09"
        "320a2c1d1839030525140d0116072121112a1c2b0b29241d242609270835"
    ),
    "after-deal-1": (
        "53504b310100002802023a2c360b050515191b11282d0c2b2a290009282706151423"
        "323124030231122d1a1d0203260d13122400040c3b0a260004181716090008080706"
        "0504030227000b3d3c3b3a39383736353408000404230235131a2233193717013325"
        "290b1c22343c3d381b09320a2c1d1839030525140d0116072121112a1c2b"
    ),
    "after-deal-2": (
        "53504b310100001e0002060d050d15191b11282d0c0b0a0908070605040302010005"
        "2423323116030a31122d1a1d2c2b2a2928272607000327262100050d0c3b3a210008"
        "1817161514131211000636352423022a000c3d3c3b3a393837363534081c0002042b"
        "131a2233193717013325290b1c22343c3d381b09320a2c1d183903052514"
    ),
    "after-deal-3": (
        "53504b310101001400092d2c2b2a2928272632040415191b112827260a0006242332"
        "31162c030431122d1a1d1c1d00040807061800060d0c3b3a21390009181716151413"
        "121103000736352423022105000b3d3c3b3a393837363534250004042b2a14131a22"
        "33193717013325290b1c22343c3d381b090d0d0c0b0a090807060504030201"
    ),
}

# Corrected cost is below the command count on the warm roots because the
# authenticated prefix contains one zero-cost transfer. That cost is kept.
_EXPECTED = (
    ("opening", 0, 0, 0, 50, 44, 0),
    ("after-deal-1", 1, 52, 51, 40, 12, 0),
    ("after-deal-2", 2, 90, 89, 30, 8, 0),
    ("after-deal-3", 3, 102, 101, 20, 7, 1),
)


def test_preparation_authenticates_the_canonical_route():
    manifest = prepare_manifest()
    assert isinstance(manifest, PlayManifest)
    deal_bytes = (ROOT / "deals" / "4925153.txt").read_bytes()
    move_bytes = (ROOT / "solutions" / "4925153_canonical.moves").read_bytes()
    assert manifest.deal_sha256 == hashlib.sha256(deal_bytes).hexdigest().upper()
    assert manifest.canonical_sha256 == hashlib.sha256(move_bytes).hexdigest().upper()
    assert manifest.deal_sha256 in ACCEPTED_DEAL_SHA256
    assert manifest.canonical_sha256 in ACCEPTED_CANONICAL_SHA256
    assert manifest.canonical_mw == CANONICAL_MOBILITYWARE_MOVES == 172
    assert manifest.canonical_foundations == 8
    assert manifest.canonical_stock_remaining == 0
    assert manifest.canonical_tableau_empty is True
    assert manifest.preparation_s < PREPARATION_BUDGET_S
    assert manifest.suffix_discarded is True
    assert manifest.canonical_action_count == 174
    assert manifest.retained_action_count == 102
    assert manifest.retained_action_count < manifest.canonical_action_count


def test_four_roots_match_the_verified_deal_boundaries():
    roots = prepare_manifest().roots
    assert [root.root_id for root in roots] == [
        "opening",
        "after-deal-1",
        "after-deal-2",
        "after-deal-3",
    ]
    assert all(root.counts_as_evidence and root.duplicate_of is None for root in roots)
    packs = [root.pack_hex for root in roots]
    assert len(set(packs)) == 4
    for root, expected in zip(roots, _EXPECTED):
        root_id, ordinal, length, cost, stock, hidden, foundations = expected
        assert root.root_id == root_id
        assert root.deal_ordinal == ordinal
        assert len(root.prefix_actions) == length
        assert root.corrected_cost == cost
        assert root.stock == stock
        assert root.hidden == hidden
        assert root.foundations == foundations
        assert root.pack_hex == _PACKS[root_id]
        assert root.imported_prefix is (ordinal > 0)


def test_prefixes_replay_from_the_opening_and_keep_the_zero_cost():
    roots = prepare_manifest().roots
    for root in roots:
        state = materialize_root(root)
        assert pack_state(state).hex() == root.pack_hex
        again = materialize_root(root)
        assert pack_state(again).hex() == root.pack_hex
    opening = roots[0]
    assert opening.prefix_actions == ()
    assert opening.corrected_cost == 0
    for root in roots[1:]:
        assert root.prefix_actions[-1] == ("deal",)
        assert root.stock == 50 - 10 * root.deal_ordinal
        replay = materialize_root(root)
        zeros = 0
        cursor = materialize_root(opening)
        for action in root.prefix_actions:
            if step_cost(cursor, action) == 0:
                zeros += 1
            apply_action(cursor, action)
        assert zeros == 1
        assert root.corrected_cost == len(root.prefix_actions) - 1
        assert pack_state(replay).hex() == pack_state(cursor).hex()


def test_policy_budget_and_metric_are_frozen():
    spec = policy_specification()
    assert spec["deal_id"] == "4925153"
    assert spec["roots"] == ["opening", "after-deal-1", "after-deal-2", "after-deal-3"]
    assert spec["identity"] == "pack_state"
    assert spec["actions"] == "all_legal_actions"
    assert spec["lower_bound"] is None
    assert spec["workers"] == 1
    assert spec["reveal_goal"] == REVEAL_GOAL == 2
    assert spec["reveal_phase_complete_is_solved"] is False
    assert spec["witness_upper_bound_is_admissible"] is False
    assert spec["independent_cold_complete"] is False
    assert spec["probe"]["max_unique"] == PROBE_MAX_UNIQUE == 20
    assert spec["probe"]["time_limit_s"] == PROBE_TIME_LIMIT_S == 2.0
    assert spec["probe"]["rss_abort_mb"] == 512.0
    assert spec["probe"]["cost_ceiling"] == PROBE_COST_CEILING == 4
    assert spec["probe"]["max_depth"] is None
    assert spec["probe"]["harvest_slack"] is None
    assert spec["probe"]["stop_on_first_terminal"] is False
    assert spec["probe"]["slots"] == PROBE_SLOTS == 8
    assert spec["episode"]["wall_s"] == EPISODE_WALL_S == 60.0
    assert spec["episode"]["additional_paid"] == EPISODE_ADDITIONAL_PAID == 12
    assert spec["episode"]["primitive_actions"] == EPISODE_PRIMITIVE_ACTIONS == 64
    assert spec["episode"]["planning_decisions"] == EPISODE_PLANNING_DECISIONS == 8
    assert spec["episode"]["probe_identities"] == EPISODE_PROBE_IDENTITIES == 1280
    assert spec["episode"]["rss_mb"] == EPISODE_RSS_MB == 512.0
    assert spec["episode"]["one_run_per_mode"] is True
    assert spec["probe"]["unfinished_witness"] == (
        "executable as ordering evidence, not a minimum certificate"
    )
    assert mode_order(0) == ("baseline", "witness")
    assert mode_order(1) == ("witness", "baseline")
    assert mode_order(2) == ("baseline", "witness")
    assert mode_order(3) == ("witness", "baseline")
    assert "not a win" in spec["metric"]["stock_alone"]
    assert "tradeoffs" in spec["metric"]["mixed"]


def test_manifest_does_not_retain_the_reference_suffix():
    manifest = prepare_manifest()
    assert manifest.suffix_discarded is True
    longest = max((root.prefix_actions for root in manifest.roots), key=len)
    assert len(longest) == manifest.retained_action_count == 102
    assert len(longest) < manifest.canonical_action_count
    assert all(len(root.prefix_actions) <= 102 for root in manifest.roots)


def test_preparation_cap_blocks_instead_of_returning_roots():
    with pytest.raises(ProvenanceBlocker):
        prepare_manifest(budget_s=-1.0)


def _lf(payload: bytes) -> bytes:
    return payload.replace(b"\r\n", b"\n").replace(b"\r", b"\n")


def _crlf(payload: bytes) -> bytes:
    return _lf(payload).replace(b"\n", b"\r\n")


def _root_key(manifest):
    return tuple(
        (
            root.root_id,
            root.prefix_actions,
            root.corrected_cost,
            root.pack_hex,
            root.stock,
            root.hidden,
            root.foundations,
        )
        for root in manifest.roots
    )


def test_lf_and_crlf_copies_are_the_same_roots_and_token_edits_are_rejected(tmp_path):
    deal_path = ROOT / "deals" / "4925153.txt"
    move_path = ROOT / "solutions" / "4925153_canonical.moves"
    deal_before = deal_path.read_bytes()
    move_before = move_path.read_bytes()
    deal_lf = _lf(deal_before)
    deal_crlf = _crlf(deal_before)
    move_lf = _lf(move_before)
    move_crlf = _crlf(move_before)
    assert hashlib.sha256(deal_lf).hexdigest().upper() == DEAL_SHA256_LF
    assert hashlib.sha256(deal_crlf).hexdigest().upper() == DEAL_SHA256_CRLF
    assert hashlib.sha256(move_lf).hexdigest().upper() == CANONICAL_SHA256_LF
    assert hashlib.sha256(move_crlf).hexdigest().upper() == CANONICAL_SHA256_CRLF
    assert DEAL_SHA256_LF != DEAL_SHA256_CRLF
    assert CANONICAL_SHA256_LF != CANONICAL_SHA256_CRLF

    def write(name, payload):
        path = tmp_path / name
        path.write_bytes(payload)
        return path

    lf = prepare_manifest(
        deal_path=write("deal-lf.txt", deal_lf),
        canonical_path=write("moves-lf.moves", move_lf),
    )
    crlf = prepare_manifest(
        deal_path=write("deal-crlf.txt", deal_crlf),
        canonical_path=write("moves-crlf.moves", move_crlf),
    )
    assert lf.deal_sha256 == DEAL_SHA256_LF
    assert crlf.deal_sha256 == DEAL_SHA256_CRLF
    assert lf.canonical_sha256 == CANONICAL_SHA256_LF
    assert crlf.canonical_sha256 == CANONICAL_SHA256_CRLF
    assert _root_key(lf) == _root_key(crlf) == _root_key(prepare_manifest())
    assert lf.canonical_mw == crlf.canonical_mw == 172
    assert lf.canonical_foundations == crlf.canonical_foundations == 8
    assert lf.canonical_stock_remaining == crlf.canonical_stock_remaining == 0
    assert lf.canonical_tableau_empty is True and crlf.canonical_tableau_empty is True

    changed_deal = deal_lf.replace(b"10c", b"10d", 1)
    assert hashlib.sha256(changed_deal).hexdigest().upper() not in ACCEPTED_DEAL_SHA256
    with pytest.raises(ProvenanceBlocker):
        prepare_manifest(
            deal_path=write("deal-token.txt", changed_deal),
            canonical_path=write("moves-lf-again.moves", move_lf),
        )
    changed_moves = move_lf.replace(b"\nmove ", b"\nmove 9 ", 1)
    assert hashlib.sha256(changed_moves).hexdigest().upper() not in ACCEPTED_CANONICAL_SHA256
    with pytest.raises(ProvenanceBlocker):
        prepare_manifest(
            deal_path=write("deal-lf-again.txt", deal_lf),
            canonical_path=write("moves-token.moves", changed_moves),
        )
    padded = deal_lf.replace(b"\n", b" \n", 1)
    assert hashlib.sha256(padded).hexdigest().upper() not in ACCEPTED_DEAL_SHA256
    with pytest.raises(ProvenanceBlocker):
        prepare_manifest(
            deal_path=write("deal-padded.txt", padded),
            canonical_path=write("moves-lf-pad.moves", move_lf),
        )
    assert deal_path.read_bytes() == deal_before
    assert move_path.read_bytes() == move_before


def test_materialize_rejects_a_mismatched_pack():
    root = prepare_manifest().roots[0]
    forged = FrozenRoot(
        root_id=root.root_id,
        deal_ordinal=root.deal_ordinal,
        prefix_actions=root.prefix_actions,
        corrected_cost=root.corrected_cost,
        pack_hex="00",
        stock=root.stock,
        foundations=root.foundations,
        hidden=root.hidden,
        duplicate_of=None,
        counts_as_evidence=True,
    )
    with pytest.raises(ProvenanceBlocker):
        materialize_root(forged)
