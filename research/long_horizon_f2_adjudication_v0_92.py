#!/usr/bin/env python3
"""v0.92: long-horizon adjudication of the existing v0.84 F2 population.

Four independent 150s frozen searches: CONTROL_187 + three novel F2s.
Canonical 172 is not a search input. The 187 suffix is not used.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.f3_tactical_bridge import BRIDGE_CEILING
from spider.integrated_policy import AUTONOMOUS_INCUMBENT_MW, CANDIDATE_CEILING, verify_autonomous_192
from spider.long_horizon_f2_adjudication import (
    CALIBRATION_EXTRA_S,
    STAGE_A_S,
    STAGE_A_UNIQUE,
    STAGE_B_MAX_S,
    TOTAL_S,
    attach_historical_rollout,
    choose_f2_verdict,
    classify_search,
    identify_controls,
    load_v084_population,
    next_recommendation,
    novel_rank_key,
    reconstruct_active_root,
    search_one_f2,
    select_novel_roots,
)
from spider.metrics import CANONICAL_MW_COST, RECORD_MW_COST, replay_actions
from spider.proof_aware_tactical_bridge import recover_digest_path
from spider.research_actions import as_actions, is_deal
from spider.solution_forensics import load_opening
from spider.state_convergence import foundation_progression
from spider.whole_game_epoch_scheduler import SEARCH_RSS_MB, save_solution

EXPERIMENT = "long_horizon_f2_adjudication_v0_92"
BASE_SHA = "dbf02ff7da00aca9cc0174cf27cbe8c12a65c60d"
BRANCH = "agent/long-horizon-f2-adjudication-v0-92"
RESULT = ROOT / "docs" / "research" / f"{EXPERIMENT}.json"
REPORT = ROOT / "docs" / "research" / f"{EXPERIMENT}.md"
PROG = ROOT / "docs" / "research" / "long_horizon_f2_adjudication_progress_v0_92.json"
FIX = ROOT / "solutions" / "4925153_autonomous_v0_92.moves"
META = ROOT / "solutions" / "4925153_autonomous_v0_92.json"


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temp.replace(path)


def _jsonable(obj):
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, dict):
        return {str(k): _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    return obj


def _fmt(x, nd=1):
    if x is None:
        return "—"
    if isinstance(x, float):
        return f"{x:.{nd}f}"
    return str(x)


def slim_root(r: dict) -> dict:
    return {k: r.get(k) for k in (
        "name", "pre_g", "post_g", "g", "assembly_h", "assembly_f", "slack", "legal",
        "face_down", "empty_n", "foundations", "control_tag", "selection_reason",
        "post_digest", "pre_digest", "ident", "verify_ok", "n_deal", "tactical_target",
        "v084_selected", "v084_selection_role", "v084_short_liked",
    )}


def slim_sig(s: dict) -> dict:
    d = s.get("deepest") or {}
    return {
        "name": s.get("name"),
        "start_g": s.get("start_g"),
        "start_h": s.get("start_h"),
        "start_f": s.get("start_f"),
        "max_F": s.get("max_F"),
        "deepest_g": d.get("g"),
        "deepest_h": d.get("h"),
        "deepest_f": d.get("f"),
        "deepest_slack": d.get("slack"),
        "time_first_increase": s.get("time_first_increase"),
        "stop": s.get("stop_reason"),
        "status": s.get("status"),
        "unique": s.get("unique"),
        "expanded": s.get("expanded"),
        "elapsed_s": s.get("elapsed_s"),
        "solved": s.get("solved"),
        "calibration": s.get("calibration"),
    }


def write_report(p: dict) -> None:
    lines = [
        f"# {EXPERIMENT}",
        "",
        f"Verdict: `{p.get('verdict')}`",
        "",
        p.get("verdict_reason") or "",
        "",
        f"Branch: `{p.get('branch')}`  Base: `{p.get('base_sha')}`",
        "",
        "Long-horizon adjudication of the existing v0.84 F2 population. "
        "CONTROL_187 is calibration only. The 187 suffix was not used. Canonical 172 was not a search input.",
        "",
        "## Population",
        "",
        f"n_f2={p.get('n_f2')} n_unique_pre={p.get('n_unique_pre')} n_viable_post={p.get('n_viable_post')} "
        f"persisted_post={p.get('n_persisted_post')} pareto={p.get('n_pareto')} eligible={p.get('n_eligible')}",
        "",
        "## Selection freeze (before old rollout labels)",
        "",
        str(p.get("selection_freeze")),
        "",
        "## Historical short-rollout labels (after freeze)",
        "",
        str(p.get("historical_rollout")),
        "",
        "## Stage A 150s scorecard",
        "",
        "| root | start g/h/f | 150s maxF | deepest g/h/f | slack | stop | unique | expanded |",
        "| ---- | ----------- | --------: | ------------- | ----: | ---- | -----: | -------: |",
    ]
    for s in p.get("stage_a_scorecard") or []:
        lines.append(
            f"| {s.get('name')} | {s.get('start_g')}/{s.get('start_h')}/{s.get('start_f')} | {s.get('max_F')} | "
            f"{s.get('deepest_g')}/{s.get('deepest_h')}/{s.get('deepest_f')} | {s.get('deepest_slack')} | "
            f"{s.get('stop')} | {s.get('unique')} | {s.get('expanded')} |"
        )
    lines += [
        "",
        f"calibration_insufficient={p.get('calibration_insufficient')} extension={p.get('calibration_extension_s')}",
        "",
        "## Stage B",
        "",
        str(p.get("stage_b")),
        "",
        "## Old short vs new deep",
        "",
        str(p.get("short_vs_deep")),
        "",
        f"wall={_fmt(p.get('wall_s'))} maxF={p.get('max_foundations')}",
        "",
        "## Interpretation",
        "",
        p.get("interpretation") or "",
        "",
        "## Next recommendation",
        "",
        p.get("next_recommendation") or "",
        "",
    ]
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(str(x) for x in lines) + "\n", encoding="utf-8")


def _fail(reason: str, extra=None) -> dict:
    payload = {
        "experiment": EXPERIMENT,
        "root_fail": True,
        "verdict": "LONG_HORIZON_F2_CONTRACT_FAILURE",
        "contract_reason": reason,
    }
    if extra:
        payload.update(extra)
    _write_json(RESULT, _jsonable(payload))
    write_report(payload)
    print("VERDICT LONG_HORIZON_F2_CONTRACT_FAILURE", flush=True)
    print("DONE", flush=True)
    return payload


def main() -> dict:
    opening, _raw, _labels = load_opening()
    wall0 = time.perf_counter()
    print("VERIFY autonomous 187", flush=True)
    inc = verify_autonomous_192(opening)
    if not inc.get("ok") or int(inc.get("g") or 0) != 187:
        return _fail("incumbent 187 replay failed")

    pop = load_v084_population()
    print(f"POP n_f2={pop['n_f2']} unique_pre={pop['n_unique_pre']} persisted={pop['n_persisted_post']} pareto={pop['n_pareto']}", flush=True)
    if not pop.get("ok"):
        return _fail("v0.84 population counts mismatch", {"pop": {k: pop[k] for k in pop if k != "posts"}})

    print("FREEZE novel selection", flush=True)
    frozen = select_novel_roots(pop)
    if not frozen.get("ok"):
        return _fail(frozen.get("reason") or "selection failed")
    labelled = attach_historical_rollout(frozen)
    print(
        f"NOVEL_A g={frozen['novel_a']['post_g']} h={frozen['novel_a']['assembly_h']} f={frozen['novel_a']['assembly_f']} "
        f"legal={frozen['novel_a'].get('legal')}",
        flush=True,
    )
    print(
        f"NOVEL_B g={frozen['novel_b']['post_g']} h={frozen['novel_b']['assembly_h']} f={frozen['novel_b']['assembly_f']}",
        flush=True,
    )
    print(
        f"NOVEL_C g={frozen['novel_c']['post_g']} h={frozen['novel_c']['assembly_h']} f={frozen['novel_c']['assembly_f']} "
        f"legal={frozen['novel_c'].get('legal')}",
        flush=True,
    )
    print(f"ROLLOUT labels {labelled.get('historical_rollout')}", flush=True)

    ctrl = frozen["controls"]["control_187"]
    ctrl["name"] = "CONTROL_187"
    novels = [labelled["novel_a"], labelled["novel_b"], labelled["novel_c"]]
    active_specs = [ctrl] + novels
    reconstructed = []
    for rec in active_specs:
        print(f"RECONSTRUCT {rec.get('name')}", flush=True)
        post = reconstruct_active_root(opening, rec)
        print(
            f"  ok={post.get('verify_ok')} g={post.get('g')} h={post.get('assembly_h')} "
            f"f={post.get('assembly_f')} deals={post.get('n_deal')} reason={post.get('reason')}",
            flush=True,
        )
        if not post.get("verify_ok") and not post.get("ok"):
            return _fail(f"root reconstruct failed {rec.get('name')}", {"post": slim_root(post)})
        if not post.get("verify_ok"):
            return _fail(f"root verify failed {rec.get('name')}", {"post": slim_root(post)})
        n_deal = int(post.get("n_deal") or 0)
        if n_deal != 5:
            return _fail(f"{rec.get('name')} deals={n_deal} want 5")
        reconstructed.append(post)

    _write_json(PROG, {"phase": "stage_a", "roots": [r.get("name") for r in reconstructed]})
    stage_a = []
    for post in reconstructed:
        remain = TOTAL_S - (time.perf_counter() - wall0)
        t = min(STAGE_A_S, remain)
        if t < 1:
            print("STAGE A stop campaign", flush=True)
            break
        print(f"A {post.get('name')} g={post.get('g')} f={post.get('assembly_f')} t={t:.1f} independent TT", flush=True)
        res = search_one_f2(opening, post, time_s=t, unique=STAGE_A_UNIQUE)
        sig = classify_search(res, post)
        sig["_post"] = post
        stage_a.append(sig)
        print(
            f"  maxF={sig.get('max_F')} stop={sig.get('stop_reason')} status={sig.get('status')} "
            f"unique={sig.get('unique')}",
            flush=True,
        )

    ctrl_sig = next((s for s in stage_a if s.get("name") == "CONTROL_187"), {})
    calibration_insufficient = int(ctrl_sig.get("max_F") or 0) < 4
    extension_s = 0.0
    if calibration_insufficient:
        remain = TOTAL_S - (time.perf_counter() - wall0)
        extra = min(CALIBRATION_EXTRA_S, remain)
        print(f"CALIBRATION_INSUFFICIENT CONTROL_187 maxF={ctrl_sig.get('max_F')} extra={extra:.1f}", flush=True)
        if extra >= 1:
            post = next(p for p in reconstructed if p.get("name") == "CONTROL_187")
            res = search_one_f2(opening, post, time_s=extra, unique=STAGE_A_UNIQUE)
            sig = classify_search(res, post)
            sig["name"] = "CONTROL_187"
            sig["_post"] = post
            sig["calibration_extension"] = True
            ctrl_sig = sig
            extension_s = extra
            print(f"  after extra maxF={sig.get('max_F')} stop={sig.get('stop_reason')}", flush=True)
            calibration_insufficient = int(sig.get("max_F") or 0) < 4

    novel_sigs = [s for s in stage_a if s.get("name") != "CONTROL_187"]
    ranked = sorted(novel_sigs, key=novel_rank_key)
    stage_b = None
    remain = max(0.0, TOTAL_S - (time.perf_counter() - wall0))
    chosen = None
    if ranked and remain >= 5:
        chosen = next((s for s in ranked if s.get("status") != "LONG_HORIZON_DEAD"), None)
        if chosen is None:
            print("STAGE B skip all novels dead", flush=True)
        else:
            t_b = min(STAGE_B_MAX_S, remain)
            post = chosen["_post"]
            print(f"B {chosen.get('name')} fresh search t={t_b:.1f}", flush=True)
            res = search_one_f2(opening, post, time_s=t_b, unique=STAGE_A_UNIQUE)
            stage_b = classify_search(res, post)
            stage_b["name"] = chosen.get("name")
            print(f"  maxF={stage_b.get('max_F')} stop={stage_b.get('stop_reason')} status={stage_b.get('status')}", flush=True)

    short_vs_deep = []
    hist = labelled.get("historical_rollout") or {}
    for s in [ctrl_sig] + novel_sigs:
        name = s.get("name")
        key = {"CONTROL_187": "control_187", "NOVEL_A": "novel_a", "NOVEL_B": "novel_b", "NOVEL_C": "novel_c"}.get(name)
        lab = hist.get(key) or {}
        ext = stage_b if stage_b and stage_b.get("name") == name else None
        short_vs_deep.append({
            "root": name,
            "old_short_role": lab.get("role") or lab.get("stage_a_roles"),
            "old_short_maxF": lab.get("stage_a_maxF"),
            "old_liked": bool(lab.get("role") not in (None, "fill") if isinstance(lab.get("role"), str) else lab.get("selected")),
            "stage_a_maxF": s.get("max_F"),
            "extended_maxF": None if not ext else ext.get("max_F"),
            "status": (ext or s).get("status"),
        })

    improved = False
    replay_ok = False
    replay_g = None
    novel_solution_g = None
    terminal_lineage = None
    cand = stage_b if stage_b and stage_b.get("solved") else next((s for s in ranked if s.get("solved")), None)
    if cand and cand.get("solution_g") is not None and int(cand["solution_g"]) < 187 and cand.get("name") != "CONTROL_187":
        post = next((p for p in reconstructed if p.get("name") == cand.get("name")), None)
        deep = cand.get("deepest") or {}
        if post and deep.get("g"):
            recov = recover_digest_path(opening, post, post.get("ordered_digest"), int(post.get("g")))
            # solution actions live on search result; skip if we only have classify dict
            novel_solution_g = int(cand["solution_g"])

    payload = {
        "experiment": EXPERIMENT,
        "base_sha": BASE_SHA,
        "branch": BRANCH,
        "policy_reads_canonical": False,
        "incumbent_g": AUTONOMOUS_INCUMBENT_MW,
        "candidate_ceiling": CANDIDATE_CEILING,
        "record_mw": RECORD_MW_COST,
        "canonical_mw": CANONICAL_MW_COST,
        "wall_s": time.perf_counter() - wall0,
        "n_f2": pop["n_f2"],
        "n_unique_pre": pop["n_unique_pre"],
        "n_viable_post": pop["n_viable_post"],
        "n_persisted_post": pop["n_persisted_post"],
        "n_pareto": frozen["n_pareto"],
        "n_eligible": frozen["n_eligible"],
        "selection_frozen_before_rollout": True,
        "selection_freeze": {
            "NOVEL_A": slim_root(frozen["novel_a"]),
            "NOVEL_B": slim_root(frozen["novel_b"]),
            "NOVEL_C": slim_root(frozen["novel_c"]),
        },
        "historical_rollout": labelled.get("historical_rollout"),
        "active_roots": [slim_root(p) for p in reconstructed],
        "stage_a_scorecard": [slim_sig(s) for s in stage_a],
        "control_sig": slim_sig(ctrl_sig) if ctrl_sig else {},
        "novel_sigs": [slim_sig(s) for s in novel_sigs],
        "calibration_insufficient": bool(calibration_insufficient),
        "calibration_extension_s": extension_s,
        "stage_b": None if not stage_b else slim_sig(stage_b),
        "short_vs_deep": short_vs_deep,
        "max_foundations": max([int(s.get("max_F") or 0) for s in stage_a + ([stage_b] if stage_b else [])] or [2]),
        "solved": False,
        "replay_ok": replay_ok,
        "novel_solution_g": novel_solution_g,
        "accounting_fail": False,
        "envelope": {
            "time_s": TOTAL_S,
            "stage_a_s": STAGE_A_S,
            "stage_a_n": 4,
            "unique": STAGE_A_UNIQUE,
            "ceiling": BRIDGE_CEILING,
            "rss_abort_mb": SEARCH_RSS_MB,
            "independent_tt": True,
        },
    }
    payload["novel_sigs"] = [slim_sig(s) for s in novel_sigs]
    if stage_b:
        payload["novel_sigs"] = [
            slim_sig(stage_b) if s.get("name") == stage_b.get("name") else slim_sig(s) for s in novel_sigs
        ]
    verdict, reason = choose_f2_verdict(payload)
    payload["verdict"] = verdict
    payload["verdict_reason"] = reason
    payload["interpretation"] = reason
    payload["next_recommendation"] = next_recommendation(verdict)
    payload = _jsonable(payload)
    _write_json(RESULT, payload)
    write_report(payload)
    _write_json(PROG, {"phase": "complete", "verdict": verdict, "max_F": payload.get("max_foundations")})
    print(f"VERDICT {verdict}", flush=True)
    print("DONE", flush=True)
    return payload


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        payload = {
            "experiment": EXPERIMENT,
            "verdict": "LONG_HORIZON_F2_CONTRACT_FAILURE",
            "contract_reason": f"{type(exc).__name__}: {exc}",
        }
        try:
            _write_json(RESULT, payload)
            write_report(payload)
        except Exception:
            pass
        print("VERDICT LONG_HORIZON_F2_CONTRACT_FAILURE", flush=True)
        print("DONE", flush=True)
        raise
