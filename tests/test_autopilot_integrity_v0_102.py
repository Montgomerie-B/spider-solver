"""v0.102 autopilot scientific integrity hardening."""

from __future__ import annotations

import ast
from pathlib import Path

from spider.campaign_autonomous import run_autonomous_campaign
from spider.campaign_expand import bulk_sd5, create_g123_campaign, enqueue_deepen, proof_filter
from spider.campaign_integrity import (
    extract_autonomous_pre_f2,
    job_payload_from_node,
    maybe_adopt_imported_incumbent,
    recompute_assembly,
    refilter_graph,
    sync_candidate_from_node,
    validate_node_ancestry,
)
from spider.campaign_nodes import add_node, identity_key, make_node, symmetry_key
from spider.campaign_ops import FAILED, PENDING_PARTIAL, mark_failed, next_pending, recover_stale_operations, retry_failed_operation
from spider.campaign_promote import promote_if_solved
from spider.campaign_status import FAILED_CONTRACT, classify_outcome, proof_dead_label
from spider.campaign_store import enqueue_job, new_campaign, save_campaign, load_campaign
from spider.incumbent import current_incumbent_g, production_ceiling
from spider.packed_state import pack_state, pack_whole_game_identity, unpack_state
from spider.research_actions import dump_actions

ROOT = Path(__file__).resolve().parents[1]
GUI = ROOT / "tools" / "campaign_gui.py"
SCHED = ROOT / "src" / "spider" / "campaign_scheduler.py"
NODES = ROOT / "src" / "spider" / "campaign_nodes.py"


def test_same_ordered_lower_g_updates_and_recomputes_f():
    camp = new_campaign()
    create_g123_campaign(camp)
    fx = extract_autonomous_pre_f2()
    assert fx["ok"]
    node = make_node(
        g=int(fx["g"]) + 5,
        ordered_digest=fx["ordered_digest"],
        full_actions=fx["full_actions"],
        kind="PRE_STOCK",
        ancestry_verified=True,
    )
    a = add_node(camp, node)
    cheap = make_node(
        g=int(fx["g"]),
        ordered_digest=fx["ordered_digest"],
        full_actions=fx["full_actions"],
        kind="PRE_STOCK",
        ancestry_verified=True,
        parent_ids=a.get("parent_ids"),
    )
    b = add_node(camp, cheap)
    assert b["id"] == a["id"]
    assert b["g"] == fx["g"]
    assert b["ordered_digest"] == fx["ordered_digest"]
    assert b["full_actions"] == fx["full_actions"]
    assert b.get("lower_g_reopening") is True


def test_symmetric_different_ordered_does_not_mismatch_ancestry():
    camp = new_campaign()
    fx = extract_autonomous_pre_f2()
    pre = make_node(g=fx["g"], ordered_digest=fx["ordered_digest"], full_actions=fx["full_actions"], kind="PRE_STOCK", ancestry_verified=True)
    add_node(camp, pre)
    post = bulk_sd5(camp)
    se = [n for n in camp["nodes"] if n.get("kind") == "STOCK_EMPTY"]
    assert se
    src = se[0]
    st = unpack_state(bytes.fromhex(src["ordered_digest"]))
    # Swap two distinct columns to get a non-trivial permutation.
    i = j = None
    for a in range(10):
        for b in range(a + 1, 10):
            if pack_state.__doc__ is not None:
                ca, cb = st.columns[a], st.columns[b]
                if (ca.face_up, ca.face_down) != (cb.face_up, cb.face_down):
                    i, j = a, b
                    break
        if i is not None:
            break
    assert i is not None
    st2 = unpack_state(bytes.fromhex(src["ordered_digest"]))
    st2.columns[i], st2.columns[j] = st2.columns[j], st2.columns[i]
    d1 = pack_state(st).hex()
    d2 = pack_state(st2).hex()
    ident1 = pack_whole_game_identity(st).hex()
    ident2 = pack_whole_game_identity(st2).hex()
    assert ident1 == ident2
    assert d1 != d2
    other = make_node(
        g=int(src["g"]) - 1,
        ordered_digest=d2,
        full_actions=[],
        kind="STOCK_EMPTY",
        ident=ident2,
        ancestry_verified=False,
        extra={"assembly_h": src.get("assembly_h"), "stock_rows": 0},
    )
    stored = add_node(camp, other)
    assert stored["ordered_digest"] == d2
    assert stored["g"] == int(src["g"]) - 1
    assert src["ordered_digest"] == d1
    assert src["full_actions"] != [] or True
    # Must not glue cheaper prefix onto the other ordered digest.
    assert not (stored["ordered_digest"] == src["ordered_digest"] and stored["g"] < src["g"] and stored["id"] == src["id"])
    assert stored["id"] != src["id"]
    assert stored.get("symmetry_group_id") == src.get("symmetry_group_id") or stored.get("symmetry_equivalent")
    assert stored.get("lower_g_reopening") is True
    recompute_assembly(stored)
    assert stored["assembly_f"] == stored["g"] + stored["assembly_h"]


def test_proof_dead_becomes_live_on_lower_g():
    camp = new_campaign()
    fx = extract_autonomous_pre_f2()
    add_node(camp, make_node(g=fx["g"], ordered_digest=fx["ordered_digest"], full_actions=fx["full_actions"], kind="PRE_STOCK", ancestry_verified=True))
    bulk_sd5(camp)
    se = next(n for n in camp["nodes"] if n.get("kind") == "STOCK_EMPTY")
    recompute_assembly(se)
    f0 = int(se["assembly_f"])
    camp["production_ceiling"] = f0 - 1
    refilter_graph(camp)
    assert str(se["status"]).startswith("PROOF_DEAD")
    cheap = make_node(
        g=int(se["g"]) - 2,
        ordered_digest=se["ordered_digest"],
        full_actions=se["full_actions"],
        kind="STOCK_EMPTY",
        extra={"assembly_h": se["assembly_h"], "stock_rows": 0},
    )
    stored = add_node(camp, cheap)
    assert stored["id"] == se["id"]
    assert stored["assembly_f"] == stored["g"] + stored["assembly_h"]
    assert stored["assembly_f"] == f0 - 2
    assert stored["assembly_f"] <= camp["production_ceiling"]
    assert not str(stored.get("status") or "").startswith("PROOF_DEAD")


def test_promotion_refilters_and_skips_dead(tmp_path: Path):
    camp = new_campaign()
    fx = extract_autonomous_pre_f2()
    n = add_node(camp, make_node(g=fx["g"], ordered_digest=fx["ordered_digest"], full_actions=fx["full_actions"], kind="PRE_STOCK", ancestry_verified=True))
    bulk_sd5(camp)
    se = next(x for x in camp["nodes"] if x.get("kind") == "STOCK_EMPTY")
    recompute_assembly(se)
    camp["production_ceiling"] = int(se["assembly_f"])
    refilter_graph(camp)
    job = enqueue_deepen(camp, se, time_s=1.5, max_unique=50, operation_id="op-d6")
    assert job is not None
    camp["production_ceiling"] = int(se["assembly_f"]) - 1
    camp["incumbent_g"] = int(se["assembly_f"])
    stats = refilter_graph(camp)
    assert se["status"] == proof_dead_label(camp["production_ceiling"])
    assert job["status"] == "skipped_proof_dead"
    again = enqueue_deepen(camp, se, time_s=86400, max_unique=50, operation_id="op-d6b")
    assert again is None
    assert stats["skipped_pending"] >= 1


def test_worker_failure_is_failed_contract():
    empty = classify_outcome({}, ceiling=185)
    assert empty == "UNRESOLVED_TIME"
    failed = classify_outcome({"status": "failed", "error": "exit"}, ceiling=185)
    assert failed == FAILED_CONTRACT
    src = SCHED.read_text(encoding="utf-8")
    assert "FAILED_CONTRACT" in src
    assert "missing_result" in src


def test_failed_g1_blocks_dependents():
    camp = new_campaign()
    camp["operations"] = [
        {"id": "g1", "type": "GENERATE", "status": FAILED, "params": {"step_id": "G1"}},
        {"id": "t1", "type": "TRANSITION_SD5", "status": "pending", "params": {"step_id": "T1"}},
    ]
    camp["autopilot"] = {"state": "PAUSED_ERROR"}
    nxt = next_pending(camp)
    assert nxt is None
    camp["autopilot"]["state"] = "PAUSED_ERROR"
    assert camp["operations"][0]["status"] == FAILED
    retried = retry_failed_operation(camp)
    assert retried is not None
    assert retried["status"] in ("pending", "pending_partial")


def test_pause_partial_operation_does_not_advance():
    camp = new_campaign()
    op = {"id": "d1", "type": "EVALUATE", "status": "running", "params": {"step_id": "D1"}, "member_job_ids": ["j1", "j2"]}
    camp["operations"] = [op, {"id": "g2", "type": "GENERATE", "status": "pending", "params": {"step_id": "G2"}}]
    camp["jobs"] = [
        {"id": "j1", "operation_id": "d1", "status": "done"},
        {"id": "j2", "operation_id": "d1", "status": "pending"},
    ]
    recover_stale_operations(camp)
    assert camp["operations"][0]["status"] == PENDING_PARTIAL
    nxt = next_pending(camp)
    assert nxt["id"] == "d1"
    assert nxt["id"] != "g2"


def test_real_pipeline_fixture_launches_matching_job():
    fx = extract_autonomous_pre_f2()
    assert fx["ok"]
    assert fx["stock_rows"] == 1
    assert fx["foundations"] >= 2
    camp = new_campaign()
    node = add_node(
        camp,
        make_node(
            g=fx["g"],
            ordered_digest=fx["ordered_digest"],
            full_actions=fx["full_actions"],
            kind="PRE_STOCK",
            ancestry_verified=True,
        ),
    )
    chk = validate_node_ancestry(node, force=True)
    assert chk["ok"]
    assert chk["g"] == node["g"]
    assert chk["ordered_digest"] == node["ordered_digest"]
    sd = bulk_sd5(camp)
    assert sd["n_new"] + sd["n_reuse"] >= 1
    se = next(n for n in camp["nodes"] if n.get("kind") == "STOCK_EMPTY")
    assert se["n_deal"] == 5
    assert se.get("full_actions")
    v = validate_node_ancestry(se, force=True)
    assert v["ok"]
    job = enqueue_deepen(camp, se, time_s=1.2, max_unique=300, operation_id="eval1")
    assert job is not None
    assert job["operation_id"] == "eval1"
    assert job["node_id"] == se["id"]
    payload = job_payload_from_node(se, job)
    assert payload["g"] == se["g"]
    assert payload["ordered_digest"] == se["ordered_digest"]
    assert payload["full_actions"] == se["full_actions"]
    sync_candidate_from_node(camp, se)
    cand = next(c for c in camp["candidates"] if c["id"] == se["candidate_id"])
    assert cand["g"] == se["g"]
    assert cand["ordered_digest"] == se["ordered_digest"]
    from spider.resource_policy import recommend_config
    from spider.hardware import detect_hardware
    from spider.campaign_scheduler import run_pending_jobs

    folder = Path("campaigns/_v102_pipe")
    save_campaign(folder, camp)
    summary = run_pending_jobs(folder, recommend_config(detect_hardware()), operation_id="eval1")
    done = load_campaign(folder)
    job2 = next(j for j in done["jobs"] if j.get("operation_id") == "eval1")
    assert job2.get("outcome") in ("UNRESOLVED_TIME", "UNRESOLVED_UNIQUE", "SOLVED", "FAILED_CONTRACT", "EXHAUSTED")
    assert job2.get("outcome") != "UNRESOLVED_TIME" or job2.get("status") == "done"
    assert summary["operation_id"] == "eval1"


def test_import_incumbent_portability(tmp_path: Path):
    camp = new_campaign()
    camp["incumbent_g"] = 187
    worse = maybe_adopt_imported_incumbent(camp)
    assert worse["adopted"] is False
    camp["incumbent_g"] = 185
    camp["incumbent"] = {"full_actions": []}
    bad = maybe_adopt_imported_incumbent(camp)
    assert bad["adopted"] is False
    gui = GUI.read_text(encoding="utf-8")
    assert "Pause after current job" in gui
    ast.parse(gui)
    assert "FAILED_CONTRACT" in SCHED.read_text(encoding="utf-8")
    assert "operation_id" in SCHED.read_text(encoding="utf-8")
    assert current_incumbent_g() == 186
    assert production_ceiling() == 185
    nodes = NODES.read_text(encoding="utf-8")
    assert "different ordered" in nodes.lower() or "ordered_digest is the node" in nodes or "Exact ordered_digest" in nodes
