"""Verified own-campaign suffixes and prefix-improvement. No long search."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.autonomous_solve_campaign import atomic_write_json
from spider.global_search_experiment import replay_cost, search_suit_ordered
from spider.incumbent_suffix import (
    SCHEMA,
    VERIFIED_157_GIT_BLOB,
    VERIFIED_157_HASH16,
    VERIFIED_157_RELATIVE,
    LiveSuffixChecker,
    SuffixTable,
    SuffixWitness,
    authenticate_campaign,
    authenticate_inputs,
    authenticate_moves_path,
    best_published_g,
    bound_at,
    build_suffix_table,
    choose_witness,
    complete_from_prefix,
    improvement_label,
    last_eligible_index,
    load_attempt_ledger,
    load_authenticated_route,
    load_campaign_routes,
    load_own_routes,
    publish_verified_game,
    require_pre120_index,
    run_prefix_attempt,
    select_campaign_route,
    shared_prefix_length,
    verified_published_incumbent,
)
from spider.packed_state import pack_state, pack_whole_game_identity, unpack_state
from spider.research_actions import all_legal_actions, opening_from_deal
from spider.search_kernel import SearchLimits, SearchNode, run_search

DEAL = ROOT / "deals" / "4925153.txt"


@pytest.fixture(scope="module")
def corpus():
    opening = opening_from_deal(DEAL)
    routes = load_own_routes(ROOT)
    table = build_suffix_table(opening, routes)
    by_label = {route["label"]: route for route in routes}
    return {"opening": opening, "routes": routes, "table": table, "by_label": by_label}


def _witness(pack: bytes, *, cost: int, actions: tuple, total: int) -> SuffixWitness:
    return SuffixWitness(
        pack=pack,
        source_label="fixture",
        source_path="fixture",
        source_hash16="fixture",
        action_index=0,
        prefix_g=0,
        suffix_cost=cost,
        total_g=total,
        suffix_actions=actions,
    )


def test_zero_cost_suffix_beats_a_shorter_paid_suffix():
    pack = b"same-physical-pack"
    paid = _witness(pack, cost=1, actions=(("deal",),), total=9)
    free = _witness(pack, cost=0, actions=(("deal",), ("deal",), ("deal",)), total=12)
    chosen = choose_witness(paid, free)
    assert chosen is free
    assert chosen.suffix_cost == 0
    assert len(chosen.suffix_actions) > len(paid.suffix_actions)
    table = SuffixTable()
    table.add(paid)
    table.add(free)
    assert table.get(pack) is free


def test_own_routes_share_the_130_prefix_and_authenticated_bounds(corpus):
    opening = corpus["opening"]
    routes = corpus["routes"]
    route = corpus["by_label"]["158"]
    assert shared_prefix_length(routes) == 130
    assert route["path_hash16"] == "9145868d32e42008"
    assert route["g"] == 158
    for label, expected in (("164", 164), ("162", 162), ("160", 160), ("158", 158)):
        assert corpus["by_label"][label]["g"] == expected
        assert corpus["by_label"][label]["foundations"] == 8
    opening_bound = bound_at(opening, route["actions"], 0)
    stock_empty = bound_at(opening, route["actions"], 58)
    at_130 = bound_at(opening, route["actions"], 130)
    at_140 = bound_at(opening, route["actions"], 140)
    at_142 = bound_at(opening, route["actions"], 142)
    at_143 = bound_at(opening, route["actions"], 143)
    assert opening_bound["g"] == 0
    assert opening_bound["h"] == 5
    assert opening_bound["f"] == 5
    assert stock_empty["stock_cards"] == 0
    assert stock_empty["g"] == 58
    assert stock_empty["h"] == 59
    assert stock_empty["f"] == 117
    assert (at_130["foundations"], at_130["face_down"], at_130["h"], at_130["f"]) == (3, 10, 23, 153)
    assert (at_140["foundations"], at_140["h"], at_140["f"]) == (4, 17, 157)
    assert (at_142["h"], at_142["f"]) == (16, 158)
    assert (at_143["h"], at_143["f"]) == (15, 158)
    eligible = last_eligible_index(opening, route["actions"], 157)
    assert eligible is not None and eligible >= 140
    assert bound_at(opening, route["actions"], eligible)["f"] <= 157
    assert at_142["f"] > 157 and at_143["f"] > 157


def test_shorter_prefix_plus_verified_suffix_replays_the_full_game(corpus):
    opening = corpus["opening"]
    route = corpus["by_label"]["158"]
    table = corpus["table"]
    completed = complete_from_prefix(opening, route["actions"][:100], table)
    assert completed["ok"] is True
    assert completed["verified_g"] == 158
    assert completed["actions"] == list(route["actions"])
    assert completed["foundations"] == 8
    missed = complete_from_prefix(opening, route["actions"][:100], SuffixTable())
    assert missed["ok"] is False
    assert missed["reason"] == "table_miss"
    wrong_cost = SuffixTable()
    pack = pack_state(opening)
    wrong_cost.add(
        _witness(pack, cost=1, actions=tuple(route["actions"]), total=1)
    )
    rejected = complete_from_prefix(opening, (), wrong_cost)
    assert rejected["ok"] is False
    assert rejected["verified_g"] == 158
    assert rejected["projected"] == 1


def test_saved_splice_does_not_beat_158():
    payload = authenticate_inputs(ROOT, ceiling=157)
    assert payload["shared_prefix_actions"] == 130
    assert payload["route_158_hash16"] == "9145868d32e42008"
    assert payload["distinct_physical_states"] == 220
    splice = payload["splice"]
    assert splice["claim"] == "saved_path_splice_not_a_search"
    # Route states plus one end state per distinct replay_ok action list.
    # Repeated copies of the same list are not extra records.
    assert splice["prefix_records"] == 735
    assert splice["exact_matches"] == 664
    assert splice["best_total"] == 158
    assert splice["improving_combinations"] == 0
    assert payload["verified_improving_splices"] == []
    assert payload["last_eligible_bound"]["f"] <= 157


def test_expensive_known_suffix_does_not_prune(corpus):
    opening = corpus["opening"]
    route = corpus["by_label"]["158"]
    prefix = tuple(route["actions"][:130])

    state, g = replay_cost(opening, prefix)
    pack = pack_state(state)
    expensive = SuffixTable()
    expensive.add(_witness(pack, cost=10000, actions=tuple(), total=g + 10000))
    kwargs = dict(
        time_limit_s=20.0,
        max_unique=20,
        rss_abort_mb=1024,
        seed=0,
        mode="prefix-improve",
        incumbent_cost=158,
        cost_ceiling=157,
        advice_fn=None,
        prefix_actions=prefix,
        representation="compact",
    )
    plain = search_suit_ordered(opening, suffix_checker=LiveSuffixChecker(SuffixTable(), prefix, 158), **kwargs)
    costly = search_suit_ordered(
        opening.clone(),
        suffix_checker=LiveSuffixChecker(expensive, prefix, 158),
        **kwargs,
    )
    assert plain.lower_bound_prunes == costly.lower_bound_prunes
    assert plain.expanded == costly.expanded
    assert plain.unique == costly.unique
    assert costly.suffix_stats["hits"] >= 1
    assert costly.suffix_stats["non_improving_hits"] >= 1
    assert costly.suffix_stats["accepted"] == 0
    assert plain.suffix_stats["hits"] == 0
    assert plain.suffix_stats["misses"] >= 1
    assert costly.solved is False


def test_bound_equality_stays_eligible_and_the_next_prefixes_are_closed(corpus):
    opening = corpus["opening"]
    route = corpus["by_label"]["158"]
    eligible = last_eligible_index(opening, route["actions"], 157)
    assert eligible is not None

    def attempt(index):
        return search_suit_ordered(
            opening,
            time_limit_s=20.0,
            max_unique=12,
            rss_abort_mb=1024,
            mode="prefix-improve",
            incumbent_cost=158,
            cost_ceiling=157,
            advice_fn=None,
            prefix_actions=tuple(route["actions"][:index]),
            representation="compact",
            suffix_checker=LiveSuffixChecker(corpus["table"], tuple(route["actions"][:index]), 158),
        )

    open_root = attempt(eligible)
    closed = attempt(142)
    assert open_root.expanded > 0
    assert open_root.provenance == "incumbent_prefix_suffix_assisted"
    assert open_root.search_kind_label == "incumbent_prefix_suffix_assisted"
    assert open_root.solved is False
    assert closed.expanded == 0
    assert closed.lower_bound_prunes >= 1
    assert closed.solved is False
    assert closed.to_dict()["search_kind"] == "incumbent_prefix_suffix_assisted"
    assert "not a checkpoint continuation" in closed.to_dict()["notes"]


def test_suffix_witness_is_a_full_replay_not_a_partial_terminal(corpus, tmp_path):
    opening = corpus["opening"]
    route = corpus["by_label"]["158"]
    prefix = tuple(route["actions"][:100])
    result = search_suit_ordered(
        opening,
        time_limit_s=20.0,
        max_unique=1,
        rss_abort_mb=1024,
        mode="prefix-improve",
        incumbent_cost=159,
        cost_ceiling=158,
        advice_fn=None,
        prefix_actions=prefix,
        representation="compact",
        suffix_checker=LiveSuffixChecker(corpus["table"], prefix, 159, tmp_path),
    )
    assert result.solved is True
    assert result.replay_ok is True
    assert result.solution_g == 158
    assert result.actions == tuple(route["actions"])
    assert result.max_foundations < 8
    assert result.census["completion"] == "verified_suffix_witness"
    assert "outside_ceiling_g" not in result.census
    assert result.suffix_stats["accepted"] == 1
    assert result.suffix_stats["in_budget"] is True
    assert result.suffix_stats["configured_ceiling"] == 158
    assert result.suffix_stats["ceiling"] == 157
    published = best_published_g(tmp_path)
    assert published == 158
    again = publish_verified_game(
        tmp_path,
        route["actions"],
        158,
        header="repeat",
    )
    assert again["rewritten"] is False
    assert best_published_g(tmp_path) == 158


def _admitted_prefix_node(opening, prefix):
    state, g = replay_cost(opening, prefix)
    pack = pack_state(state)
    node = SearchNode(pack, pack, int(g), 0, -1, None)
    kernel = type("Kernel", (), {"nodes": [node]})()
    return kernel, state, int(g)


def test_tighter_ceiling_stays_put_when_the_known_suffix_is_outside_it(corpus, tmp_path):
    opening = corpus["opening"]
    route = corpus["by_label"]["158"]
    prefix = tuple(route["actions"][:100])
    kernel, state, g = _admitted_prefix_node(opening, prefix)

    tight = LiveSuffixChecker(corpus["table"], prefix, 159, tmp_path / "tight")
    tight.ceiling_box = [148]
    assert tight.observe(kernel, state, g, 0)["g"] == 158
    assert tight.ceiling_box == [148]
    assert tight.accepted == 1
    assert tight.incumbent == 158
    assert tight.best["in_budget"] is False
    assert tight.best["configured_ceiling"] == 148
    assert tight.stats()["ceiling"] == 148
    assert tight.stats()["in_budget"] is False
    assert best_published_g(tmp_path / "tight") == 158
    tight.observe(kernel, state, g, 0)
    assert tight.ceiling_box == [148]
    assert tight.accepted == 1

    loose = LiveSuffixChecker(corpus["table"], prefix, 159, tmp_path / "loose")
    loose.ceiling_box = [158]
    loose.observe(kernel, state, g, 0)
    assert loose.ceiling_box == [157]
    assert loose.best["in_budget"] is True
    assert loose.stats()["configured_ceiling"] == 158
    assert loose.stats()["ceiling"] == 157

    admitted = search_suit_ordered(
        opening,
        time_limit_s=20.0,
        max_unique=1,
        rss_abort_mb=1024,
        mode="prefix-improve",
        incumbent_cost=159,
        cost_ceiling=148,
        advice_fn=None,
        prefix_actions=prefix,
        representation="compact",
        suffix_checker=LiveSuffixChecker(corpus["table"], prefix, 159, tmp_path / "search"),
    )
    assert admitted.cost_ceiling == 148
    assert admitted.solved is False
    assert admitted.solution_g is None
    assert admitted.census["completion"] == "verified_suffix_outside_ceiling"
    assert admitted.census["outside_ceiling_g"] == 158
    assert admitted.suffix_stats["accepted"] == 1
    assert admitted.suffix_stats["best_g"] == 158
    assert admitted.suffix_stats["in_budget"] is False
    assert admitted.suffix_stats["configured_ceiling"] == 148
    assert admitted.suffix_stats["ceiling"] == 148
    assert best_published_g(tmp_path / "search") == 158
    notes = admitted.to_dict()["notes"]
    assert "never raises the configured ceiling" in notes
    assert "not an in-budget result" in notes


def test_cold_continuation_keeps_its_guard_and_does_not_install_the_bound(corpus):
    opening = corpus["opening"]
    prefix = tuple(corpus["by_label"]["158"]["actions"][:20])
    with pytest.raises(ValueError, match="incumbent"):
        search_suit_ordered(
            opening,
            time_limit_s=5.0,
            max_unique=5,
            rss_abort_mb=512,
            mode="cold",
            incumbent_cost=158,
            prefix_actions=prefix,
        )
    with pytest.raises(ValueError, match="checkpoint continuation"):
        search_suit_ordered(
            opening,
            time_limit_s=5.0,
            max_unique=5,
            rss_abort_mb=512,
            mode="optimise",
            incumbent_cost=158,
            prefix_actions=prefix,
        )
    cold = search_suit_ordered(
        opening,
        time_limit_s=15.0,
        max_unique=12,
        rss_abort_mb=1024,
        mode="cold",
        incumbent_cost=None,
        cost_ceiling=300,
        advice_fn=None,
        prefix_actions=prefix,
        representation="compact",
    )
    assert cold.provenance == "checkpoint_continuation"
    assert cold.search_kind_label == "checkpoint_continuation"
    assert cold.lower_bound_prunes == 0
    assert cold.imported_incumbent is False


def test_live_ceiling_drop_keeps_equality_and_drops_costlier_children():
    opening = opening_from_deal(DEAL)
    box = [5]
    diagnostics = {}

    def progress(_kr, _state, g, _node):
        if g == 0:
            box[0] = 0

    result = run_search(
        [{"g": 0, "ordered_digest": pack_state(opening).hex()}],
        limits=SearchLimits(max_unique=40, time_limit_s=15.0, rss_abort_mb=1024, cost_ceiling=5),
        ceiling_box=box,
        identity_fn=pack_whole_game_identity,
        store_fn=pack_state,
        unpack_fn=unpack_state,
        lane_names=("cost",),
        lane_key_fns=[lambda _state, g: (g,)],
        actions_fn=all_legal_actions,
        is_terminal=lambda _state: False,
        on_progress=progress,
        diagnostics=diagnostics,
    )
    assert diagnostics["ceiling"] == 0
    assert result.ceiling_prunes > 0
    assert all(node.g <= 0 for node in result.nodes)


def test_publication_and_interrupted_ledger_survive(corpus, tmp_path):
    route = corpus["by_label"]["158"]
    first = publish_verified_game(tmp_path, route["actions"], 158, header="first")
    raw = Path(first["path"]).read_bytes()
    second = publish_verified_game(tmp_path, route["actions"], 158, header="second")
    assert second["rewritten"] is False
    assert Path(first["path"]).read_bytes() == raw
    assert best_published_g(tmp_path) == 158
    status = tmp_path / "status.json"
    atomic_write_json(
        status,
        {
            "schema": SCHEMA,
            "running": True,
            "best_verified_g": 157,
            "attempts": [
                {"id": "p1", "status": "running", "prefix_index": 130, "unique": 12, "stop_reason": None}
            ],
        },
    )
    raw_status = status.read_bytes()
    resumed = load_attempt_ledger(status, fingerprint={"commit": "test"}, machine={"workers": 1})
    assert status.read_bytes() == raw_status
    unavailable = {"available": False, "reason": "not recorded at launch"}
    assert resumed["source"] == unavailable
    assert resumed["machine"] == unavailable
    assert resumed["attempts"][0]["source"] == unavailable
    assert resumed["attempts"][0]["launch"] == unavailable
    assert resumed["attempts"][0]["status"] == "interrupted"
    assert resumed["attempts"][0]["stop_reason"] == "interrupted"
    assert resumed["attempts"][0]["prefix_index"] == 130
    assert resumed["attempts"][0]["unique"] == 12
    assert resumed["best_verified_g"] == 157
    assert improvement_label(157) == "VERIFIED_IMPROVEMENT"
    assert improvement_label(158) == "NO_VERIFIED_IMPROVEMENT"
    assert improvement_label(None) == "NO_VERIFIED_IMPROVEMENT"

    original_source = {"commit": "80e1e9d2a8b819bb07e8e49211532e55df1f0d43", "dirty": True}
    original_machine = {"cpus": 8, "workers": 1, "rss_cap_mb": 3000.0}
    recorded_launch = {"available": True, "ceiling": 157, "incumbent": 158}
    atomic_write_json(
        status,
        {
            "schema": SCHEMA,
            "running": False,
            "source": original_source,
            "machine": original_machine,
            "best_verified_g": 157,
            "attempts": [
                {
                    "id": "p3",
                    "status": "finished",
                    "prefix_index": 120,
                    "unique": 135206,
                    "source": {"commit": "17b7e9f30731ea9b252045b03f7d38abbf2ce09b"},
                    "launch": recorded_launch,
                },
                {"id": "p0", "status": "finished", "prefix_index": 140, "unique": 1},
            ],
        },
    )
    preserved = status.read_bytes()
    reloaded = load_attempt_ledger(
        status,
        fingerprint={"commit": "later"},
        machine={"workers": 99},
    )
    assert status.read_bytes() == preserved
    assert reloaded["source"] == original_source
    assert reloaded["machine"] == original_machine
    assert reloaded["best_verified_g"] == 157
    assert reloaded["attempts"][0]["source"] == {"commit": "17b7e9f30731ea9b252045b03f7d38abbf2ce09b"}
    assert reloaded["attempts"][0]["launch"] == recorded_launch
    assert reloaded["attempts"][0]["status"] == "finished"
    assert reloaded["attempts"][0]["unique"] == 135206
    assert reloaded["attempts"][1]["source"] == unavailable
    assert reloaded["attempts"][1]["launch"] == unavailable
    assert "later" not in json.dumps(reloaded["attempts"][1])
    assert reloaded["attempts"][1]["prefix_index"] == 140
    assert reloaded["attempts"][1]["unique"] == 1


def test_reference_inputs_are_refused_before_they_are_read(tmp_path):
    with pytest.raises(ValueError):
        load_authenticated_route(tmp_path, "canonical", "solutions/canonical_172.moves")
    with pytest.raises(ValueError):
        load_authenticated_route(ROOT, "canonical", "docs/canonical_example.moves")


def test_prefix_attempt_checkpoints_a_bounded_run(corpus, tmp_path):
    eligible = last_eligible_index(corpus["opening"], corpus["by_label"]["158"]["actions"], 157)
    document = run_prefix_attempt(
        action_index=int(eligible),
        time_limit_s=15.0,
        max_unique=8,
        memory_mb=1024,
        checkpoint_s=0,
        output_dir=tmp_path,
        root=ROOT,
        incumbent=158,
        ceiling=157,
    )
    assert document["running"] is False
    assert document["verified_improvement"] == "NO_VERIFIED_IMPROVEMENT"
    attempt = document["attempts"][-1]
    assert attempt["status"] == "finished"
    assert attempt["representation"] == "compact"
    assert attempt["provenance"] == "incumbent_prefix_suffix_assisted"
    assert attempt["prefix_f"] <= 157
    assert attempt["expanded"] > 0
    assert "suffix" in attempt
    assert attempt["source"]["commit"]
    assert attempt["launch"]["available"] is True
    assert attempt["launch"]["ceiling"] == 157
    assert attempt["launch"]["incumbent"] == 158
    assert attempt["launch"]["representation"] == "compact"
    assert document["source"] == attempt["source"]
    saved = json.loads((tmp_path / "status.json").read_text(encoding="utf-8"))
    assert saved["attempts"][-1]["prefix_index"] == int(eligible)
    assert saved["running"] is False
    frozen = (tmp_path / "status.json").read_bytes()
    resumed = load_attempt_ledger(
        tmp_path / "status.json",
        fingerprint={"commit": "later", "dirty": False},
        machine={"workers": 99},
    )
    assert (tmp_path / "status.json").read_bytes() == frozen
    assert resumed["source"] == saved["source"]
    assert resumed["source"]["commit"] != "later"
    assert resumed["machine"] == saved["machine"]
    assert resumed["attempts"][0]["source"] == saved["attempts"][0]["source"]
    assert resumed["attempts"][0]["launch"] == saved["attempts"][0]["launch"]
    assert resumed["attempts"][0]["launch"]["ceiling"] == 157


def test_historical_fixture_stays_four_routes_when_157_is_added(corpus):
    historical = load_own_routes(ROOT)
    assert [route["label"] for route in historical] == ["164", "162", "160", "158"]
    assert len(corpus["table"]) == 220
    manifest = authenticate_campaign(ROOT, ceiling=156, incumbent=157)
    assert manifest["schema"] == "spider-pre120-optimisation"
    assert manifest["historical"]["labels"] == ["164", "162", "160", "158"]
    assert manifest["historical"]["distinct_physical_states"] == 220
    assert manifest["historical"]["shared_prefix_actions"] == 130
    assert manifest["historical"]["splice_prefix_records"] == 735
    assert manifest["historical"]["splice_exact_matches"] == 664
    assert manifest["historical"]["splice_best_total"] == 158
    assert manifest["historical"]["splice_improving_combinations"] == 0
    assert manifest["incumbent"] == 157
    assert manifest["ceiling"] == 156
    assert manifest["route_157"]["g"] == 157
    assert manifest["route_157"]["path_hash16"] == VERIFIED_157_HASH16
    assert manifest["route_157"]["git_blob"] == VERIFIED_157_GIT_BLOB
    assert manifest["route_157"]["tableau_moves"] == 152
    assert manifest["route_157"]["stock_deals"] == 5
    assert manifest["route_157"]["foundations"] == 8
    assert manifest["shared_prefix_157_158"] == 121
    assert manifest["shared_prefix_all_routes"] == 121
    assert manifest["distinct_physical_states"] > 220
    assert manifest["splice"]["prefix_records"] > 735
    assert manifest["splice"]["best_total"] == 157
    assert manifest["splice"]["improving_combinations"] == 0
    assert manifest["splice_publication"] is None
    assert "prefix_actions" not in manifest["splice"]["best"]
    labels = [route["label"] for route in manifest["routes"]]
    assert labels[:4] == ["164", "162", "160", "158"]
    assert "157" in labels
    for index in (100, 110, 119):
        bound = manifest["bounds_on_157"][str(index)]
        assert bound["f"] == bound["g"] + bound["h"]
        assert bound["f"] <= 156
    route_157 = next(route for route in load_campaign_routes(ROOT) if route["label"] == "157")
    route_158 = corpus["by_label"]["158"]
    assert route_157["actions"][:121] == list(route_158["actions"][:121])
    assert route_157["actions"][121] != route_158["actions"][121]
    assert bound_at(corpus["opening"], route_157["actions"], 119)["pack"] == bound_at(
        corpus["opening"], route_158["actions"], 119
    )["pack"]
    table = build_suffix_table(corpus["opening"], load_campaign_routes(ROOT))
    opening_witness = table.get(pack_state(corpus["opening"]))
    assert opening_witness is not None
    assert opening_witness.source_label == "157"
    assert opening_witness.suffix_cost == 157
    assert opening_witness.total_g == 157
    diverged, diverged_g = replay_cost(corpus["opening"], route_157["actions"][:122])
    diverged_witness = table.get(pack_state(diverged))
    assert diverged_witness is not None
    assert diverged_witness.source_label == "157"
    assert diverged_g + diverged_witness.suffix_cost == 157
    assert corpus["table"].get(pack_state(diverged)) is None
    assert select_campaign_route(load_campaign_routes(ROOT), "best")["label"] == "157"
    assert select_campaign_route(
        [
            {"label": "158", "g": 158},
            {"label": "157", "g": 157},
            {"label": "156", "g": 156, "adopted": True},
        ],
        "best",
    )["label"] == "156"


def test_authentication_failure_is_not_replaced_by_sidecar_metadata(corpus, tmp_path):
    opening = corpus["opening"]
    pinned = authenticate_moves_path(
        opening,
        ROOT / VERIFIED_157_RELATIVE,
        label="157",
        root=ROOT,
        expected_g=157,
        expected_hash16=VERIFIED_157_HASH16,
        expected_git_blob=VERIFIED_157_GIT_BLOB,
        git_relative=VERIFIED_157_RELATIVE,
    )
    copied = tmp_path / "wrong.moves"
    copied.write_bytes((ROOT / "docs/research/autonomous_solve_campaign/4925153_cold_158.moves").read_bytes())
    with pytest.raises(ValueError, match="corrected cost"):
        authenticate_moves_path(
            opening,
            copied,
            label="157",
            root=ROOT,
            expected_g=157,
            expected_hash16=VERIFIED_157_HASH16,
        )
    corrupt = tmp_path / "corrupt.moves"
    corrupt.write_text("move 1 1 99\n", encoding="utf-8")
    with pytest.raises(ValueError):
        authenticate_moves_path(opening, corrupt, label="corrupt", root=ROOT)
    published = publish_verified_game(tmp_path, pinned["actions"], 157, header="pinned")
    sidecar = Path(published["sidecar"])
    payload = json.loads(sidecar.read_text(encoding="utf-8"))
    payload["g"] = 140
    payload["path_hash16"] = "deadbeefdeadbeef"
    sidecar.write_text(json.dumps(payload), encoding="utf-8")
    assert best_published_g(tmp_path) == 140
    found = verified_published_incumbent(tmp_path, opening, root=ROOT)
    assert found is not None
    assert found["g"] == 157
    assert found["path_hash16"] == VERIFIED_157_HASH16
    assert found["sidecar_agreed"] is False
    adopted = load_campaign_routes(ROOT, tmp_path)
    adopted_157 = [route for route in adopted if route["path_hash16"] == VERIFIED_157_HASH16]
    assert len(adopted_157) == 1
    assert select_campaign_route(adopted, "best")["g"] == 157


def test_pre120_runner_rejects_closed_prefixes_and_launches_119(corpus, tmp_path):
    for closed in (120, 130, 140):
        with pytest.raises(ValueError, match="closed"):
            require_pre120_index(closed)
    assert require_pre120_index(119) == 119
    assert require_pre120_index(58) == 58
    routes = load_campaign_routes(ROOT)
    document = run_prefix_attempt(
        action_index=119,
        time_limit_s=15.0,
        max_unique=2,
        memory_mb=1024,
        checkpoint_s=0,
        output_dir=tmp_path,
        root=ROOT,
        route_label="157",
        incumbent=157,
        ceiling=156,
        routes=routes,
        verify_published=True,
        improvement_below=157,
    )
    attempt = document["attempts"][-1]
    assert attempt["route_label"] == "157"
    assert attempt["route_hash16"] == VERIFIED_157_HASH16
    assert attempt["prefix_index"] == 119
    assert attempt["ceiling"] == 156
    assert attempt["incumbent"] == 157
    assert attempt["prefix_f"] <= 156
    assert attempt["provenance"] == "incumbent_prefix_suffix_assisted"
    assert attempt["representation"] == "compact"
    assert attempt["sampled_reseeds"] == 0
    assert attempt["retained_frontier"] == "leaders_not_full_frontier"
    assert attempt["launch"]["available"] is True
    assert attempt["launch"]["ceiling"] == 156
    assert attempt["launch"]["incumbent"] == 157
    assert attempt["source"]["commit"]
    assert document["source"] == attempt["source"]
    assert document.get("best_verified_g") is None
    assert document["verified_improvement"] == "NO_VERIFIED_IMPROVEMENT"
    completed = subprocess.run(
        [
            sys.executable,
            "tools/pre120_optimisation.py",
            "authenticate",
            "--output",
            "docs/research/incumbent_suffix_optimisation",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert completed.returncode != 0
    assert "accepted" in completed.stderr.lower()
