"""Method v1 contracts. These tests do not run a long campaign."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.method_capture import (
    _load_document,
    _promote_verified_complete,
    authenticate_route,
    choose_continuation,
    clamp_rss_mb,
    cold_search_kwargs,
    continuation_prefix,
    load_recipe,
    opening_improve_kwargs,
    parse_meminfo,
    plan_overlapping_windows,
    probe_host_memory,
    refuse_reference_route,
    route_profile,
    run_method_attempt,
)
from spider.packed_state import pack_state, pack_whole_game_identity, unpack_state
from spider.metrics import format_action, parse_moves_file
from spider.research_actions import all_legal_actions, face_down_count, is_deal, opening_from_deal
from spider.search_kernel import KernelResult, SearchLimits, SearchNode, run_search
from spider.suit_completion import suit_completion_score
from spider.global_search_experiment import replay_cost, search_suit_ordered, suit_lane_keys
from spider.whole_game_anytime import LANES

DEAL = ROOT / "deals" / "4925153.txt"
RECIPE = ROOT / "docs" / "research" / "method_capture_optimisation" / "method_v1.json"
LEDGER = ROOT / "docs" / "research" / "method_capture_optimisation" / "status.json"
COLD_164 = ROOT / "docs" / "research" / "method_capture_optimisation" / "4925153_cold_feasibility_164.moves"
HISTORICAL_158 = ROOT / "docs" / "research" / "autonomous_solve_campaign" / "4925153_cold_158.moves"
CRLF_158 = "C5F4059E8288A8160449F5ACF2E8F8B3848368A63A1A99FAE8132E0358492CC1"
LF_158 = "D1CBE17BEDCA6625DD48223685908EB07C46990A70E0638A57F7E7C4AF19BD21"


def _opening():
    return opening_from_deal(DEAL)


def test_recipe_loads_and_matches_the_live_foundation_order():
    recipe = load_recipe(RECIPE)
    opening = _opening()
    keys = suit_lane_keys(opening, 3)
    assert recipe["lane_names"] == list(LANES)
    assert keys["foundation"][0] == -len(opening.foundations)
    assert keys["foundation"][1] == -suit_completion_score(opening)
    assert keys["foundation"][-1] == 3
    assert recipe["advice"] is False
    assert recipe["seed_wired_into_successor_order"] is False
    kwargs = cold_search_kwargs(recipe, rss_abort_mb=3000)
    assert kwargs["mode"] == "cold"
    assert kwargs["advice_fn"] is None
    assert kwargs["prefix_actions"] == ()
    assert "incumbent_cost" not in kwargs
    assert kwargs["cost_ceiling"] == 400
    assert kwargs["max_unique"] == 1_000_000
    assert kwargs["time_limit_s"] == 1500


def test_recipe_rejects_advice_and_a_copied_kernel(tmp_path):
    recipe = load_recipe(RECIPE)
    recipe["advice"] = True
    path = tmp_path / "recipe.json"
    path.write_text(json.dumps(recipe), encoding="utf-8")
    with pytest.raises(ValueError, match="advice"):
        load_recipe(path)


def test_opening_improve_ceiling_keeps_equality_eligible_and_reads_no_route():
    kwargs = opening_improve_kwargs(158, 157, time_limit_s=10, max_unique=20, rss_abort_mb=512)
    assert kwargs["mode"] == "optimise"
    assert kwargs["incumbent_cost"] == 158
    assert kwargs["cost_ceiling"] == 157
    assert kwargs["prefix_actions"] == ()
    assert kwargs["advice_fn"] is None
    wider = opening_improve_kwargs(158, 400, time_limit_s=10, max_unique=20, rss_abort_mb=512)
    assert wider["cost_ceiling"] == 157
    with pytest.raises(ValueError, match="route"):
        run_method_attempt(
            _opening(),
            mode="opening-improve",
            status_path=Path("unused.json"),
            recipe=load_recipe(RECIPE),
            time_limit_s=1,
            max_unique=10,
            rss_abort_mb=512,
            cost_ceiling=157,
            checkpoint_s=0,
            machine={},
            solution_dir=None,
            incumbent_cost=158,
            route_path=Path("notes") / "route.moves",
        )


def test_historical_158_file_matches_the_pinned_lf_or_crlf_hash():
    raw = HISTORICAL_158.read_bytes()
    lf = raw.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    crlf = lf.replace(b"\n", b"\r\n")
    assert hashlib.sha256(lf).hexdigest().upper() == LF_158
    assert hashlib.sha256(crlf).hexdigest().upper() == CRLF_158
    assert hashlib.sha256(raw).hexdigest().upper() in {LF_158, CRLF_158}


def test_authenticated_158_is_a_scalar_and_not_search_guidance():
    info = authenticate_route(_opening(), HISTORICAL_158)
    assert info["valid"] is True
    assert info["g"] == 158
    assert info["actions_loaded_into_search"] is False
    assert "actions" not in info
    assert info["hashes"]["crlf_sha256"] == CRLF_158
    assert info["hashes"]["lf_sha256"] == LF_158
    kwargs = opening_improve_kwargs(info["g"], 157, time_limit_s=10, max_unique=20, rss_abort_mb=512)
    assert kwargs["prefix_actions"] == ()


def test_memory_clamp_uses_the_lesser_of_request_eight_gib_and_forty_percent():
    eight_gib = 8 * 1024
    assert clamp_rss_mb(3000, int(20 * 1024 * 1024 * 1024)) == 3000
    assert clamp_rss_mb(6000, int(10 * 1024 * 1024 * 1024)) == 4096
    assert clamp_rss_mb(10000, int(30 * 1024 * 1024 * 1024)) == eight_gib
    assert clamp_rss_mb(9000, 0) == eight_gib
    total, avail = parse_meminfo("MemTotal: 16384000 kB\nMemAvailable: 8192000 kB\n")
    assert total == 16384000 * 1024
    assert avail == 8192000 * 1024
    host = probe_host_memory()
    assert host["probe"] in {"GlobalMemoryStatusEx", "proc_meminfo", "unavailable"}


def test_overlapping_repair_windows_can_cross_a_stock_deal():
    windows = plan_overlapping_windows(100, [10, 40, 70], span=36, stride=12, limit=6)
    assert len(windows) >= 2
    assert windows[1]["start"] < windows[0]["end"]
    assert any(window["crosses_stock_deals"] for window in windows)
    with pytest.raises(ValueError, match="stride"):
        plan_overlapping_windows(20, [], span=4, stride=4, limit=2)


def test_published_routes_are_refused_before_repair_reads_them(tmp_path):
    with pytest.raises(ValueError, match="solutions"):
        refuse_reference_route(tmp_path / "solutions" / "example.moves")
    with pytest.raises(ValueError, match="published"):
        refuse_reference_route(tmp_path / "route_canonical.moves")


def test_one_deal_profile_records_the_stock_boundary():
    opening = _opening()
    deal = next(action for action in all_legal_actions(opening) if is_deal(action))
    profile = route_profile(opening, [deal])
    assert profile["deal_count"] == 1
    assert profile["deals"][0]["action"] == 1
    assert profile["cost"] == 1


def test_proof_equality_stays_eligible_and_a_larger_bound_prunes_the_root():
    opening = _opening()
    store = pack_state(opening).hex()
    limits = SearchLimits(max_unique=5, time_limit_s=2.0, rss_abort_mb=512, cost_ceiling=0)
    common = dict(
        identity_fn=pack_whole_game_identity,
        store_fn=pack_state,
        unpack_fn=unpack_state,
        actions_fn=all_legal_actions,
        lane_names=LANES,
        lane_keys_fn=suit_lane_keys,
    )
    equal = run_search(
        [{"g": 0, "ordered_digest": store}],
        limits=limits,
        lower_bound_fn=lambda state, g: 0,
        **common,
    )
    above = run_search(
        [{"g": 0, "ordered_digest": store}],
        limits=limits,
        lower_bound_fn=lambda state, g: 1,
        **common,
    )
    assert equal.expanded >= 1
    assert equal.lower_bound_prunes == 0
    assert above.expanded == 0
    assert above.lower_bound_prunes >= 1


def test_seed_does_not_change_a_unique_capped_opening():
    opening = _opening()
    kwargs = dict(
        time_limit_s=15.0,
        max_unique=25,
        rss_abort_mb=512,
        mode="cold",
        cost_ceiling=8,
        advice_fn=None,
    )
    first = search_suit_ordered(opening, seed=0, **kwargs)
    second = search_suit_ordered(opening.clone(), seed=1, **kwargs)
    assert first.stop_reason == "unique limit"
    assert second.stop_reason == "unique limit"
    assert first.actions == second.actions
    assert first.unique == second.unique


def test_short_cold_status_separates_complete_and_unfinished_work(tmp_path):
    status = tmp_path / "status.json"
    recipe = load_recipe(RECIPE)
    document = run_method_attempt(
        _opening(),
        mode="cold",
        status_path=status,
        recipe=recipe,
        time_limit_s=2.0,
        max_unique=40,
        rss_abort_mb=512,
        cost_ceiling=12,
        checkpoint_s=0.2,
        machine={"workers": 1},
        solution_dir=tmp_path,
        historical_best_g=158,
        repo_root=ROOT,
    )
    assert document["schema"] == "spider-method-capture-26"
    assert document["cold_reproduction"] == "COLD_REPRODUCTION_INCOMPLETE"
    assert document["exact_frontier_retained"] is False
    assert document["restart_inherits_exhaustion"] is False
    assert document["resume_kind"] == "sampled_reseed"
    assert document["best_complete"] is None
    assert document["method_captured"] == "METHOD_CAPTURED"
    attempt = document["attempts"][0]
    assert attempt["search_kind"] == "cold_feasibility"
    assert attempt["action_guidance"] == "none"
    assert attempt["incumbent_passed_to_search"] is False
    assert attempt["root_ancestry"] == "fresh_opening"
    reloaded = json.loads(status.read_text(encoding="utf-8"))
    branch = choose_continuation(reloaded, "unfinished")
    assert branch["terminal"] is False
    assert branch["replay_ok"] is True
    prefix = continuation_prefix(_opening(), reloaded, "unfinished")
    assert prefix
    branch["g"] = int(branch["g"]) + 1
    with pytest.raises(ValueError, match="replay"):
        continuation_prefix(_opening(), reloaded, "unfinished")


def test_a_later_flush_keeps_unfinished_branches_from_earlier_attempts():
    from spider.method_capture import _publish_samples

    document = {
        "attempts": [
            {
                "branches": [
                    {
                        "id": "leader-1",
                        "role": "leader",
                        "replay_ok": True,
                        "terminal": False,
                        "actions": ["deal"],
                        "g": 9,
                        "foundations": 2,
                        "face_down": 20,
                        "stock_rows": 3,
                        "action_count": 9,
                        "expanded": True,
                    }
                ]
            }
        ],
        "best_branch": None,
    }
    _publish_samples(document, [])
    assert document["best_unfinished"][0]["id"] == "leader-1"
    assert document["best_branch"]["g"] == 9
    assert document["exact_frontier_retained"] is False


def test_continuation_search_receives_the_unfinished_prefix(tmp_path, monkeypatch):
    status = tmp_path / "status.json"
    recipe = load_recipe(RECIPE)
    run_method_attempt(
        _opening(),
        mode="cold",
        status_path=status,
        recipe=recipe,
        time_limit_s=2.0,
        max_unique=30,
        rss_abort_mb=512,
        cost_ceiling=12,
        checkpoint_s=0,
        machine={"workers": 1},
        solution_dir=tmp_path,
        repo_root=ROOT,
    )
    captured = {}

    class _Stub:
        stop_reason = "unique limit"
        solved = False
        replay_ok = False
        solution_g = None
        replay_g = None
        provenance = "checkpoint_continuation"
        peak_rss_mb = 1.0
        ceiling_kind = "hard_path_cap"
        lane_pops = {}
        actions = ()

    def fake(state, **kwargs):
        captured.update(kwargs)
        return _Stub()

    monkeypatch.setattr("spider.method_capture.search_suit_ordered", fake)
    run_method_attempt(
        _opening(),
        mode="continue",
        status_path=status,
        recipe=recipe,
        time_limit_s=5.0,
        max_unique=20,
        rss_abort_mb=512,
        cost_ceiling=400,
        checkpoint_s=0,
        machine={"workers": 1},
        solution_dir=tmp_path,
        resume_from="unfinished",
        repo_root=ROOT,
    )
    assert captured["mode"] == "cold"
    assert captured["prefix_actions"]
    assert "incumbent_cost" not in captured


def test_continuation_refuses_a_solved_terminal():
    document = {
        "schema": "spider-method-capture-26",
        "reference_seed": False,
        "exact_frontier_retained": False,
        "restart_inherits_exhaustion": False,
        "best_complete": {"g": 158, "validated": True},
        "attempts": [
            {
                "branches": [
                    {
                        "role": "leader",
                        "terminal": True,
                        "replay_ok": True,
                        "actions": ["deal"],
                        "g": 158,
                        "foundations": 8,
                        "face_down": 0,
                        "stock_rows": 0,
                        "pack": "aa",
                    },
                    {
                        "role": "leader",
                        "terminal": False,
                        "replay_ok": True,
                        "actions": ["move 1 2 1"],
                        "g": 4,
                        "foundations": 1,
                        "face_down": 40,
                        "stock_rows": 4,
                        "pack": "bb",
                        "expanded": True,
                    },
                ]
            }
        ],
    }
    chosen = choose_continuation(document, "unfinished")
    assert chosen["terminal"] is False
    assert chosen["g"] == 4
    with pytest.raises(ValueError, match="solved terminal"):
        choose_continuation(document, "complete")
    affordable = {
        "schema": "spider-method-capture-26",
        "reference_seed": False,
        "exact_frontier_retained": False,
        "restart_inherits_exhaustion": False,
        "attempts": [
            {
                "branches": [
                    {
                        "role": "leader",
                        "terminal": False,
                        "replay_ok": True,
                        "actions": ["deal"],
                        "g": 160,
                        "foundations": 7,
                        "face_down": 0,
                        "stock_rows": 0,
                        "pack": "aa",
                    },
                    {
                        "role": "leader",
                        "terminal": False,
                        "replay_ok": True,
                        "actions": ["move 1 2 1"],
                        "g": 145,
                        "foundations": 5,
                        "face_down": 4,
                        "stock_rows": 0,
                        "pack": "bb",
                    },
                ]
            }
        ],
    }
    assert choose_continuation(affordable, "unfinished", max_g=157)["g"] == 145
    assert choose_continuation(affordable, "unfinished")["g"] == 160
    exhausted = {
        "schema": "spider-method-capture-26",
        "reference_seed": False,
        "exact_frontier_retained": False,
        "restart_inherits_exhaustion": False,
        "attempts": [
            {
                "search_kind": "sampled_reseed",
                "stop_reason": "complete",
                "solved": False,
                "prefix_len": 155,
                "branches": [],
            },
            {
                "branches": [
                    {
                        "role": "leader",
                        "terminal": False,
                        "replay_ok": True,
                        "actions": ["deal"],
                        "action_count": 155,
                        "g": 155,
                        "foundations": 6,
                        "face_down": 0,
                        "stock_rows": 0,
                    },
                    {
                        "role": "leader",
                        "terminal": False,
                        "replay_ok": True,
                        "actions": ["move 1 2 1"],
                        "action_count": 145,
                        "g": 145,
                        "foundations": 5,
                        "face_down": 4,
                        "stock_rows": 0,
                    },
                ]
            },
        ],
    }
    assert choose_continuation(exhausted, "unfinished", max_g=157)["g"] == 155


def _method_document(attempts):
    return {
        "schema": "spider-method-capture-26",
        "deal_id": "4925153",
        "reference_seed": False,
        "exact_frontier_retained": False,
        "restart_inherits_exhaustion": False,
        "attempts": attempts,
    }


def _one_step_branch(opening, action, foundations: int) -> dict:
    end, cost = replay_cost(opening, [action])
    return {
        "role": "leader",
        "terminal": bool(end.is_solved()),
        "replay_ok": True,
        "actions": [format_action(action)],
        "action_count": 1,
        "g": int(cost),
        "foundations": int(foundations),
        "face_down": face_down_count(end),
        "stock_rows": len(end.stock) // 10,
        "pack": pack_state(end).hex(),
        "expanded": True,
        "node": 1,
    }


def test_equal_length_prefixes_exhaust_only_the_recorded_root():
    opening = _opening()
    legal = [action for action in all_legal_actions(opening) if not is_deal(action)]
    assert len(legal) >= 2
    exhausted_branch = _one_step_branch(opening, legal[0], 6)
    other_branch = _one_step_branch(opening, legal[1], 7)
    assert exhausted_branch["pack"] != other_branch["pack"]
    assert exhausted_branch["action_count"] == other_branch["action_count"]
    root = {
        "pack": exhausted_branch["pack"],
        "prefix_hash16": "root-hash",
        "root_g": exhausted_branch["g"],
        "prefix_len": 1,
        "deal_id": "4925153",
        "rules": "MW_RULES",
        "cost_ceiling": 157,
        "component_exhausted": True,
    }
    exhausted_branch["prefix_hash16"] = "root-hash"
    other_branch["prefix_hash16"] = "other-hash"
    document = _method_document(
        [
            {
                "search_kind": "sampled_reseed",
                "stop_reason": "complete",
                "stop_class": "heap_empty_under_paid_ceiling",
                "solved": False,
                "prefix_len": 1,
                "cost_ceiling": 157,
                "exhausted_root": root,
                "branches": [],
            },
            {"branches": [exhausted_branch, other_branch]},
        ]
    )
    chosen = choose_continuation(document, "unfinished", max_g=157)
    assert chosen["pack"] == other_branch["pack"]
    assert chosen["action_count"] == exhausted_branch["action_count"]
    same_pack = dict(other_branch)
    same_pack["pack"] = exhausted_branch["pack"]
    same_pack["g"] = exhausted_branch["g"]
    same_pack["prefix_hash16"] = "different-opening"
    same_pack["foundations"] = 8
    document["attempts"][1]["branches"] = [exhausted_branch, same_pack]
    assert choose_continuation(document, "unfinished", max_g=157)["prefix_hash16"] == "different-opening"
    document["attempts"][1]["branches"] = [exhausted_branch]
    with pytest.raises(ValueError, match="no verified unfinished"):
        choose_continuation(document, "unfinished", max_g=157)
    wider = choose_continuation(document, "unfinished", max_g=158)
    assert wider["pack"] == exhausted_branch["pack"]
    assert wider["prefix_hash16"] == "root-hash"


def test_saved_a5_root_does_not_hide_the_other_155_action_branch():
    document = json.loads(LEDGER.read_text(encoding="utf-8"))
    chosen = choose_continuation(document, "unfinished", max_g=157)
    assert chosen["foundations"] == 7
    assert chosen["g"] == 155
    assert chosen["action_count"] == 155
    a5 = next(item for item in document["attempts"] if item["id"] == "a5")
    exhausted_pack = a5["branches"][0]["pack"]
    assert chosen["pack"] != exhausted_pack
    only = _method_document([a5])
    with pytest.raises(ValueError, match="no verified unfinished"):
        choose_continuation(only, "unfinished", max_g=157)
    with pytest.raises(ValueError, match="no verified unfinished"):
        choose_continuation(only, "unfinished", max_g=156)
    released = choose_continuation(only, "unfinished", max_g=158)
    assert released["pack"] == exhausted_pack
    assert released["g"] == 155
    assert released["foundations"] == 6


def test_continuation_records_the_exhausted_root_not_its_length(tmp_path, monkeypatch):
    opening = _opening()
    legal = [action for action in all_legal_actions(opening) if not is_deal(action)]
    first = _one_step_branch(opening, legal[0], 6)
    second = _one_step_branch(opening, legal[1], 5)
    status = tmp_path / "status.json"
    status.write_text(
        json.dumps(_method_document([{"branches": [first, second]}])),
        encoding="utf-8",
    )

    class _Stub:
        stop_reason = "complete"
        solved = False
        replay_ok = False
        solution_g = None
        replay_g = None
        provenance = "checkpoint_continuation"
        peak_rss_mb = 1.0
        ceiling_kind = "hard_path_cap"
        lane_pops = {}
        actions = ()

    monkeypatch.setattr("spider.method_capture.search_suit_ordered", lambda state, **kwargs: _Stub())
    document = run_method_attempt(
        opening,
        mode="continue",
        status_path=status,
        recipe=load_recipe(RECIPE),
        time_limit_s=5.0,
        max_unique=20,
        rss_abort_mb=512,
        cost_ceiling=30,
        checkpoint_s=0,
        machine={"workers": 1},
        solution_dir=tmp_path,
        resume_from="unfinished",
        repo_root=ROOT,
    )
    recorded = document["attempts"][-1]["exhausted_root"]
    assert recorded["component_exhausted"] is True
    assert recorded["pack"] == first["pack"]
    assert recorded["root_g"] == first["g"]
    assert recorded["cost_ceiling"] == 30
    assert recorded["rules"] == "MW_RULES"
    assert recorded["deal_id"] == "4925153"
    assert recorded["prefix_len"] == 1
    chosen = choose_continuation(document, "unfinished", max_g=30)
    assert chosen["pack"] == second["pack"]
    released = choose_continuation(document, "unfinished", max_g=31)
    assert released["pack"] == first["pack"]


def test_terminal_discovery_publishes_before_the_search_returns(tmp_path):
    from spider.method_capture import _Observer

    actions = parse_moves_file(COLD_164)
    opening = _opening()
    end, cost = replay_cost(opening, actions)
    assert end.is_solved()
    assert int(cost) == 164
    pack = pack_state(end)
    kernel = KernelResult(
        unique=1,
        expanded=0,
        generated=1,
        nodes=[SearchNode(ident=pack, store=pack, g=int(cost), origin=0, parent=-1, action=None)],
    )
    document = _method_document([])
    attempt = {"id": "a-terminal", "search_kind": "cold_feasibility", "branches": []}
    document["attempts"].append(attempt)
    document["best_complete"] = {"g": 170, "path_hash16": "older", "validated": True}
    observer = _Observer(
        opening,
        actions,
        attempt,
        document,
        tmp_path / "status.json",
        0,
        None,
        solution_dir=tmp_path,
        kind="cold_feasibility",
        header="Interrupted terminal.",
        incumbent=158,
    )
    observer.last_kr = kernel
    observer.leaders[(8, 0)] = 0
    observer.leader_rank[(8, 0)] = (0, int(cost))
    observer.flush(running=True)
    assert attempt["status"] == "running"
    assert document["best_complete"]["g"] == 164
    assert document["best_complete"]["validated"] is True
    assert document["best_complete"]["path_hash16"] == "e56a441f03423876"
    published = list(tmp_path.glob("*.moves"))
    assert len(published) == 1
    observer.flush(running=True)
    assert list(tmp_path.glob("*.moves")) == published
    assert document["best_complete"]["g"] == 164
    document["best_complete"] = {"g": 150, "path_hash16": "better", "validated": True}
    refused = _promote_verified_complete(
        document,
        actions,
        164,
        solution_dir=tmp_path,
        kind="route_guided_repair",
        header="Repair must not raise the best cost.",
        incumbent=158,
    )
    assert refused is False
    assert document["best_complete"]["g"] == 150
    assert list(tmp_path.glob("*.moves")) == published


def test_checkpoint_then_return_syncs_attempt_validation_without_rewriting(tmp_path):
    actions = parse_moves_file(COLD_164)
    document = _method_document([])
    attempt = {
        "id": "a-return",
        "search_kind": "cold_feasibility",
        "validated": False,
        "branches": [],
    }
    document["attempts"].append(attempt)
    published = _promote_verified_complete(
        document,
        actions,
        164,
        solution_dir=tmp_path,
        kind="cold_feasibility",
        header="Checkpoint before return.",
        incumbent=158,
        attempt=None,
    )
    assert published is True
    assert attempt["validated"] is False
    moves = list(tmp_path.glob("*.moves"))
    assert len(moves) == 1
    stamp = moves[0].stat().st_mtime_ns
    again = _promote_verified_complete(
        document,
        actions,
        164,
        solution_dir=tmp_path,
        kind="cold_feasibility",
        header="Search return.",
        incumbent=158,
        attempt=attempt,
    )
    assert again is False
    assert attempt["validated"] is True
    assert attempt["validation_g"] == 164
    assert attempt["validation_failure"] == ""
    assert attempt["contract_failure"] is False
    assert attempt["path_hash16"] == document["best_complete"]["path_hash16"]
    assert attempt["candidate"]["path"] == document["best_complete"]["candidate"]["path"]
    assert moves[0].stat().st_mtime_ns == stamp
    assert list(tmp_path.glob("*.moves")) == moves


def test_saved_terminal_is_promoted_before_continuation(tmp_path, monkeypatch):
    opening = _opening()
    legal = [action for action in all_legal_actions(opening) if not is_deal(action)]
    unfinished = _one_step_branch(opening, legal[0], 1)
    solved = [format_action(action) for action in parse_moves_file(COLD_164)]
    status = tmp_path / "status.json"
    document = _method_document(
        [
            {
                "id": "a-saved",
                "search_kind": "cold_feasibility",
                "branches": [
                    unfinished,
                    {
                        "role": "leader",
                        "terminal": True,
                        "replay_ok": True,
                        "actions": solved,
                        "action_count": len(solved),
                        "g": 164,
                        "foundations": 8,
                        "face_down": 0,
                        "stock_rows": 0,
                        "expanded": True,
                    },
                ],
            }
        ]
    )
    document["source"] = {"commit": "a73478bc354b1da0d3d0749fff1e0c7fd5631648"}
    document["best_complete"] = None
    status.write_text(json.dumps(document), encoding="utf-8")
    captured = {}

    class _Stub:
        stop_reason = "unique limit"
        solved = False
        replay_ok = False
        solution_g = None
        replay_g = None
        provenance = "checkpoint_continuation"
        peak_rss_mb = 1.0
        ceiling_kind = "hard_path_cap"
        lane_pops = {}
        actions = ()

    def fake(state, **kwargs):
        on_disk = json.loads(status.read_text(encoding="utf-8"))
        captured["best_g"] = on_disk["best_complete"]["g"]
        captured["files"] = [path.name for path in tmp_path.glob("*.moves")]
        captured["prefix_len"] = len(kwargs["prefix_actions"])
        return _Stub()

    monkeypatch.setattr("spider.method_capture.search_suit_ordered", fake)
    returned = run_method_attempt(
        opening,
        mode="continue",
        status_path=status,
        recipe=load_recipe(RECIPE),
        time_limit_s=5.0,
        max_unique=10,
        rss_abort_mb=512,
        cost_ceiling=400,
        checkpoint_s=0,
        machine={"workers": 1},
        solution_dir=tmp_path,
        resume_from="unfinished",
        repo_root=ROOT,
    )
    assert captured["best_g"] == 164
    assert captured["files"]
    assert captured["prefix_len"] == 1
    assert returned["best_complete"]["g"] == 164
    assert returned["attempts"][0]["source_snapshot"]["commit"] == "unknown"
    assert returned["source"]["commit"] == "a73478bc354b1da0d3d0749fff1e0c7fd5631648"
    assert returned["attempts"][-1]["source_snapshot"]["commit"] != "unknown"
    assert returned["attempts"][-1]["source_snapshot"]["configuration"]["mode"] == "continue"


def test_each_attempt_keeps_its_own_source_snapshot(tmp_path, monkeypatch):
    status = tmp_path / "status.json"
    recipe = load_recipe(RECIPE)
    common = dict(
        status_path=status,
        recipe=recipe,
        time_limit_s=1.0,
        max_unique=15,
        rss_abort_mb=512,
        cost_ceiling=8,
        checkpoint_s=0,
        machine={"workers": 1},
        solution_dir=tmp_path,
        repo_root=ROOT,
    )
    first = run_method_attempt(_opening(), mode="cold", **common)
    frozen = json.loads(json.dumps(first["attempts"][0]["source_snapshot"]))
    assert frozen["commit"] not in {"", "unknown"}
    assert isinstance(frozen["dirty"], bool)
    assert len(frozen["relevant_lf_sha256"]["src/spider/method_capture.py"]) == 64
    assert frozen["recipe"]["schema"] == "spider-whole-game-method-v1"
    assert frozen["recipe"]["frozen_at_commit"] == recipe["frozen_at_commit"]
    assert frozen["configuration"]["mode"] == "cold"
    assert frozen["configuration"]["cost_ceiling"] == 8

    def other(repo, loaded):
        del repo, loaded
        return {
            "commit": "ffffffffffffffffffffffffffffffffffffffff",
            "dirty": True,
            "relevant_dirty": [],
            "relevant_lf_sha256": {"src/spider/method_capture.py": "abc"},
            "recipe": {
                "schema": "spider-whole-game-method-v1",
                "version": 1,
                "frozen_at_commit": recipe["frozen_at_commit"],
                "path": "docs/research/method_capture_optimisation/method_v1.json",
                "lf_sha256": "abc",
            },
        }

    monkeypatch.setattr("spider.method_capture._source_identity_snapshot", other)
    second = run_method_attempt(_opening(), mode="cold", **common)
    assert second["attempts"][0]["source_snapshot"] == frozen
    assert second["attempts"][1]["source_snapshot"]["commit"] == "ffffffffffffffffffffffffffffffffffffffff"
    assert second["source"]["commit"] == frozen["commit"]


def test_historical_attempts_stay_unknown_and_a4_keeps_its_errata(tmp_path):
    status = tmp_path / "status.json"
    raw = _method_document(
        [
            {"id": "a1", "search_kind": "cold_feasibility", "prefix_len": 0, "solved": True},
            {
                "id": "a4",
                "search_kind": "sampled_reseed",
                "prefix_len": 155,
                "kernel_provenance_string": "partial_legal_search",
                "root_ancestry": "verified_unfinished_prefix",
                "stop_reason": "unique limit",
            },
        ]
    )
    raw["source"] = {"commit": "a73478bc354b1da0d3d0749fff1e0c7fd5631648"}
    status.write_text(json.dumps(raw), encoding="utf-8")
    loaded = _load_document(status, None, {"commit": "c705183ac879b8e11495b967e8f9fff3c3913b25"})
    assert loaded["source"]["commit"] == "a73478bc354b1da0d3d0749fff1e0c7fd5631648"
    first = loaded["attempts"][0]["source_snapshot"]
    assert first["commit"] == "unknown"
    assert first["historical"] is True
    assert "a73478bc" not in json.dumps(first)
    assert "c705183" not in json.dumps(first)
    a4 = loaded["attempts"][1]
    assert a4["kernel_provenance_string"] == "partial_legal_search"
    assert a4["prefix_len"] == 155
    assert a4["source_snapshot"]["commit"] == "unknown"
    assert "fresh opening" in a4["source_snapshot"]["errata"]
    assert "partial_legal_search" in a4["source_snapshot"]["errata"]
    loaded["attempts"][0]["source_snapshot"] = {
        "commit": "434f8569a359d27e008b3d12ba18b5aa7f8610fb",
        "dirty": False,
    }
    status.write_text(json.dumps(loaded), encoding="utf-8")
    again = _load_document(status, None, {"commit": "deadbeef"})
    assert again["attempts"][0]["source_snapshot"]["commit"] == "434f8569a359d27e008b3d12ba18b5aa7f8610fb"
    assert again["attempts"][1]["source_snapshot"]["commit"] == "unknown"
    assert again["source"]["commit"] == "a73478bc354b1da0d3d0749fff1e0c7fd5631648"
