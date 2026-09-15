"""v0.100 hierarchical campaign engine and verified autonomous 186."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

from spider.campaign_bundle import export_campaign, import_campaign
from spider.campaign_expand import (
    create_g123_campaign,
    create_opening_campaign,
    evaluate_node,
    expand_node,
    expand_sd5_child,
)
from spider.campaign_nodes import add_node, identity_key, make_node, opening_node
from spider.campaign_status import PROOF_DEAD, UNRESOLVED_TIME, classify_outcome
from spider.campaign_store import new_campaign, save_campaign
from spider.f2_quality_frontier import apply_exact_final_deal, expected_g123_digest, verify_g123_root
from spider.metrics import parse_moves_file, replay_actions
from spider.packed_state import pack_state
from spider.recover_autonomous_186 import SOLUTION_MOVES, WINNERS
from spider.research_actions import as_actions, is_deal, stock_rows
from spider.whole_game_anytime import opening_state

ROOT = Path(__file__).resolve().parents[1]
GUI = ROOT / "tools" / "campaign_gui.py"
RECOVER = ROOT / "src" / "spider" / "recover_autonomous_186.py"
CANON = ROOT / "solutions" / "4925153_canonical.moves"


def test_g123_and_winner_constants():
    g123 = verify_g123_root()
    assert g123["ok"]
    assert g123["g"] == 123
    assert g123["foundations"] == 1
    assert g123["face_down"] == 2
    assert g123["stock_rows"] == 1
    assert g123["ordered_digest"] == expected_g123_digest()
    assert sum(1 for a in as_actions(g123["prefix_actions"]) if is_deal(a)) == 4
    assert WINNERS[0]["pre_g"] == 130
    assert WINNERS[1]["pre_g"] == 130
    assert WINNERS[0]["post_g"] == 131
    assert WINNERS[1]["post_g"] == 131
    src = RECOVER.read_text(encoding="utf-8")
    assert "4925153_canonical.moves" not in src or "CANON" in src
    assert "parse_moves_file(CANON)" not in src
    assert "canonical.moves" not in inspect.getsource(verify_g123_root)


def test_186_complete_replay():
    assert SOLUTION_MOVES.exists()
    acts = parse_moves_file(SOLUTION_MOVES)
    opening = opening_state()
    end = opening.clone()
    g = replay_actions(end, acts)
    assert g == 186
    assert sum(1 for a in acts if is_deal(a)) == 5
    assert end.is_solved()
    assert len(end.foundations) == 8
    assert not end.stock
    assert all(c.is_empty() for c in end.columns)
    assert stock_rows(end) == 0
    post_a = apply_exact_final_deal({"g": 130, "ordered_digest": WINNERS[0]["pre_digest"]})
    post_b = apply_exact_final_deal({"g": 130, "ordered_digest": WINNERS[1]["pre_digest"]})
    assert post_a.get("post_digest") == WINNERS[0]["post_digest"]
    assert post_b.get("post_digest") == WINNERS[1]["post_digest"]


def test_campaign_graph_opening_g123_reopening(tmp_path: Path):
    camp = new_campaign(incumbent_g=187, ceiling=186)
    opening = create_opening_campaign(camp)
    assert opening["g"] == 0
    assert opening["full_actions"] == []
    assert opening["n_deal"] == 0
    assert opening["kind"] == "OPENING"
    gcamp = new_campaign(incumbent_g=187, ceiling=186)
    g123 = create_g123_campaign(gcamp)
    assert g123["g"] == 123
    assert g123["full_actions"]
    assert g123["ancestry_verified"] is True
    assert g123["n_deal"] == 4
    assert any(e["child"] == g123["id"] for e in gcamp["edges"])
    orig_g = int(g123["g"])
    cheap = make_node(
        g=orig_g - 1,
        ordered_digest=g123["ordered_digest"],
        full_actions=g123["full_actions"],
        parent_ids=[g123["parent_ids"][0]],
        source="test",
        ancestry_verified=True,
    )
    stored = add_node(gcamp, cheap)
    assert stored.get("lower_g_reopening") is True
    assert identity_key(stored) == identity_key(g123)
    assert stored["g"] == orig_g - 1
    assert sum(1 for n in gcamp["nodes"] if identity_key(n) == identity_key(g123)) == 1
    folder = tmp_path / "g"
    save_campaign(folder, gcamp)
    bundle = export_campaign(folder, tmp_path / "g.spidercampaign")
    imported = import_campaign(bundle, tmp_path / "in")
    assert len(imported.get("nodes") or []) == len(gcamp["nodes"])
    assert imported["nodes"][1]["full_actions"]
    assert classify_outcome({"stop_reason": "time limit"}, ceiling=186, assembly_f=171) == UNRESOLVED_TIME
    assert classify_outcome({"stop_reason": "time limit"}, ceiling=186, assembly_f=171) != PROOF_DEAD
    assert classify_outcome({"stop_reason": "complete"}, ceiling=186) == "EXHAUSTED"


def test_generators_and_timeout_semantics():
    camp = new_campaign(incumbent_g=187, ceiling=186)
    opening = create_opening_campaign(camp)
    kids = expand_node(camp, opening, time_s=2.0, max_unique=600)
    assert kids.get("n_children") >= 1
    child = next(n for n in camp["nodes"] if n["id"] in (kids.get("children") or []))
    assert child.get("full_actions") is not None
    gcamp = new_campaign(incumbent_g=187, ceiling=186)
    g123 = create_g123_campaign(gcamp)
    f2 = expand_node(gcamp, g123, time_s=10.0, max_unique=10_000, suit="d")
    assert f2.get("n_children") >= 1
    pre = next(n for n in gcamp["nodes"] if n["id"] in (f2.get("children") or []) and n.get("stock_rows") == 1)
    assert pre.get("tactical_actions") or pre.get("full_actions")
    sd5 = expand_sd5_child(gcamp, pre)
    assert sd5 is not None
    assert sd5["kind"] == "STOCK_EMPTY"
    assert sd5["n_deal"] == 5
    assert sd5["full_actions"]
    # tiny stock-empty smoke: unique cap forces UNRESOLVED_UNIQUE, not PROOF_DEAD
    ev = evaluate_node(gcamp, sd5, time_s=1.5, max_unique=400)
    assert ev.get("outcome") in (UNRESOLVED_TIME, "UNRESOLVED_UNIQUE", "SOLVED")
    assert ev.get("outcome") != PROOF_DEAD
    if sd5.get("runs"):
        assert sd5["runs"][-1].get("outcome") == ev.get("outcome")


def test_gui_hierarchy_controls():
    gui = GUI.read_text(encoding="utf-8")
    for label in (
        "Create Opening Campaign",
        "Create Known g123 Campaign",
        "Generate Children",
        "Evaluate / Start",
        "Deepen Selected",
        "Deepen All Unresolved",
        "Step to Parent",
        "Open Root/Node",
        "Export Campaign",
        "Import Campaign",
        "Sync Results",
        "Pause after current job",
        "Pause After Current Operation",
        "Start Autopilot",
        "Stop",
        "LEAN CONSEQUENCE",
        "Hardware mode:",
    ):
        assert label in gui
    ast.parse(gui)
    src = RECOVER.read_text(encoding="utf-8")
    assert "harvest_f2_target" in src
    assert "run_lean_job" in src or "run_stockempty_consequence" in src
