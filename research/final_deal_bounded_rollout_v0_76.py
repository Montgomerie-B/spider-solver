#!/usr/bin/env python3
"""v0.76: bounded stock-empty rollout of final-Deal roots.

Pilot only. Canonical 172 is evaluation after the machine experiment is frozen.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.autonomous_continuations import build_autonomous_continuation_table
from spider.final_deal_rollout import (
    ROLLOUT_CEILING,
    ROLLOUT_RSS_MB,
    ROLLOUT_TIME_S,
    ROLLOUT_UNIQUE,
    apply_sd5,
    choose_rollout_verdict,
    control_pre_sd5,
    pre_sd5_from_actions,
    reconstruct_tactical_f2,
    rollout_key,
    run_rollout,
    select_pilot_roots,
)
from spider.integrated_policy import AUTONOMOUS_INCUMBENT_MW, CANDIDATE_CEILING
from spider.metrics import CANONICAL_MW_COST, RECORD_MW_COST, parse_moves_file, replay_actions
from spider.research_actions import as_actions, is_deal
from spider.solution_forensics import load_opening
from spider.whole_game_epoch_scheduler import save_solution

EXPERIMENT = "final_deal_bounded_rollout_v0_76"
BASE_SHA = "e4d7617745be291326c0200741c04da72339f11e"
BRANCH = "agent/final-deal-bounded-rollout-v0-76"
RESULT = ROOT / "docs" / "research" / f"{EXPERIMENT}.json"
REPORT = ROOT / "docs" / "research" / f"{EXPERIMENT}.md"
PROG = ROOT / "docs" / "research" / "final_deal_bounded_rollout_progress_v0_76.json"
FIX = ROOT / "solutions" / "4925153_autonomous_v0_76.moves"
META = ROOT / "solutions" / "4925153_autonomous_v0_76.json"
CANON = ROOT / "solutions" / "4925153_canonical.moves"


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


def slim_sig(sig: dict) -> dict:
    skip = {"solution_actions"}
    return {k: v for k, v in sig.items() if k not in skip}


def static_rank(posts: list) -> list:
    return sorted(posts, key=lambda p: (int(p["assembly_f"]), -int(p["legal"]), int(p["boundaries"]), p["post_digest"]))


def write_report(p: dict) -> None:
    lines = [
        f"# {EXPERIMENT}",
        "",
        f"Verdict: `{p.get('verdict')}`",
        "",
        p.get("verdict_reason") or "",
        "",
        "## Selected roots",
        "",
        str(p.get("static_preview") or []),
        "",
        "## Rollout envelope",
        "",
        str(p.get("envelope") or {}),
        "",
        "## Per-root rollouts",
        "",
        str(p.get("signatures") or []),
        "",
        "## Rollout-key ranking",
        "",
        str(p.get("ranking_roles") or []),
        "",
        "## Controls 187/192/198",
        "",
        str(p.get("control_comparison") or {}),
        "",
        "## g128 vs g129/187",
        "",
        str(p.get("f2_comparison") or {}),
        "",
        "## One-step vs rollout",
        "",
        f"static={p.get('static_order_roles')} rollout={p.get('ranking_roles')}",
        "",
        "## Canonical calibration (after freeze)",
        "",
        str(p.get("canonical") or {}),
        "",
        "## Performance",
        "",
        str(p.get("performance") or {}),
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


def next_recommendation(verdict: str) -> str:
    if verdict == "ROLLOUT_COST_IMPROVED":
        return "Promote the new autonomous solution before integration work."
    if verdict in ("ROLLOUT_SIGNAL_STRONGLY_DISCRIMINATES", "ROLLOUT_SIGNAL_USEFUL"):
        return "v0.77 should integrate bounded post-Deal rollout into final-Deal root selection inside the existing whole-game time envelope."
    if verdict == "ROLLOUT_SIGNAL_TOO_SHALLOW":
        return "Do not simply increase whole-game runtime; first improve rollout efficiency or use progressive allocation."
    if verdict == "ROLLOUT_SIGNAL_STATIC_EQUIVALENT":
        return "Drop rollout integration and revisit a cheaper future-value representation."
    if verdict == "ROLLOUT_SIGNAL_MISLEADING":
        return "Do not use short rollout for final-Deal selection."
    return "Do not promote; diagnose the contract discrepancy."


def main() -> dict:
    opening, _raw, _labels = load_opening()
    t_setup = time.perf_counter()
    print("BUILD table and select 8 machine-only final-Deal roots", flush=True)
    table = build_autonomous_continuation_table(opening)
    roots = select_pilot_roots(opening, table=table, n=8)
    setup_s = time.perf_counter() - t_setup
    preview = [
        {
            "role": r.get("role"),
            "pre_g": r["pre_g"],
            "post_g": r["post_g"],
            "F": r["foundations"],
            "fd": r["face_down"],
            "legal": r["legal"],
            "h": r["assembly_h"],
            "f": r["assembly_f"],
            "boundaries": r["boundaries"],
            "empty": r["empty_n"],
        }
        for r in roots
    ]
    print("ROOTS", [(p["role"], p["post_g"], p["F"], p["h"], p["f"]) for p in preview], flush=True)
    _write_json(PROG, {"phase": "roots_selected", "n": len(roots), "roles": [p["role"] for p in preview]})

    print(f"ROLLOUT {len(roots)} roots x {ROLLOUT_TIME_S}s unique={ROLLOUT_UNIQUE} ceiling={ROLLOUT_CEILING}", flush=True)
    signatures = []
    t_roll = time.perf_counter()
    bound_s = 0.0
    peak = None
    for i, post in enumerate(roots):
        print(f"  root {i+1}/{len(roots)} {post.get('role')} post_g={post['post_g']}", flush=True)
        sig = run_rollout(opening, post)
        bound_s += float(sig.get("proof_prunes") or 0)
        if sig.get("peak_rss_mb") is not None:
            peak = sig["peak_rss_mb"] if peak is None else max(peak, sig["peak_rss_mb"])
        signatures.append(sig)
        _write_json(
            PROG,
            {
                "phase": "rolling",
                "done": i + 1,
                "role": sig.get("role"),
                "max_F": sig.get("max_F"),
                "solved": sig.get("solved"),
            },
        )
        print(
            f"    stop={sig['stop_reason']} unique={sig['unique']} exp={sig['expanded']} "
            f"maxF={sig['max_F']} min_f={sig['min_f']} solved={sig['solved']} t={sig['elapsed_s']:.1f}s",
            flush=True,
        )
    roll_s = time.perf_counter() - t_roll

    ranked = sorted(signatures, key=lambda s: tuple(s.get("rollout_key") or rollout_key(s)))
    ranking_roles = [s.get("role") for s in ranked]
    static_order = [p.get("role") for p in static_rank(roots)]
    ctrl = {s.get("role"): s for s in signatures}
    known_remaining = {"ctrl_187": 57, "ctrl_192": 57, "ctrl_198": 67}
    control_rank = [r for r in ranking_roles if r in known_remaining]
    misleading = False
    if "ctrl_198" in control_rank and "ctrl_187" in control_rank:
        if control_rank.index("ctrl_198") < control_rank.index("ctrl_187"):
            misleading = True
    f2c = {
        "g128": slim_sig(ctrl.get("tactical_f2_g128") or {}),
        "g129_187": slim_sig(ctrl.get("ctrl_187") or {}),
        "prefer": None,
    }
    if "tactical_f2_g128" in ranking_roles and "ctrl_187" in ranking_roles:
        f2c["prefer"] = (
            "g128"
            if ranking_roles.index("tactical_f2_g128") < ranking_roles.index("ctrl_187")
            else "g129_187"
        )

    improved = None
    for sig in ranked:
        if sig.get("solved") and sig.get("terminal_g") is not None and int(sig["terminal_g"]) < 187:
            improved = sig
            break
    replay_ok = False
    replay_g = None
    if improved and improved.get("solution_actions"):
        acts = as_actions(improved["solution_actions"])
        end = opening.clone()
        replay_g = replay_actions(end, acts)
        replay_ok = (
            replay_g == int(improved["terminal_g"])
            and end.is_solved()
            and sum(1 for a in acts if is_deal(a)) == 5
        )
        if replay_ok:
            save_solution(
                acts,
                FIX,
                g=int(improved["terminal_g"]),
                label="Autonomous v0.76 bounded final-Deal rollout",
            )
            _write_json(
                META,
                {
                    "g": int(improved["terminal_g"]),
                    "replay_g": replay_g,
                    "replay_ok": True,
                    "role": improved.get("role"),
                    "canonical_input": False,
                    "incumbent_parent": 187,
                },
            )

    payload = {
        "experiment": EXPERIMENT,
        "base_sha": BASE_SHA,
        "branch": BRANCH,
        "policy_reads_canonical": False,
        "incumbent_g": AUTONOMOUS_INCUMBENT_MW,
        "candidate_ceiling": CANDIDATE_CEILING,
        "record_mw": RECORD_MW_COST,
        "canonical_mw": CANONICAL_MW_COST,
        "static_preview": preview,
        "static_order_roles": static_order,
        "signatures": [slim_sig(s) for s in signatures],
        "ranking": [slim_sig(s) for s in ranked],
        "ranking_roles": ranking_roles,
        "control_comparison": {
            "known_remaining": known_remaining,
            "rollout_order": control_rank,
            "by_role": {k: slim_sig(v) for k, v in ctrl.items() if k in known_remaining},
        },
        "f2_comparison": f2c,
        "one_step_differs": static_order != ranking_roles,
        "misleading": misleading,
        "solved": bool(improved and replay_ok),
        "replay_ok": replay_ok,
        "replay_g": replay_g,
        "best_complete_g": None if not improved else improved.get("terminal_g"),
        "envelope": {
            "time_s": ROLLOUT_TIME_S,
            "unique": ROLLOUT_UNIQUE,
            "rss_abort_mb": ROLLOUT_RSS_MB,
            "ceiling": ROLLOUT_CEILING,
            "n_roots": len(roots),
        },
        "performance": {
            "setup_s": setup_s,
            "rollout_s": roll_s,
            "peak_rss_mb": peak,
            "per_root": [
                {
                    "role": s.get("role"),
                    "elapsed_s": s.get("elapsed_s"),
                    "expanded": s.get("expanded"),
                    "exp_per_s": None
                    if not s.get("elapsed_s")
                    else (s.get("expanded") or 0) / float(s["elapsed_s"]),
                    "proof_prunes": s.get("proof_prunes"),
                }
                for s in signatures
            ],
        },
    }
    verdict, reason = choose_rollout_verdict(payload)
    payload["verdict"] = verdict
    payload["verdict_reason"] = reason
    payload["interpretation"] = reason
    payload["next_recommendation"] = next_recommendation(verdict)
    _write_json(RESULT, _jsonable({k: v for k, v in payload.items() if k != "canonical"}))
    _write_json(PROG, {"phase": "machine_frozen", "verdict": verdict, "ranking": ranking_roles})
    write_report(_jsonable(payload))
    print("machine experiment frozen", flush=True)

    print("EVAL canonical after search", flush=True)
    canon_pre = pre_sd5_from_actions(opening, parse_moves_file(CANON))
    canon_pre["tag"] = "canonical"
    canon_post = apply_sd5(opening, canon_pre)
    canon_post["role"] = "canonical"
    canon_sig = run_rollout(opening, canon_post)
    canon_key = tuple(canon_sig.get("rollout_key") or rollout_key(canon_sig))
    machine_keys = [tuple(s.get("rollout_key") or []) for s in ranked]
    rank_among = 1 + sum(1 for k in machine_keys if k < canon_key)
    payload["canonical"] = {
        "pre_g": canon_post.get("pre_g"),
        "post_g": canon_post.get("post_g"),
        "F": canon_post.get("foundations"),
        "fd": canon_post.get("face_down"),
        "legal": canon_post.get("legal"),
        "h": canon_post.get("assembly_h"),
        "f": canon_post.get("assembly_f"),
        "signature": slim_sig(canon_sig),
        "rank_among_machine_plus_one": rank_among,
        "n_machine": len(ranked),
    }
    payload = _jsonable(payload)
    _write_json(RESULT, payload)
    write_report(payload)
    _write_json(
        PROG,
        {
            "phase": "complete",
            "verdict": verdict,
            "ranking": ranking_roles,
            "canonical_rank": rank_among,
        },
    )
    print(f"VERDICT {verdict}", flush=True)
    print("DONE", flush=True)
    return payload


if __name__ == "__main__":
    main()
