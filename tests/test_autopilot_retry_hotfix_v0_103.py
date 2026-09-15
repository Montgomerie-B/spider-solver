"""v0.103 FAILED-operation retry hotfix."""

from __future__ import annotations

import ast
from pathlib import Path

from spider.campaign_autonomous import run_autonomous_campaign
from spider.campaign_ops import FAILED, PENDING, PENDING_PARTIAL, retry_failed_operation
from spider.campaign_store import new_campaign, save_campaign
from spider.hardware import detect_hardware
from spider.resource_policy import recommend_config

ROOT = Path(__file__).resolve().parents[1]
GUI = ROOT / "tools" / "campaign_gui.py"


def test_retry_resets_only_failed_member_jobs():
    camp = new_campaign()
    op = {
        "id": "d1",
        "type": "EVALUATE",
        "status": FAILED,
        "params": {"step_id": "D1"},
        "member_job_ids": ["j-done", "j-fail"],
        "result": {"ok": False, "failed": True},
    }
    camp["operations"] = [op]
    camp["jobs"] = [
        {
            "id": "j-done",
            "operation_id": "d1",
            "status": "done",
            "outcome": "UNRESOLVED_TIME",
            "result": {"unique": 3},
        },
        {
            "id": "j-fail",
            "operation_id": "d1",
            "status": "failed",
            "outcome": "FAILED_CONTRACT",
            "exitcode": 1,
            "result": {"error": "exitcode=1", "outcome": "FAILED_CONTRACT"},
        },
        {
            "id": "j-skip",
            "operation_id": "d1",
            "status": "skipped_proof_dead",
            "outcome": None,
        },
    ]
    op["member_job_ids"] = ["j-done", "j-fail", "j-skip"]
    out = retry_failed_operation(camp)
    assert out is not None
    assert out["status"] == PENDING_PARTIAL
    assert out.get("retry_counts", {}).get("reset") == 1
    assert out["retry_counts"]["kept_done"] == 1
    assert out["retry_counts"]["kept_skipped"] == 1
    jobs = {j["id"]: j for j in camp["jobs"]}
    assert jobs["j-done"]["status"] == "done"
    assert jobs["j-done"]["result"]["unique"] == 3
    assert jobs["j-skip"]["status"] == "skipped_proof_dead"
    assert jobs["j-fail"]["status"] == PENDING
    assert jobs["j-fail"]["outcome"] is None
    assert jobs["j-fail"]["result"] is None
    assert jobs["j-fail"]["exitcode"] is None
    assert out["retry_history"][-1]["jobs"][0]["job_id"] == "j-fail"
    assert out["retry_history"][-1]["jobs"][0]["outcome"] == "FAILED_CONTRACT"
    pending = [j for j in camp["jobs"] if j["status"] == PENDING and j.get("operation_id") == "d1"]
    assert [j["id"] for j in pending] == ["j-fail"]


def test_resume_without_retry_stays_paused_error(tmp_path: Path):
    camp = new_campaign()
    camp["operations"] = [
        {"id": "g1", "type": "GENERATE", "status": FAILED, "params": {"step_id": "G1"}, "result": {"ok": False}},
        {"id": "t1", "type": "TRANSITION_SD5", "status": "pending", "params": {"step_id": "T1"}},
    ]
    camp["g123_id"] = "missing-will-not-run"
    folder = tmp_path / "camp"
    save_campaign(folder, camp)
    logs = []
    summary = run_autonomous_campaign(
        folder, recommend_config(detect_hardware()), profile="SMOKE", on_log=logs.append
    )
    assert summary["autopilot"]["state"] == "PAUSED_ERROR"
    assert summary.get("retry_required") is True
    assert summary["ops_run"] == 0
    assert "plan complete" not in " ".join(logs).lower()
    from spider.campaign_store import load_campaign

    data = load_campaign(folder)
    assert data["autopilot"]["state"] == "PAUSED_ERROR"
    assert data["operations"][0]["status"] == FAILED
    assert data["operations"][1]["status"] == "pending"


def test_gui_retry_and_pause_wording():
    gui = GUI.read_text(encoding="utf-8")
    assert "Retry Failed Operation" in gui
    assert "Pause after current job" in gui
    assert "Pause After Current Operation" not in gui
    ast.parse(gui)
