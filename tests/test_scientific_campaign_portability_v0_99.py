"""v0.99 scientific campaign worker and portable research data."""

from __future__ import annotations

import ast
import inspect
import json
import zipfile
from pathlib import Path

import pytest

from spider.campaign_bundle import export_campaign, import_campaign
from spider.campaign_closed import apply_closed_pruning, classify_arrival
from spider.campaign_exchange import ingest_results, publish_result
from spider.campaign_import_v084 import import_v084_population
from spider.campaign_promote import promote_if_solved, reevaluate_proof_viability
from spider.campaign_store import add_candidate, enqueue_job, load_campaign, new_campaign, save_campaign
from spider.campaign_worker import WORKER_MODE, job_worker, run_lean_job, scientific_result_fields
from spider.consequence_search import MinimalConsequenceObserver, run_stockempty_consequence
from spider.hardware_profile import PROFILE_NAME, profile_mismatch
from spider.hardware import detect_hardware
from spider.long_horizon_f2_adjudication import reconstruct_active_root
from spider.blinded_deep_f2 import load_five_root_specs
from spider.metrics import parse_moves_file
from spider.research_actions import dump_actions
from spider.whole_game_anytime import opening_state

ROOT = Path(__file__).resolve().parents[1]
SCHED = ROOT / "src" / "spider" / "campaign_scheduler.py"
WORKER = ROOT / "src" / "spider" / "campaign_worker.py"
GUI = ROOT / "tools" / "campaign_gui.py"
SPEC = ROOT / "spider_campaign.spec"
V074 = ROOT / "solutions" / "4925153_autonomous_v0_74.moves"


def _ctrl187():
    opening = opening_state()
    spec = next(s for s in load_five_root_specs() if s.get("name") == "CONTROL_187")
    post = reconstruct_active_root(opening, spec)
    assert post.get("verify_ok") or post.get("ok")
    return post


def test_worker_is_lean_and_equivalent():
    src = inspect.getsource(job_worker)
    assert "run_lean_job" in src
    wsrc = WORKER.read_text(encoding="utf-8")
    assert "run_stockempty_consequence" in wsrc
    assert "pack_whole_game_identity" in wsrc
    assert "stock_empty_assembly_h" in wsrc
    assert "COMPLETION_LANES" in wsrc
    assert "identity_fn=pack_whole_game_identity" in wsrc
    assert WORKER_MODE == "LEAN_CONSEQUENCE"
    ss = SCHED.read_text(encoding="utf-8")
    assert "from spider.campaign_worker import" in ss
    assert "lane_names=(\"cost\", \"reveal\", \"construction\")" not in ss
    assert "lower_bound_fn=None" not in ss
    post = _ctrl187()
    job = {
        "id": "eq",
        "g": post["g"],
        "ordered_digest": post["ordered_digest"],
        "ident": post.get("ident"),
        "ceiling": 187,
        "time_s": 25.0,
        "max_unique": 2000,
        "stop_on_first_terminal": False,
        "trace": True,
    }
    a = run_lean_job(job, rss_abort_mb=2048, trace=True)
    obs = MinimalConsequenceObserver(trace=True)
    kr = run_stockempty_consequence(
        [{"g": post["g"], "ordered_digest": post["ordered_digest"], "ident": post.get("ident")}],
        ceiling=187,
        time_limit_s=25.0,
        max_unique=2000,
        rss_abort_mb=2048,
        stop_on_first_terminal=False,
        observer=obs,
    )
    assert a["unique"] == kr.unique == 2000
    assert a["expanded"] == kr.expanded
    assert a["generated"] == kr.generated
    assert a["duplicate_skips"] == kr.duplicate_skips
    assert a["stale_skips"] == kr.stale_skips
    assert a["lower_bound_calls"] == kr.lower_bound_calls
    assert a["lower_bound_prunes"] == kr.lower_bound_prunes
    assert a["lane_exp"] == dict(kr.lane_exp)
    assert a["horizon_exp"] == 0
    assert a["trace_hash"] == obs.trace_hex()
    assert a["lower_bound_calls"] > 0
    assert "completion" in a["lanes"]
    assert a["no_deal"] is True
    assert a["identity"] == "pack_whole_game_identity"
    for field in scientific_result_fields():
        assert field in a


def test_bundle_exchange_import_v084(tmp_path: Path):
    camp = new_campaign()
    add_candidate(
        camp,
        g=130,
        ordered_digest="aa",
        ident="id1",
        assembly_h=41,
        full_actions=[("deal",)] * 5,
        n_deal=5,
        source_experiment="t",
        pre_digest="pre",
        prefix_artefact={"artefact": "docs/research/f2_quality_frontier_v0_84.json"},
    )
    folder = tmp_path / "c1"
    save_campaign(folder, camp)
    bundle = export_campaign(folder, tmp_path / "x.spidercampaign")
    dest = tmp_path / "c2"
    imported = import_campaign(bundle, dest)
    assert imported["uuid"] == camp["uuid"]
    assert imported["candidates"][0]["full_actions"]
    assert imported["candidates"][0]["n_deal"] == 5
    assert imported["candidates"][0]["prefix_artefact"]
    with zipfile.ZipFile(bundle) as zf:
        assert PROFILE_NAME not in zf.namelist()
        assert "hardware_profile.json" not in zf.namelist()
        man = json.loads(zf.read("manifest.json"))
        assert man["files"]["campaign.json"]
    shared = tmp_path / "share"
    job = {"id": "j1", "candidate_id": camp["candidates"][0]["id"], "ceiling": 186, "status": "done", "result": {"stop_reason": "time limit", "unique": 10, "solver_sha": "abc"}}
    publish_result(shared, camp, job, machine_id="hostA")
    dest2 = tmp_path / "c3"
    save_campaign(dest2, imported)
    s1 = ingest_results(shared, dest2)
    assert s1["added"] == 1
    s2 = ingest_results(shared, dest2)
    assert s2["skipped"] >= 1
    job2 = {"id": "j2", "candidate_id": camp["candidates"][0]["id"], "ceiling": 186, "status": "done", "result": {"stop_reason": "unique limit", "unique": 11, "solver_sha": "abc"}}
    publish_result(shared, camp, job2, machine_id="hostB")
    s3 = ingest_results(shared, dest2)
    assert s3["added"] == 1
    assert s3["conflicts"] >= 1
    after = load_campaign(dest2)
    assert len(after["imported_results"]) == 2
    pop = import_v084_population()
    st = pop["import_stats"]
    assert st["raw_n_f2"] == 279
    assert st["n_persisted_pre"] >= 48
    assert st["reconstructed"] == st["n_persisted_pre"]
    assert st["unique_post_stock"] >= 1
    assert st["proof_live"] + st["proof_dead"] == st["unique_post_stock"]
    assert st["ancestry_failures"] == 0
    assert any(c.get("prefix_artefact") or c.get("full_actions") or c.get("pre_digest") for c in pop["candidates"])
    gui = GUI.read_text(encoding="utf-8")
    for label in (
        "Export Campaign",
        "Import Campaign",
        "Shared Research Folder",
        "Sync Results",
        "LEAN CONSEQUENCE",
        "Recalibrate",
        "New Campaign",
        "Open Campaign",
        "Pause after current job",
        "Stop",
        "Resume",
        "Export Report",
        "Open Data Folder",
    ):
        assert label in gui
    tree = ast.parse(gui)
    assert tree
    assert inspect.getsource(run_lean_job)
    assert SPEC.exists()
    assert "SpiderCampaign" in SPEC.read_text(encoding="utf-8")


def test_checksum_rejects_corrupt_bundle(tmp_path: Path):
    camp = new_campaign()
    add_candidate(camp, g=1, ordered_digest="ab", ident="x")
    folder = tmp_path / "c"
    save_campaign(folder, camp)
    bundle = export_campaign(folder, tmp_path / "ok.spidercampaign")
    with zipfile.ZipFile(bundle) as zf:
        man = json.loads(zf.read("manifest.json"))
        campaign_bytes = zf.read("campaign.json")
    man["files"]["campaign.json"] = "0" * 64
    bad = tmp_path / "bad.spidercampaign"
    with zipfile.ZipFile(bad, "w") as zf:
        zf.writestr("manifest.json", json.dumps(man))
        zf.writestr("campaign.json", campaign_bytes)
    with pytest.raises(ValueError, match="checksum"):
        import_campaign(bad, tmp_path / "out")


def test_closed_pruning_and_lower_g_reopening():
    ident = "ident-closed"
    table = {ident: {"ident": ident, "g": 170, "source": "v081", "ceiling": 186, "complete": True}}
    cands = [
        {"ident": ident, "g": 171},
        {"ident": ident, "g": 169},
        {"ident": "other", "g": 130},
    ]
    stats = apply_closed_pruning(cands, table, ceiling=186)
    assert cands[0]["known_closed"] is True
    assert cands[1]["lower_g_reopening"] is True
    assert stats["closed_pruned"] == 1
    assert stats["lower_g_reopenings"] == 1
    assert classify_arrival("missing", 100, table)["status"] == "open"


def test_incumbent_promotion_and_proof_filter():
    acts = parse_moves_file(V074)
    campaign = new_campaign(incumbent_g=187, ceiling=187)
    cand = add_candidate(
        campaign,
        g=187,
        ordered_digest="dead",
        ident="sol",
        assembly_h=0,
        assembly_f=187,
        full_actions=dump_actions(acts),
        n_deal=5,
    )
    live = add_candidate(campaign, g=130, ordered_digest="live", ident="l", assembly_h=57, assembly_f=187)
    deadish = add_candidate(campaign, g=140, ordered_digest="d", ident="d", assembly_h=47, assembly_f=187)
    enqueue_job(campaign, live["id"], ceiling=187, time_s=60, max_unique=10)
    result = {"solved": True, "terminal_g": 187, "terminal_actions": [], "job_id": "j"}
    out = promote_if_solved(campaign, cand, result)
    assert out["promoted"] is True
    assert campaign["incumbent_g"] == 187
    assert campaign["production_ceiling"] == 186
    reevaluate_proof_viability(campaign)
    assert live["proof_dead"] is True
    assert deadish["proof_dead"] is True
    assert campaign["jobs"][0]["status"] == "skipped_proof_dead"


def test_machine_change_preserves_scientific_results(tmp_path: Path):
    camp = new_campaign()
    c = add_candidate(camp, g=130, ordered_digest="aa", ident="id", assembly_h=41, full_actions=[("deal",)] * 5, n_deal=5)
    job = enqueue_job(camp, c["id"], ceiling=186, time_s=1, max_unique=10)
    job["status"] = "done"
    job["result"] = {"unique": 9, "stop_reason": "time limit", "worker_mode": "LEAN_CONSEQUENCE"}
    folder = tmp_path / "camp"
    save_campaign(folder, camp)
    loaded = load_campaign(folder)
    assert loaded["jobs"][0]["result"]["unique"] == 9
    snap = detect_hardware()
    fake_profile = {"machine_id": "other-machine|cpu|1p/1l|8GB"}
    assert profile_mismatch(fake_profile, snap) is True
    again = load_campaign(folder)
    assert again["jobs"][0]["result"]["unique"] == 9
    assert again["uuid"] == camp["uuid"]


def test_pyinstaller_entrypoint_and_gui_imports():
    src = SPEC.read_text(encoding="utf-8")
    assert "tools/campaign_gui.py" in src
    assert "spider.campaign_worker" in src
    assert "deals/4925153.txt" in src
    gui = ast.parse(GUI.read_text(encoding="utf-8"))
    assert gui
    import spider.campaign_worker as w
    import spider.campaign_bundle as b
    import spider.campaign_exchange as e
    assert w.WORKER_MODE == "LEAN_CONSEQUENCE"
    assert b.FORMAT.startswith("spidercampaign")
    assert callable(e.publish_result)
