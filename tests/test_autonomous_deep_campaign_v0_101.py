"""v0.101 incumbent registry, packaged 186, and progressive deepening."""

from __future__ import annotations

import ast
from pathlib import Path

from spider.campaign_autonomous import PROFILES, run_autonomous_campaign
from spider.campaign_schedule import next_round_for_node
from spider.campaign_store import new_campaign, save_campaign
from spider.incumbent import (
    bundled_incumbent_path,
    current_incumbent_g,
    incumbent_moves_path,
    load_incumbent,
    production_ceiling,
)
from spider.metrics import AUTONOMOUS_INCUMBENT_MW, V074_AUTONOMOUS_INCUMBENT_MW, parse_moves_file, replay_actions
from spider.resource_policy import recommend_config
from spider.hardware import detect_hardware
from spider.whole_game_anytime import opening_state

ROOT = Path(__file__).resolve().parents[1]
GUI = ROOT / "tools" / "campaign_gui.py"
SPEC = ROOT / "spider_campaign.spec"
NODES = ROOT / "src" / "spider" / "campaign_nodes.py"


def test_incumbent_registry_is_186():
    rec = load_incumbent()
    assert rec["deal_id"] == "4925153"
    assert rec["incumbent_g"] == 186
    assert rec["production_ceiling"] == 185
    assert rec["verified_replay"] is True
    assert current_incumbent_g() == 186
    assert production_ceiling() == 185
    assert bundled_incumbent_path().exists()
    moves = incumbent_moves_path()
    assert moves.exists()
    g = replay_actions(opening_state().clone(), parse_moves_file(moves))
    assert g == 186
    camp = new_campaign()
    assert camp["incumbent_g"] == 186
    assert camp["production_ceiling"] == 185
    src = NODES.read_text(encoding="utf-8")
    assert "4925153_autonomous_v0_100.moves" not in src or "incumbent" in src
    assert "current_incumbent_g" in src
    assert V074_AUTONOMOUS_INCUMBENT_MW == 187
    assert AUTONOMOUS_INCUMBENT_MW == V074_AUTONOMOUS_INCUMBENT_MW


def test_packaged_app_incumbent_without_git_checkout(tmp_path: Path, monkeypatch):
    sol = tmp_path / "solutions"
    sol.mkdir()
    for name in (
        "4925153_incumbent.json",
        "4925153_autonomous_v0_100.moves",
        "4925153_autonomous_v0_100.json",
    ):
        (sol / name).write_bytes((ROOT / "solutions" / name).read_bytes())
    (tmp_path / "deals").mkdir()
    (tmp_path / "deals" / "4925153.txt").write_bytes((ROOT / "deals" / "4925153.txt").read_bytes())
    monkeypatch.setattr("spider.incumbent.repo_root", lambda: tmp_path)
    monkeypatch.setattr("spider.app_paths.repo_root", lambda: tmp_path)
    import spider.incumbent as inc

    assert inc.current_incumbent_g() == 186
    assert inc.production_ceiling() == 185
    path = inc.incumbent_moves_path()
    assert path.exists()
    g = replay_actions(opening_state().clone(), parse_moves_file(path))
    assert g == 186
    spec = SPEC.read_text(encoding="utf-8")
    assert "solutions/4925153_incumbent.json" in spec
    assert "solutions/4925153_autonomous_v0_100.moves" in spec
    assert "spider.incumbent" in spec


def test_deepening_progresses_beyond_round_two():
    r1 = next_round_for_node({"deepest_budget_s": 0})
    r2 = next_round_for_node({"deepest_budget_s": 60})
    r3 = next_round_for_node({"deepest_budget_s": 300})
    r4 = next_round_for_node({"deepest_budget_s": 1800})
    r5 = next_round_for_node({"deepest_budget_s": 7200})
    assert r1["time_s"] == 60.0 and r1["round"] == 1
    assert r2["time_s"] == 300.0 and r2["round"] == 2
    assert r3["time_s"] == 1800.0 and r3["round"] == 3
    assert r4["time_s"] == 7200.0 and r4["round"] == 4
    assert r5["time_s"] == 28800.0 and r5["round"] == 5
    r6 = next_round_for_node({"deepest_budget_s": 28800})
    r7 = next_round_for_node({"deepest_budget_s": 86400})
    assert r6["time_s"] == 86400.0 and r6["round"] == 6
    assert r7["time_s"] == 86400.0 and r7.get("repeat") is True
    assert r7["label"] == "REPEAT 24H"
    gui = GUI.read_text(encoding="utf-8")
    assert "DEFAULT_ROUNDS[min(1" not in gui
    assert "next_round_for_node" in gui
    assert "Deep campaign profile" in gui
    assert "run_autonomous_campaign" in gui
    ast.parse(gui)
    assert "G123_DIAMOND_DEEP" in PROFILES
    assert "REPEAT_24H" in PROFILES or "SMOKE" in PROFILES


def test_generation_bulk_sd5_dedup_and_autopilot(tmp_path: Path):
    from spider.campaign_expand import bulk_sd5, create_g123_campaign, expand_f2_children, proof_filter
    from spider.campaign_nodes import add_node, identity_key, make_node
    from spider.campaign_ops import recover_stale_operations
    from spider.campaign_status import GENERATION_UNRESOLVED_TIME, proof_dead_label
    from spider.campaign_store import load_campaign

    camp = new_campaign()
    g123 = create_g123_campaign(camp)
    first = expand_f2_children(camp, g123, time_s=4.0, max_unique=4000, suit="d")
    assert first.get("history")
    assert first["history"]["target_suit"] == "d"
    assert "n_new" in first["history"]
    hist0 = list(g123.get("generation_runs") or [])
    assert hist0
    second = expand_f2_children(camp, g123, time_s=4.0, max_unique=4000, suit="d")
    assert second["history"]["n_duplicate"] >= 0
    n_pre = sum(1 for n in camp["nodes"] if n.get("kind") == "PRE_STOCK")
    third = expand_f2_children(camp, g123, time_s=4.0, max_unique=4000, suit="d")
    n_pre2 = sum(1 for n in camp["nodes"] if n.get("kind") == "PRE_STOCK")
    assert n_pre2 == n_pre or n_pre2 >= n_pre
    if g123.get("generation_status") == GENERATION_UNRESOLVED_TIME:
        assert g123["generation_status"] != "EXHAUSTED"
    sd = bulk_sd5(camp)
    assert sd["n_fail"] == 0
    posts = [n for n in camp["nodes"] if n.get("kind") == "STOCK_EMPTY"]
    for p in posts:
        assert p.get("n_deal") == 5
        assert p.get("full_actions")
    keys = [identity_key(p) for p in posts]
    assert len(keys) == len(set(keys))
    filt = proof_filter(camp)
    assert filt["ceiling"] == 185
    assert filt["label"] == proof_dead_label(185)
    clone = make_node(
        g=g123["g"],
        ordered_digest=g123["ordered_digest"],
        full_actions=g123["full_actions"],
        parent_ids=g123["parent_ids"],
        ancestry_verified=True,
    )
    reused = add_node(camp, clone)
    assert reused["id"] == g123["id"]
    assert reused.get("arrival") == "duplicate"

    folder = tmp_path / "camp"
    save_campaign(folder, new_campaign())
    cfg = recommend_config(detect_hardware())
    summary = run_autonomous_campaign(folder, cfg, profile="SMOKE")
    assert summary["profile"] == "SMOKE"
    data = load_campaign(folder)
    assert data.get("g123_id")
    assert data["incumbent_g"] == 186
    assert data["production_ceiling"] == 185
    types = [o.get("type") for o in data.get("operations") or []]
    assert "GENERATE" in types
    assert "TRANSITION_SD5" in types
    assert "FILTER" in types
    assert data.get("autopilot", {}).get("state") in ("STOPPED", "PAUSED", "RUNNING")
    for op in data.get("operations") or []:
        if op.get("status") == "done":
            assert op.get("finished_at")
    data["operations"][0]["status"] = "running"
    n = recover_stale_operations(data)
    assert n >= 1
    assert data["operations"][0]["status"] == "pending"
    summary2 = run_autonomous_campaign(folder, cfg, profile="SMOKE")
    data2 = load_campaign(folder)
    assert data2.get("g123_id") == data.get("g123_id")
