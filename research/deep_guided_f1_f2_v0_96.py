#!/usr/bin/env python3
"""v0.96: F1 preparation → F2 cash-out → lean deep consequence.

Canonical 172 is not a search input. CONTROL_187 suffix is not used.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.blinded_deep_f2 import load_five_root_specs
from spider.consequence_calibration_187 import KNOWN_ROUTE_GUIDANCE_USED
from spider.deep_guided_f1_f2 import (
    NOVEL_MAX,
    PREP_MAX_DG,
    PREP_S,
    PREP_UNIQUE,
    STAGE_A_CEILING,
    STAGE_A_S,
    STAGE_A_UNIQUE,
    STAGE_B_CEILING,
    STAGE_B_S,
    STAGE_B_UNIQUE,
    STAGE_C_CEILING,
    STAGE_C_S,
    STAGE_C_UNIQUE,
    TACTICAL_S,
    TACTICAL_UNIQUE,
    choose_stage_c,
    choose_verdict,
    classify_completion,
    f1_as_harvest_root,
    fresh_targets,
    known_post_idents,
    next_recommendation,
    post_sd5_record,
    retain_f2_terminals,
    route_pressure,
    select_novel_posts,
    select_prepared_f1s,
)
from spider.f2_quality_frontier import harvest_f2_target, verify_g123_root
from spider.integrated_policy import AUTONOMOUS_INCUMBENT_MW, CANDIDATE_CEILING, verify_autonomous_192
from spider.long_horizon_f2_adjudication import reconstruct_active_root
from spider.metrics import CANONICAL_MW_COST, RECORD_MW_COST, replay_actions
from spider.packed_state import unpack_state
from spider.post_f2_predeal_preparation import harvest_preparation
from spider.proof_aware_tactical_bridge import ExactHCache
from spider.research_actions import as_actions, is_deal, stock_rows, tableau_actions
from spider.solution_forensics import load_opening
from spider.whole_game_epoch_scheduler import save_solution
from spider.blinded_deep_f2 import run_blinded_lean, search_spec

EXPERIMENT = "deep_guided_f1_f2_v0_96"
BASE_SHA = "caf738cb0831c48d621bcd47b2b8fdce0ee01d69"
BRANCH = "agent/deep-guided-f1-f2-v0-96"
RESULT = ROOT / "docs" / "research" / f"{EXPERIMENT}.json"
REPORT = ROOT / "docs" / "research" / f"{EXPERIMENT}.md"
PROG = ROOT / "docs" / "research" / "deep_guided_f1_f2_progress_v0_96.json"
FIX = ROOT / "solutions" / "4925153_autonomous_v0_96.moves"
META = ROOT / "solutions" / "4925153_autonomous_v0_96.json"


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


def summarize(kr, obs, ceiling: int) -> dict:
    first = obs.first_F.get(obs.max_F) or {}
    return {
        "ceiling": ceiling,
        "solved": bool(kr.terminals),
        "terminal_g": kr.first_g if kr.terminals else None,
        "terminal_s": kr.first_s,
        "stop": kr.stop_reason,
        "max_F": obs.max_F,
        "first_deep_g": first.get("g"),
        "first_deep_f": first.get("f"),
        "unique": kr.unique,
        "expanded": kr.expanded,
        "generated": kr.generated,
        "elapsed_s": kr.elapsed_s,
    }


def replay_term(opening, post, kr) -> dict:
    if not kr.terminals:
        return {"ok": False}
    path = kr.reconstruct(int(kr.terminals[0]["node"]))
    st = unpack_state(bytes.fromhex(post["ordered_digest"]))
    try:
        g_from = replay_actions(st, list(path))
    except Exception:
        return {"ok": False, "reason": "from_root"}
    full = as_actions(post.get("full_actions") or []) + list(path)
    end = opening.clone()
    try:
        g = replay_actions(end, list(full))
    except Exception:
        return {"ok": False, "reason": "opening"}
    ok = (
        g == int(kr.first_g)
        and g_from is not None
        and int(g_from) + int(post["g"]) == int(kr.first_g)
        and end.is_solved()
        and sum(1 for a in full if is_deal(a)) == 5
        and len(end.foundations) == 8
    )
    return {"ok": bool(ok), "g": g, "g_from_root": g_from, "n_deal": sum(1 for a in full if is_deal(a)), "full_actions": full if ok else None}


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
        "## F1 root",
        "",
        str(p.get("g123")),
        "",
        f"prep n={p.get('n_prep')} incidental_f2={p.get('n_incidental')} selected_f1={p.get('n_f1')}",
        "",
        str(p.get("selected_f1")),
        "",
        "## Tactical F2",
        "",
        str(p.get("tactical_table")),
        "",
        f"post_sd5={p.get('n_post')} proof_dead={p.get('n_dead')} known_hits={p.get('n_known')} reopen={p.get('n_reopen')} novels={p.get('n_novel')}",
        "",
        "## Stage A 186 / 25s",
        "",
        str(p.get("stage_a")),
        "",
        "## Stage B 187 / 35s",
        "",
        str(p.get("stage_b")),
        "",
        f"classes={p.get('classes')} calibration_ok={not p.get('calibration_failure')}",
        "",
        "## Stage C",
        "",
        str(p.get("stage_c")),
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


def main() -> dict:
    opening, _raw, _labels = load_opening()
    wall0 = time.perf_counter()
    print("VERIFY incumbent 187", flush=True)
    if not verify_autonomous_192(opening).get("ok"):
        payload = {"verdict": "DEEP_GUIDED_F1_F2_CONTRACT_FAILURE", "root_fail": True, "contract_reason": "incumbent replay failed"}
        _write_json(RESULT, payload)
        write_report(payload)
        print("VERDICT DEEP_GUIDED_F1_F2_CONTRACT_FAILURE", flush=True)
        print("DONE", flush=True)
        return payload

    print("RESOLVE g123 F1", flush=True)
    g123 = verify_g123_root(opening)
    print(f"  ok={g123.get('ok')} g={g123.get('g')} F={g123.get('foundations')} rows={g123.get('stock_rows')} fd={g123.get('face_down')}", flush=True)
    if not g123.get("ok"):
        payload = {"verdict": "DEEP_GUIDED_F1_F2_CONTRACT_FAILURE", "root_fail": True, "contract_reason": g123.get("reason")}
        _write_json(RESULT, payload)
        write_report(payload)
        print("VERDICT DEEP_GUIDED_F1_F2_CONTRACT_FAILURE", flush=True)
        print("DONE", flush=True)
        return payload

    print(f"PREP tableau-only Δg<={PREP_MAX_DG} t={PREP_S}s", flush=True)
    ha = harvest_preparation(opening, f1_as_harvest_root(g123), time_s=PREP_S, unique=PREP_UNIQUE, max_dg=PREP_MAX_DG)
    cands = ha.get("candidates") or []
    incidental = [c for c in cands if int(c.get("foundations") or 1) >= 2]
    for rec in incidental:
        rec["f2_role"] = "INCIDENTAL_F2"
        rec["f1_source"] = "PREP"
        rec["prep_delta_g"] = rec.get("prep_delta_g")
    print(f"  archive={ha.get('n_archive')} unique={ha.get('unique')} incidental_f2={len(incidental)} stop={ha.get('stop_reason')}", flush=True)

    orig = {
        "g": g123["g"],
        "ordered_digest": g123["ordered_digest"],
        "full_actions": g123.get("prefix_actions"),
        "foundations": 1,
        "legal_tableau": g123.get("legal_tableau"),
        "face_down": g123.get("face_down"),
        "prep_delta_g": 0,
    }
    selected = select_prepared_f1s(cands, orig)
    print(f"F1 SELECT n={len(selected)} roles={[s.get('source_role') for s in selected]}", flush=True)
    _write_json(PROG, {"phase": "f1_frozen", "n": len(selected), "digests": [s["ordered_digest"][:16] for s in selected]})

    tactical_table = []
    retained = []
    for src in selected:
        tgts = fresh_targets(src["ordered_digest"], int(src["g"]))
        print(f"TARGETS {src.get('source_role')} {[t.get('suit') for t in tgts]}", flush=True)
        g123_like = {
            "g": src["g"],
            "ordered_digest": src["ordered_digest"],
            "prefix_actions": src.get("full_actions") or [],
        }
        for tgt in tgts:
            print(f"  F2 {src.get('source_role')} rank={tgt.get('operational_rank')} t={TACTICAL_S}", flush=True)
            hv = harvest_f2_target(g123_like, tgt, time_s=TACTICAL_S, unique=TACTICAL_UNIQUE)
            keep = retain_f2_terminals(hv.get("terminals") or [])
            for rec in keep:
                rec["f1_source"] = src.get("source_role")
                rec["prep_delta_g"] = src.get("prep_delta_g")
                retained.append(rec)
            tactical_table.append({
                "f1": src.get("source_role"),
                "suit_rank": tgt.get("operational_rank"),
                "n_f2": hv.get("n_f2"),
                "cheapest_g": hv.get("cheapest_g"),
                "kept": len(keep),
                "stop": hv.get("stop_reason"),
                "elapsed_s": hv.get("elapsed_s"),
            })
            print(f"    n_f2={hv.get('n_f2')} kept={len(keep)} stop={hv.get('stop_reason')}", flush=True)
    for rec in incidental:
        retained.append(rec)

    print(f"SD5 n={len(retained)}", flush=True)
    cache = ExactHCache()
    posts = []
    n_dead = 0
    for rec in retained:
        if int(rec.get("stock_rows") or 1) != 1:
            continue
        post = post_sd5_record(rec, cache)
        if post.get("proof_dead"):
            n_dead += 1
            continue
        if post.get("ok"):
            posts.append(post)
    known = known_post_idents()
    novels, hits, reopen = select_novel_posts(posts, known, k=NOVEL_MAX)
    print(f"  live_post={len(posts)} dead={n_dead} known={len(hits)} reopen={len(reopen)} novels={len(novels)}", flush=True)

    ctrl_spec = next(s for s in load_five_root_specs() if s.get("name") == "CONTROL_187")
    ctrl = reconstruct_active_root(opening, ctrl_spec)
    ctrl["book_name"] = "CONTROL_187"
    deep_posts = [ctrl]
    for i, rec in enumerate(novels):
        rec["book_name"] = rec.get("f1_source") or f"NOVEL_{i}"
        rec["g"] = rec.get("post_g") or rec.get("g")
        rec["ordered_digest"] = rec.get("post_digest") or rec.get("ordered_digest")
        deep_posts.append(rec)

    lower_g_control = any(r.get("reopened") and r.get("known_name") == "CONTROL_187" for r in reopen)

    # Stage A 186
    stage_a = []
    kA = []
    solved_186 = False
    for post in deep_posts:
        spec = search_spec(post)
        print(f"A unlabeled g={spec['g']} ceiling={STAGE_A_CEILING} t={STAGE_A_S}", flush=True)
        kr, obs = run_blinded_lean(post, ceiling=STAGE_A_CEILING, time_s=STAGE_A_S, max_unique=STAGE_A_UNIQUE)
        rec = summarize(kr, obs, STAGE_A_CEILING)
        rec["name"] = post["book_name"]
        stage_a.append(rec)
        kA.append(kr)
        print(f"  {post['book_name']} solved={rec['solved']} g={rec['terminal_g']} maxF={rec['max_F']}", flush=True)
        if rec["solved"] and rec["terminal_g"] is not None and int(rec["terminal_g"]) <= 186 and post["book_name"] != "CONTROL_187":
            solved_186 = True

    stage_b = []
    kB = []
    if not solved_186:
        for post in deep_posts:
            print(f"B unlabeled g={post['g']} ceiling={STAGE_B_CEILING} t={STAGE_B_S}", flush=True)
            kr, obs = run_blinded_lean(post, ceiling=STAGE_B_CEILING, time_s=STAGE_B_S, max_unique=STAGE_B_UNIQUE)
            rec = summarize(kr, obs, STAGE_B_CEILING)
            rec["name"] = post["book_name"]
            stage_b.append(rec)
            kB.append(kr)
            print(f"  {post['book_name']} solved={rec['solved']} g={rec['terminal_g']} t={rec['terminal_s']}", flush=True)
    else:
        print("SKIP Stage B; novel <=186 found", flush=True)

    rows = []
    for i, post in enumerate(deep_posts):
        a = stage_a[i]
        b = stage_b[i] if i < len(stage_b) else {"solved": False}
        rows.append({
            "name": post["book_name"],
            "start_g": post["g"],
            "start_f": post.get("assembly_f"),
            "post_digest": post.get("ordered_digest"),
            "prep_delta_g": post.get("prep_delta_g"),
            "stage_a": a,
            "stage_b": b,
            "cls": classify_completion(a, b),
        })

    ctrl_row = next(r for r in rows if r["name"] == "CONTROL_187")
    calibration_failure = (not solved_186) and ctrl_row["cls"] != "CLASS_187"
    pressures = {}
    if not calibration_failure:
        for i, row in enumerate(rows):
            if row["cls"] == "CLASS_187" and row["name"] != "CONTROL_187" and i < len(kB):
                pressures[row["name"]] = route_pressure(opening, deep_posts[i], kB[i], cache)

    pick = None if (solved_186 or calibration_failure) else choose_stage_c(rows, pressures)
    stage_c = None
    stage_c_replay = None
    if pick is not None:
        post = next(p for p in deep_posts if p["book_name"] == pick["name"])
        print(f"C {pick['name']} ceiling={STAGE_C_CEILING} t={STAGE_C_S}", flush=True)
        kr, obs = run_blinded_lean(post, ceiling=STAGE_C_CEILING, time_s=STAGE_C_S, max_unique=STAGE_C_UNIQUE)
        stage_c = summarize(kr, obs, STAGE_C_CEILING)
        stage_c["name"] = pick["name"]
        if kr.terminals:
            stage_c_replay = replay_term(opening, post, kr)

    improved = False
    best_novel_g = None
    replay_ok = False
    if stage_c and stage_c.get("solved") and stage_c_replay and stage_c_replay.get("ok") and int(stage_c["terminal_g"]) <= 186:
        best_novel_g = int(stage_c["terminal_g"])
        replay_ok = True
        save_solution(stage_c_replay["full_actions"], FIX, g=best_novel_g, label="Autonomous v0.96 deep-guided F1-F2")
        _write_json(META, {"g": best_novel_g, "replay_ok": True, "parent_incumbent": 187, "canonical_input": False})
        improved = True
    for i, row in enumerate(rows):
        if row["name"] != "CONTROL_187" and row["cls"] == "CLASS_186":
            rp = replay_term(opening, deep_posts[i], kA[i])
            if rp.get("ok"):
                best_novel_g = int(row["stage_a"]["terminal_g"])
                replay_ok = True
                if rp.get("full_actions"):
                    save_solution(rp["full_actions"], FIX, g=best_novel_g, label="Autonomous v0.96 deep-guided F1-F2")
                improved = True

    n_novel_187 = sum(1 for r in rows if r["name"] != "CONTROL_187" and r["cls"] == "CLASS_187")
    payload = {
        "experiment": EXPERIMENT,
        "base_sha": BASE_SHA,
        "branch": BRANCH,
        "known_route_guidance_used": KNOWN_ROUTE_GUIDANCE_USED,
        "incumbent_g": AUTONOMOUS_INCUMBENT_MW,
        "candidate_ceiling": CANDIDATE_CEILING,
        "record_mw": RECORD_MW_COST,
        "canonical_mw": CANONICAL_MW_COST,
        "wall_s": time.perf_counter() - wall0,
        "g123": {k: g123.get(k) for k in ("ok", "g", "foundations", "face_down", "stock_rows", "legal_tableau", "ordered_digest")},
        "n_prep": ha.get("n_archive"),
        "n_incidental": len(incidental),
        "n_f1": len(selected),
        "selected_f1": [{"role": s.get("source_role"), "g": s.get("g"), "dg": s.get("prep_delta_g"), "legal": s.get("legal_tableau")} for s in selected],
        "tactical_table": tactical_table,
        "n_post": len(posts),
        "n_dead": n_dead,
        "n_known": len(hits),
        "n_reopen": len(reopen),
        "n_novel": len(novels),
        "stage_a": stage_a,
        "stage_b": stage_b,
        "classes": {r["name"]: r["cls"] for r in rows},
        "calibration_failure": calibration_failure,
        "pressures": pressures,
        "stage_c": stage_c,
        "n_novel_187": n_novel_187,
        "lower_g_control": lower_g_control,
        "novel_le_186": improved,
        "best_novel_g": best_novel_g,
        "replay_ok": replay_ok,
        "deep_candidate": any(int((r.get("stage_b") or {}).get("max_F") or (r.get("stage_a") or {}).get("max_F") or 0) >= 5 for r in rows if r["name"] != "CONTROL_187"),
        "incumbent_updated": improved,
    }
    verdict, reason = choose_verdict(payload)
    payload["verdict"] = verdict
    payload["verdict_reason"] = reason
    payload["interpretation"] = reason
    payload["next_recommendation"] = next_recommendation(verdict)
    payload = _jsonable(payload)
    _write_json(RESULT, payload)
    write_report(payload)
    _write_json(PROG, {"phase": "complete", "verdict": verdict, "classes": payload["classes"]})
    print(f"VERDICT {verdict}", flush=True)
    print("DONE", flush=True)
    return payload


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        payload = {"experiment": EXPERIMENT, "verdict": "DEEP_GUIDED_F1_F2_CONTRACT_FAILURE", "contract_reason": f"{type(exc).__name__}: {exc}"}
        try:
            _write_json(RESULT, payload)
            write_report(payload)
        except Exception:
            pass
        print("VERDICT DEEP_GUIDED_F1_F2_CONTRACT_FAILURE", flush=True)
        print("DONE", flush=True)
        raise
