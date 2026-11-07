"""Scheduler, exhaustion, resources, and packaged authentication for the Optimise tab."""
import json
import shutil
import subprocess
import sys
import time
from copy import deepcopy
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

from spider.incumbent_suffix import load_authenticated_route
from spider.method_capture import probe_host_memory
from spider.packaged_runtime import resource_report, verify_manifest_files, verify_packaged_seed
from spider.play_session import PlaySession
from spider.research_actions import opening_from_deal
from spider.unattended_optimiser import (
    INITIAL_CEILING,
    RECOVERY_TEXT,
    SEED_HASH,
    OptimiserCampaign,
    assert_campaign_dir,
    classify_stop,
    covered_by_exhaustion,
    normalise_settings,
    open_verified_route,
    plan_jobs,
    work_key,
)

DEAL = ROOT / "deals" / "4925153.txt"
SEED = "docs/research/pre120_optimisation/4925153_assisted_140.moves"
RESEARCH_STATUS = ROOT / "docs" / "research" / "pre120_optimisation" / "status.json"


@pytest.fixture(scope="module")
def seed_route():
    opening = opening_from_deal(DEAL)
    route = load_authenticated_route(ROOT, "140", SEED)
    return opening, route


def _resources(unique=1000, rss=3000):
    return resource_report(rss, unique)


def _settings(unique=1000, rss=3000, attempt=30):
    return normalise_settings({
        "campaign_duration_s": 600,
        "attempt_time_limit_s": attempt,
        "requested_rss_mb": rss,
        "max_unique": unique,
    })


def test_initial_queue_starts_with_actions_100_and_90(seed_route):
    opening, route = seed_route
    assert route["path_hash16"] == SEED_HASH
    jobs, notes = plan_jobs(
        route, opening, ceiling=INITIAL_CEILING, settings=_settings(),
        resources=_resources(), jobs=[],
    )
    assert [job["index"] for job in jobs[:2]] == [100, 90]
    assert all(job["identity"]["rules"] == "MW_RULES" for job in jobs[:2])
    assert all(job["identity"]["ceiling"] == 139 for job in jobs[:2])
    assert all(job["identity"]["physical_pack"] for job in jobs[:2])
    assert all(job["identity"]["ancestry"]["prefix_hash16"] for job in jobs[:2])
    assert all(job["bound"]["f"] <= 139 for job in jobs)
    assert not any("action 100" in note and "above ceiling" in note for note in notes)
    assert not any("action 90" in note and "above ceiling" in note for note in notes)


def test_identical_capped_jobs_are_not_repeated(seed_route):
    opening, route = seed_route
    resources = _resources()
    settings = _settings()
    jobs, _notes = plan_jobs(
        route, opening, ceiling=139, settings=settings, resources=resources, jobs=[],
    )
    finished = deepcopy(jobs[0])
    finished["state"] = "time limit"
    finished["exhausted"] = False
    finished["stop_reason"] = "time limit"
    again, notes = plan_jobs(
        route, opening, ceiling=139, settings=settings, resources=resources, jobs=[finished],
    )
    assert all(work_key(job["identity"]) != work_key(finished["identity"]) for job in again)
    assert any("identical" in note for note in notes)
    smaller = _resources(unique=25)
    retried, _notes = plan_jobs(
        route, opening, ceiling=139, settings=_settings(unique=25), resources=smaller, jobs=[finished],
    )
    same_prefix = [job for job in retried if job["index"] == finished["index"]]
    assert same_prefix
    assert same_prefix[0]["recovery"] == RECOVERY_TEXT or finished["state"] != "interrupted"
    interrupted = deepcopy(finished)
    interrupted["state"] = "interrupted"
    interrupted["recovery"] = RECOVERY_TEXT
    retried, _notes = plan_jobs(
        route, opening, ceiling=139, settings=_settings(unique=25), resources=smaller, jobs=[interrupted],
    )
    same_prefix = [job for job in retried if job["index"] == interrupted["index"]]
    assert same_prefix and same_prefix[0]["recovery"] == RECOVERY_TEXT
    assert same_prefix[0]["exhausted"] is False


def test_only_a_finished_frontier_is_exhaustion(seed_route):
    opening, route = seed_route
    jobs, _notes = plan_jobs(
        route, opening, ceiling=139, settings=_settings(), resources=_resources(), jobs=[],
    )
    identity = jobs[0]["identity"]
    assert classify_stop("complete", terminated=False, requested_stop=False)["exhausted"] is True
    for reason in ("time limit", "unique limit", "rss abort", "solved", "failed"):
        outcome = classify_stop(reason, terminated=False, requested_stop=False)
        assert outcome["exhausted"] is False
    stopped = classify_stop("complete", terminated=True, requested_stop=True)
    interrupted = classify_stop(None, terminated=True, requested_stop=False)
    assert stopped["exhausted"] is False and interrupted["exhausted"] is False
    assert "exact search frontier was not retained" in interrupted["recovery"]
    assert "not an exhaustion claim" in interrupted["recovery"]
    done = deepcopy(jobs[0])
    done["state"] = "complete"
    done["exhausted"] = True
    assert covered_by_exhaustion(identity, [done])
    tighter = deepcopy(identity)
    tighter["ceiling"] = 120
    assert covered_by_exhaustion(tighter, [done])
    looser = deepcopy(identity)
    looser["ceiling"] = 150
    assert covered_by_exhaustion(looser, [done]) is False


def test_resource_clamp_uses_available_ram_and_keeps_one_worker():
    report = resource_report(100_000, 5_000_000)
    host = probe_host_memory()
    assert report["workers_requested"] == 1
    assert report["workers_effective"] == 1
    assert report["requested_rss_mb"] == 100_000
    assert report["effective_rss_mb"] < report["requested_rss_mb"]
    assert report["effective_rss_mb"] <= 8 * 1024
    assert report["effective_max_unique"] <= 2_000_000
    assert report["effective_max_unique"] < report["requested_max_unique"]
    if int(host["available_bytes"]) > 0:
        cap = 0.40 * int(host["available_bytes"]) / (1024 * 1024)
        assert report["effective_rss_mb"] <= cap + 0.01


def test_manifest_replay_accepts_the_140_seed():
    manifest = verify_manifest_files(ROOT)
    assert manifest["seed"]["action_hash16"] == SEED_HASH
    assert verify_packaged_seed(ROOT) == 0


def test_campaign_directory_refuses_research_and_solutions():
    with pytest.raises(ValueError):
        assert_campaign_dir(ROOT / "docs" / "research" / "pre120_optimisation")
    with pytest.raises(ValueError):
        assert_campaign_dir(ROOT / "solutions")


def test_adoption_replays_and_lowers_the_target(tmp_path):
    campaign = OptimiserCampaign(tmp_path / "camp", root=ROOT)
    campaign.load()
    campaign.authenticate()
    assert campaign.campaign["incumbent_g"] == 140
    assert campaign.campaign["ceiling"] == 139
    campaign.campaign["incumbent_g"] = 141
    campaign.campaign["ceiling"] = 140
    destination = tmp_path / "camp" / "jobs" / "j9" / "search"
    destination.mkdir(parents=True)
    shutil.copyfile(ROOT / SEED, destination / "4925153_assisted_140.moves")
    campaign.adopt_files()
    assert campaign.campaign["incumbent_g"] == 140
    assert campaign.campaign["ceiling"] == 139
    assert campaign.campaign["best"]["path_hash16"] == SEED_HASH
    assert campaign.campaign["best"]["verified"] is True
    bad = destination / "4925153_assisted_10.moves"
    bad.write_text("move 1 1 99\n", encoding="utf-8")
    campaign.campaign["incumbent_g"] = 141
    campaign.adopt_files()
    assert campaign.campaign["incumbent_g"] == 140


def test_open_verified_best_preserves_session_history(tmp_path):
    session = PlaySession.from_deal(DEAL, path=tmp_path / "lab.json")
    session.act(session.state.enumerate_moves()[0])
    session.start_campaign("manual branch")
    nodes = set(session.nodes)
    campaigns = dict(session.campaigns)
    route_id = open_verified_route(session, ROOT / SEED)
    assert nodes <= set(session.nodes)
    assert set(campaigns) <= set(session.campaigns)
    assert session.campaigns[next(iter(campaigns))]["name"] == "manual branch"
    assert session.routes[route_id]["nodes"]
    assert session.active_campaign is None
    with pytest.raises(ValueError, match="4925153"):
        session.deal_id = "other"
        open_verified_route(session, ROOT / SEED)


def test_supervisor_runs_successive_jobs_pause_and_interruption(tmp_path):
    """The process chooses the next root itself. This does not search for a cheaper game."""

    before = RESEARCH_STATUS.read_bytes()
    directory = tmp_path / "unattended"
    directory.mkdir()
    settings = {
        "campaign_duration_s": 180,
        "attempt_time_limit_s": 5,
        "max_unique": 40,
        "requested_rss_mb": 512,
        "workers": 1,
    }
    control = directory / "control.json"
    control.write_text(json.dumps({
        "command": "run",
        "run_started_at": time.time(),
        "settings": settings,
    }), encoding="utf-8")
    log_handle = (directory / "supervisor.log").open("w", encoding="utf-8")
    process = subprocess.Popen(
        [sys.executable, str(ROOT / "tools" / "play_lab.py"),
         "--optimiser-supervisor", "--campaign", str(directory)],
        cwd=ROOT,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
    )
    deadline = time.time() + 180
    pause_sent = False
    try:
        while time.time() < deadline:
            payload = _campaign(directory)
            running = [job for job in payload.get("jobs") or [] if job.get("state") == "running"]
            finished = [job for job in payload.get("jobs") or [] if job.get("state") not in {None, "queued", "running"}]
            phase = payload.get("phase")
            if not pause_sent and running:
                _rewrite(control, "pause", settings)
                pause_sent = True
            if pause_sent and phase == "paused" and len(finished) == 1 and not running:
                break
            if process.poll() is not None:
                raise AssertionError("supervisor exited early:\n" + (directory / "supervisor.log").read_text(encoding="utf-8"))
            time.sleep(0.4)
        else:
            detail = (directory / "supervisor.log").read_text(encoding="utf-8")
            raise AssertionError(f"pause did not settle: {_campaign(directory)}\n{detail}")
        first = _campaign(directory)["jobs"][0]
        assert first["index"] == 100
        assert first["exhausted"] is False
        assert first["stop_reason"] in {"time limit", "unique limit", "rss abort"}
        _rewrite(control, "run", settings, started=_started(control))
        while time.time() < deadline:
            payload = _campaign(directory)
            running = [job for job in payload.get("jobs") or [] if job.get("state") == "running"]
            if any(job.get("index") == 90 for job in running):
                break
            if process.poll() is not None:
                raise AssertionError("supervisor exited before the second job:\n" + (directory / "supervisor.log").read_text(encoding="utf-8"))
            time.sleep(0.4)
        else:
            raise AssertionError(f"second job did not start: {_campaign(directory)}")
        process.kill()
        process.wait(timeout=20)
        from spider.unattended_optimiser import recover_campaign
        recovered = recover_campaign(directory, requested_stop=True)
        second = next(job for job in recovered["jobs"] if job["index"] == 90 and job["state"] != "queued")
        assert second["exhausted"] is False
        assert second["state"] == "stopped"
        assert "exact search frontier was not retained" in second["recovery"]
        assert all(not job.get("exhausted") for job in recovered["jobs"])
        assert recovered["jobs"][0]["index"] == 100
        assert recovered["jobs"][1]["index"] == 90 or second["index"] == 90
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=20)
        log_handle.close()
    assert RESEARCH_STATUS.read_bytes() == before


def _campaign(directory: Path) -> dict:
    path = directory / "campaign.json"
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _started(path: Path) -> float:
    return float(json.loads(path.read_text(encoding="utf-8"))["run_started_at"])


def _rewrite(path: Path, command: str, settings: dict, started=None) -> None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["command"] = command
    payload["settings"] = settings
    if started is not None:
        payload["run_started_at"] = started
    path.write_text(json.dumps(payload), encoding="utf-8")
