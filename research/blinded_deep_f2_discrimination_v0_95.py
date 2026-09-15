#!/usr/bin/env python3
"""v0.95: blinded lean deep evaluation of five existing F2 roots.

Search sees only state, g, and ceiling. Labels attached after freeze.
Canonical 172 is not a search input. The 187 suffix is not used.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.blinded_deep_f2 import (
    ROOT_NAMES,
    STAGE_A_CEILING,
    STAGE_A_S,
    STAGE_A_UNIQUE,
    STAGE_B_CEILING,
    STAGE_B_S,
    STAGE_B_UNIQUE,
    STAGE_C_CEILING,
    STAGE_C_N,
    STAGE_C_S,
    STAGE_C_UNIQUE,
    classify_root,
    choose_blinded_verdict,
    load_five_root_specs,
    next_recommendation,
    run_blinded_lean,
    search_spec,
    select_stage_c,
)
from spider.consequence_calibration_187 import KNOWN_ROUTE_GUIDANCE_USED
from spider.integrated_policy import AUTONOMOUS_INCUMBENT_MW, CANDIDATE_CEILING, verify_autonomous_192
from spider.long_horizon_f2_adjudication import reconstruct_active_root
from spider.metrics import CANONICAL_MW_COST, RECORD_MW_COST, replay_actions
from spider.packed_state import unpack_state
from spider.research_actions import as_actions, is_deal, stock_rows, tableau_actions
from spider.solution_forensics import load_opening
from spider.whole_game_epoch_scheduler import save_solution

EXPERIMENT = "blinded_deep_f2_discrimination_v0_95"
BASE_SHA = "936668320e301e6248d258cb5dcc65e7eb0261dc"
BRANCH = "agent/blinded-deep-f2-discrimination-v0-95"
RESULT = ROOT / "docs" / "research" / f"{EXPERIMENT}.json"
REPORT = ROOT / "docs" / "research" / f"{EXPERIMENT}.md"
PROG = ROOT / "docs" / "research" / "blinded_deep_f2_discrimination_progress_v0_95.json"
FIX = ROOT / "solutions" / "4925153_autonomous_v0_95.moves"
META = ROOT / "solutions" / "4925153_autonomous_v0_95.json"


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


def summarize_run(kr, obs, ceiling: int) -> dict:
    term_g = kr.first_g if kr.terminals else None
    deep_n = obs.max_F
    first = obs.first_F.get(deep_n) or {}
    cheap = obs.cheap_F.get(deep_n) or {}
    minf = obs.minf_F.get(deep_n) or {}
    return {
        "ceiling": ceiling,
        "solved": bool(kr.terminals),
        "terminal_g": term_g,
        "terminal_s": kr.first_s,
        "stop": kr.stop_reason,
        "max_F": obs.max_F,
        "first_deep_g": first.get("g"),
        "first_deep_h": first.get("h"),
        "first_deep_f": first.get("f"),
        "first_deep_s": first.get("elapsed_s"),
        "cheap_g": cheap.get("g"),
        "min_f": minf.get("f"),
        "unique": kr.unique,
        "expanded": kr.expanded,
        "generated": kr.generated,
        "bound_calls": kr.lower_bound_calls,
        "bound_prunes": kr.lower_bound_prunes,
        "elapsed_s": kr.elapsed_s,
        "n_progress": obs.n_progress,
    }


def replay_terminal(opening, post: dict, kr) -> dict:
    if not kr.terminals:
        return {"ok": False, "reason": "no_terminal"}
    term = kr.terminals[0]
    path = kr.reconstruct(int(term["node"]))
    st = unpack_state(bytes.fromhex(post["ordered_digest"]))
    try:
        g_from = replay_actions(st, list(path))
    except Exception as exc:
        return {"ok": False, "reason": f"from_root:{exc}"}
    full = as_actions(post.get("full_actions") or []) + list(path)
    end = opening.clone()
    try:
        g = replay_actions(end, list(full))
    except Exception as exc:
        return {"ok": False, "reason": f"opening:{exc}"}
    ok = (
        g == int(kr.first_g)
        and g_from is not None
        and int(g_from) + int(post["g"]) == int(kr.first_g)
        and end.is_solved()
        and sum(1 for a in full if is_deal(a)) == 5
        and len(end.foundations) == 8
        and not end.stock
        and all(c.is_empty() for c in end.columns)
    )
    return {"ok": bool(ok), "g": g, "g_from_root": g_from, "n_deal": sum(1 for a in full if is_deal(a)), "n_actions": len(full), "full_actions": full if ok else None}


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
        "Blinded lean evaluator. Labels attached after freeze. Canonical 172 absent.",
        "",
        "## Roots",
        "",
        str(p.get("roots")),
        "",
        "## Stage A ceiling 186 / 30s",
        "",
        "| root | solved | g | maxF | unique | stop |",
        "| ---- | ------ | -: | ---: | -----: | ---- |",
    ]
    for row in p.get("rows") or []:
        a = row.get("stage_a") or {}
        lines.append(f"| {row.get('name')} | {a.get('solved')} | {a.get('terminal_g')} | {a.get('max_F')} | {a.get('unique')} | {a.get('stop')} |")
    lines += [
        "",
        "## Stage B ceiling 187 / 45s",
        "",
        "| root | solved | g | t | maxF | unique | class |",
        "| ---- | ------ | -: | -: | ---: | -----: | ----- |",
    ]
    for row in p.get("rows") or []:
        b = row.get("stage_b") or {}
        lines.append(
            f"| {row.get('name')} | {b.get('solved')} | {b.get('terminal_g')} | {_fmt(b.get('terminal_s'))} | "
            f"{b.get('max_F')} | {b.get('unique')} | {row.get('cls')} |"
        )
    lines += [
        "",
        "## Stage C",
        "",
        str(p.get("stage_c")),
        "",
        "## Deep vs shallow",
        "",
        str(p.get("deep_vs_shallow")),
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
    inc = verify_autonomous_192(opening)
    if not inc.get("ok"):
        payload = {"verdict": "BLINDED_F2_CONTRACT_FAILURE", "root_fail": True, "contract_reason": "incumbent replay failed"}
        _write_json(RESULT, payload)
        write_report(payload)
        print("VERDICT BLINDED_F2_CONTRACT_FAILURE", flush=True)
        print("DONE", flush=True)
        return payload

    print("RESOLVE five F2 roots", flush=True)
    specs = load_five_root_specs()
    posts = []
    for spec in specs:
        post = reconstruct_active_root(opening, spec)
        st = unpack_state(bytes.fromhex(post["ordered_digest"]))
        ok = (
            post.get("verify_ok")
            and int(post.get("g") or 0) == int(spec.get("post_g") or spec.get("g") or post.get("g"))
            and len(st.foundations) == 2
            and stock_rows(st) == 0
            and not st.can_deal()
            and not any(is_deal(a) for a in tableau_actions(st))
            and int(post.get("n_deal") or 0) == 5
        )
        print(f"  {spec.get('name')} ok={ok} g={post.get('g')} h={post.get('assembly_h')} f={post.get('assembly_f')} deals={post.get('n_deal')}", flush=True)
        if not ok:
            payload = {"verdict": "BLINDED_F2_CONTRACT_FAILURE", "root_fail": True, "contract_reason": f"{spec.get('name')} reconstruct failed"}
            _write_json(RESULT, payload)
            write_report(payload)
            print("VERDICT BLINDED_F2_CONTRACT_FAILURE", flush=True)
            print("DONE", flush=True)
            return payload
        post["book_name"] = spec.get("name")
        posts.append(post)

    freeze = [
        {"id": i, "name": p["book_name"], "g": p["g"], "h": p.get("assembly_h"), "f": p.get("assembly_f"), "digest": p["ordered_digest"], "ident": p.get("ident")}
        for i, p in enumerate(posts)
    ]
    _write_json(PROG, {"phase": "frozen", "roots": freeze})
    print("FROZEN identities; searches are unlabeled", flush=True)

    # Stage A
    stage_a = []
    kernels_a = []
    for post in posts:
        spec = search_spec(post)
        print(f"A unlabeled g={spec['g']} ceiling={STAGE_A_CEILING} t={STAGE_A_S}", flush=True)
        kr, obs = run_blinded_lean(post, ceiling=STAGE_A_CEILING, time_s=STAGE_A_S, max_unique=STAGE_A_UNIQUE)
        rec = summarize_run(kr, obs, STAGE_A_CEILING)
        rec["name"] = post["book_name"]
        stage_a.append(rec)
        kernels_a.append(kr)
        print(f"  {post['book_name']} solved={rec['solved']} g={rec['terminal_g']} maxF={rec['max_F']} stop={rec['stop']}", flush=True)

    # Stage B
    stage_b = []
    kernels_b = []
    for post in posts:
        spec = search_spec(post)
        print(f"B unlabeled g={spec['g']} ceiling={STAGE_B_CEILING} t={STAGE_B_S}", flush=True)
        kr, obs = run_blinded_lean(post, ceiling=STAGE_B_CEILING, time_s=STAGE_B_S, max_unique=STAGE_B_UNIQUE)
        rec = summarize_run(kr, obs, STAGE_B_CEILING)
        rec["name"] = post["book_name"]
        stage_b.append(rec)
        kernels_b.append(kr)
        print(f"  {post['book_name']} solved={rec['solved']} g={rec['terminal_g']} t={rec['terminal_s']} maxF={rec['max_F']}", flush=True)

    rows = []
    for i, post in enumerate(posts):
        a, b = stage_a[i], stage_b[i]
        cls = classify_root(a, b)
        rows.append({
            "name": post["book_name"],
            "start_g": post["g"],
            "start_h": post.get("assembly_h"),
            "start_f": post.get("assembly_f"),
            "post_digest": post.get("ordered_digest"),
            "stage_a": a,
            "stage_b": b,
            "cls": cls,
        })

    ctrl_b = next(r for r in rows if r["name"] == "CONTROL_187")
    calibration_failure = ctrl_b["cls"] != "CLASS_187" and not (ctrl_b["stage_a"].get("solved") and int(ctrl_b["stage_a"].get("terminal_g") or 10**9) <= 186)
    if calibration_failure:
        print("CALIBRATION FAILURE CONTROL_187 did not solve 187", flush=True)

    replays = {}
    for i, row in enumerate(rows):
        if row["stage_b"].get("solved"):
            replays[row["name"]] = replay_terminal(opening, posts[i], kernels_b[i])
            print(f"REPLAY {row['name']} ok={replays[row['name']].get('ok')} g={replays[row['name']].get('g')}", flush=True)
        if row["stage_a"].get("solved"):
            replays[row["name"] + "_186"] = replay_terminal(opening, posts[i], kernels_a[i])

    pick = None if calibration_failure else select_stage_c(rows)
    stage_c = None
    stage_c_replay = None
    if pick is not None:
        post = next(p for p in posts if p["book_name"] == pick["name"])
        print(f"C {pick['name']} ceiling={STAGE_C_CEILING} t={STAGE_C_S}", flush=True)
        kr, obs = run_blinded_lean(post, ceiling=STAGE_C_CEILING, time_s=STAGE_C_S, max_unique=STAGE_C_UNIQUE)
        stage_c = summarize_run(kr, obs, STAGE_C_CEILING)
        stage_c["name"] = pick["name"]
        print(f"  solved={stage_c['solved']} g={stage_c['terminal_g']} maxF={stage_c['max_F']}", flush=True)
        if kr.terminals:
            stage_c_replay = replay_terminal(opening, post, kr)
            print(f"  replay ok={stage_c_replay.get('ok')} g={stage_c_replay.get('g')}", flush=True)

    improved = False
    best_novel_g = None
    replay_ok = False
    if stage_c and stage_c.get("solved") and stage_c_replay and stage_c_replay.get("ok") and int(stage_c["terminal_g"]) <= 186:
        best_novel_g = int(stage_c["terminal_g"])
        replay_ok = True
        save_solution(stage_c_replay["full_actions"], FIX, g=best_novel_g, label="Autonomous v0.95 blinded F2")
        _write_json(META, {"g": best_novel_g, "replay_ok": True, "parent_incumbent": 187, "root": stage_c["name"], "canonical_input": False})
        improved = True
    for row in rows:
        if row["name"].startswith("NOVEL_") and row["cls"] == "CLASS_186" and row["stage_a"].get("solved"):
            rp = replays.get(row["name"] + "_186") or {}
            if rp.get("ok") and int(row["stage_a"]["terminal_g"]) <= 186:
                best_novel_g = int(row["stage_a"]["terminal_g"])
                replay_ok = True
                if rp.get("full_actions"):
                    save_solution(rp["full_actions"], FIX, g=best_novel_g, label="Autonomous v0.95 blinded F2")
                improved = True

    hist = {
        "CONTROL_187": {"shallow": "v0.84 fill / F2; v0.92 150s F3 f183; known 187"},
        "CONTROL_ROOT_A": {"shallow": "v0.84 lowest-f g128; v0.85–v0.91 attractive then dead F4s"},
        "NOVEL_A": {"shallow": "v0.84 lowest_h; v0.92 150s F4 f186 slack 0"},
        "NOVEL_B": {"shallow": "v0.84 pareto_balanced; v0.92 150s F3 f186 slack 0"},
        "NOVEL_C": {"shallow": "v0.84 highest_mobility; v0.92 150s stayed F2"},
    }
    deep_vs_shallow = []
    for row in rows:
        deep_vs_shallow.append({
            "root": row["name"],
            "old_shallow": hist.get(row["name"], {}).get("shallow"),
            "term_186": bool(row["stage_a"].get("solved")),
            "term_187": bool(row["stage_b"].get("solved")),
            "class": row["cls"],
        })

    classes = {r["name"]: r["cls"] for r in rows}
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
        "roots": freeze,
        "rows": [{k: v for k, v in r.items()} for r in rows],
        "classes": classes,
        "calibration_failure": calibration_failure,
        "stage_c": stage_c,
        "replays": {k: {kk: vv for kk, vv in v.items() if kk != "full_actions"} for k, v in replays.items()},
        "stage_c_replay": None if not stage_c_replay else {k: v for k, v in stage_c_replay.items() if k != "full_actions"},
        "deep_vs_shallow": deep_vs_shallow,
        "novel_le_186": improved,
        "best_novel_g": best_novel_g,
        "replay_ok": replay_ok,
        "incumbent_updated": improved,
        "envelope": {
            "stage_a_s": STAGE_A_S,
            "stage_a_ceiling": STAGE_A_CEILING,
            "stage_b_s": STAGE_B_S,
            "stage_b_ceiling": STAGE_B_CEILING,
            "stage_c_s": STAGE_C_S,
            "stage_c_n": STAGE_C_N,
        },
    }
    verdict, reason = choose_blinded_verdict(payload)
    payload["verdict"] = verdict
    payload["verdict_reason"] = reason
    payload["interpretation"] = reason
    payload["next_recommendation"] = next_recommendation(verdict)
    payload = _jsonable(payload)
    _write_json(RESULT, payload)
    write_report(payload)
    _write_json(PROG, {"phase": "complete", "verdict": verdict, "classes": classes})
    print(f"VERDICT {verdict}", flush=True)
    print("DONE", flush=True)
    return payload


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        payload = {"experiment": EXPERIMENT, "verdict": "BLINDED_F2_CONTRACT_FAILURE", "contract_reason": f"{type(exc).__name__}: {exc}"}
        try:
            _write_json(RESULT, payload)
            write_report(payload)
        except Exception:
            pass
        print("VERDICT BLINDED_F2_CONTRACT_FAILURE", flush=True)
        print("DONE", flush=True)
        raise
