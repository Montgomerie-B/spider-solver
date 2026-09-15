#!/usr/bin/env python3
"""v0.97: focused ceiling-186 lean search of the v0.96 F5 F2 candidate.

One root. No new candidates. Canonical 172 is not a search input.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.blinded_deep_f2 import run_blinded_lean, search_spec
from spider.consequence_calibration_187 import KNOWN_ROUTE_GUIDANCE_USED
from spider.f5_production_candidate import (
    PRIMARY_CEILING,
    PRIMARY_S,
    PRIMARY_UNIQUE,
    audit_closed,
    choose_verdict,
    next_recommendation,
    resolve_v096_f5_root,
)
from spider.integrated_policy import AUTONOMOUS_INCUMBENT_MW, CANDIDATE_CEILING, verify_autonomous_192
from spider.metrics import CANONICAL_MW_COST, RECORD_MW_COST, replay_actions
from spider.packed_state import unpack_state
from spider.research_actions import as_actions, is_deal
from spider.solution_forensics import load_opening
from spider.whole_game_epoch_scheduler import SEARCH_RSS_MB, save_solution

EXPERIMENT = "f5_production_candidate_v0_97"
BASE_SHA = "b8384fdd35cf283030acb958dedcf39283a989f8"
BRANCH = "agent/f5-production-candidate-v0-97"
RESULT = ROOT / "docs" / "research" / f"{EXPERIMENT}.json"
REPORT = ROOT / "docs" / "research" / f"{EXPERIMENT}.md"
PROG = ROOT / "docs" / "research" / "f5_production_candidate_progress_v0_97.json"
FIX = ROOT / "solutions" / "4925153_autonomous_v0_97.moves"
META = ROOT / "solutions" / "4925153_autonomous_v0_97.json"


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


def slim_F(store: dict) -> dict:
    return {
        str(k): {kk: rec.get(kk) for kk in ("g", "h", "f", "elapsed_s", "ident", "foundations")}
        for k, rec in sorted(store.items())
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
        "One ORIGINAL_G123 F2, ceiling 186, lean evaluator, 240 s max. Canonical 172 absent.",
        "",
        "## Candidate",
        "",
        str(p.get("root")),
        "",
        f"distinct_from_CONTROL_187={p.get('distinct_187')} n_deal={p.get('n_deal')}",
        "",
        "## Envelope",
        "",
        f"ceiling={PRIMARY_CEILING} t={PRIMARY_S}s unique={PRIMARY_UNIQUE} stop_on_terminal=True",
        "",
        "## Milestones",
        "",
        "| F | first t | first g/h/f | cheapest g | lowest f |",
        "| -: | ------: | ----------- | ---------: | -------: |",
    ]
    first = p.get("first_F") or {}
    cheap = p.get("cheap_F") or {}
    minf = p.get("minf_F") or {}
    for n in range(2, 9):
        fr = first.get(str(n)) or {}
        cr = cheap.get(str(n)) or {}
        mr = minf.get(str(n)) or {}
        if not fr and not cr:
            continue
        lines.append(
            f"| {n} | {_fmt(fr.get('elapsed_s'))} | {fr.get('g')}/{fr.get('h')}/{fr.get('f')} | "
            f"{cr.get('g')} | {mr.get('f')} |"
        )
    lines += [
        "",
        f"F5 reproduced={p.get('f5_reproduced')} stop=`{p.get('stop_reason')}` unique={p.get('unique')} "
        f"maxF={p.get('max_foundations')} wall={_fmt(p.get('wall_s'))}",
        "",
        "## Known-closed audit",
        "",
        str(p.get("closed_audit")),
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
        payload = {"verdict": "F5_PRODUCTION_CONTRACT_FAILURE", "root_fail": True, "contract_reason": "incumbent replay failed"}
        _write_json(RESULT, payload)
        write_report(payload)
        print("VERDICT F5_PRODUCTION_CONTRACT_FAILURE", flush=True)
        print("DONE", flush=True)
        return payload

    print("RESOLVE v0.96 F5 ORIGINAL_G123 candidate", flush=True)
    root = resolve_v096_f5_root(opening)
    print(
        f"  ok={root.get('ok')} g={root.get('g')} h={root.get('assembly_h')} f={root.get('assembly_f')} "
        f"deals={root.get('n_deal')} distinct187={root.get('distinct', {}).get('CONTROL_187')} reason={root.get('reason')}",
        flush=True,
    )
    if not root.get("ok"):
        payload = {"verdict": "F5_PRODUCTION_CONTRACT_FAILURE", "root_fail": True, "contract_reason": root.get("reason")}
        _write_json(RESULT, payload)
        write_report(payload)
        print("VERDICT F5_PRODUCTION_CONTRACT_FAILURE", flush=True)
        print("DONE", flush=True)
        return payload

    _write_json(PROG, {"phase": "search", "g": root.get("g"), "f": root.get("assembly_f"), "ident": root.get("ident")})
    spec = search_spec(root)
    print(f"SEARCH unlabeled g={spec['g']} ceiling={PRIMARY_CEILING} t={PRIMARY_S}", flush=True)
    kr, obs = run_blinded_lean(root, ceiling=PRIMARY_CEILING, time_s=PRIMARY_S, max_unique=PRIMARY_UNIQUE)
    print(
        f"  stop={kr.stop_reason} g={kr.first_g} maxF={obs.max_F} unique={kr.unique} "
        f"F5t={(obs.first_F.get(5) or {}).get('elapsed_s')}",
        flush=True,
    )

    f5 = obs.first_F.get(5) or {}
    f5_reproduced = bool(obs.max_F >= 5 and f5.get("g") is not None)
    closed = audit_closed(obs)

    replay_ok = False
    replay_g = None
    improved = False
    if kr.terminals:
        path = kr.reconstruct(int(kr.terminals[0]["node"]))
        st = unpack_state(bytes.fromhex(root["ordered_digest"]))
        try:
            g_from = replay_actions(st, list(path))
        except Exception:
            g_from = None
        full = as_actions(root.get("full_actions") or []) + list(path)
        end = opening.clone()
        try:
            replay_g = replay_actions(end, list(full))
        except Exception:
            replay_g = None
        replay_ok = (
            replay_g == int(kr.first_g)
            and g_from is not None
            and int(g_from) + int(root["g"]) == int(kr.first_g)
            and end.is_solved()
            and sum(1 for a in full if is_deal(a)) == 5
            and len(end.foundations) == 8
            and not end.stock
        )
        print(f"  replay_ok={replay_ok} g={replay_g}", flush=True)
        if replay_ok and int(kr.first_g) <= 186:
            save_solution(full, FIX, g=int(kr.first_g), label="Autonomous v0.97 F5 production candidate")
            _write_json(
                META,
                {
                    "g": int(kr.first_g),
                    "replay_ok": True,
                    "parent_incumbent": 187,
                    "source_f1": "ORIGINAL_G123",
                    "post_sd5_g": root.get("g"),
                    "post_sd5_h": root.get("assembly_h"),
                    "post_sd5_f": root.get("assembly_f"),
                    "post_digest": root.get("ordered_digest"),
                    "canonical_input": False,
                },
            )
            improved = True

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
        "root": {
            "g": root.get("g"),
            "h": root.get("assembly_h"),
            "f": root.get("assembly_f"),
            "legal": root.get("legal"),
            "face_down": root.get("face_down"),
            "visible_runs": root.get("visible_runs"),
            "mixed_suit_boundaries": root.get("mixed_suit_boundaries"),
            "ident": root.get("ident"),
            "ordered_digest": root.get("ordered_digest"),
            "source_f1": "ORIGINAL_G123",
            "v096_signal": root.get("v096_signal"),
        },
        "distinct_187": root.get("distinct", {}).get("CONTROL_187"),
        "n_deal": root.get("n_deal"),
        "envelope": {"ceiling": PRIMARY_CEILING, "time_s": PRIMARY_S, "unique": PRIMARY_UNIQUE, "rss_abort_mb": SEARCH_RSS_MB, "n_roots": 1},
        "stop_reason": kr.stop_reason,
        "unique": kr.unique,
        "expanded": kr.expanded,
        "generated": kr.generated,
        "bound_calls": kr.lower_bound_calls,
        "bound_prunes": kr.lower_bound_prunes,
        "lanes": dict(kr.lane_exp),
        "horizon_exp": int((kr.lane_exp or {}).get("horizon") or 0),
        "first_F": slim_F(obs.first_F),
        "cheap_F": slim_F(obs.cheap_F),
        "minf_F": slim_F(obs.minf_F),
        "max_foundations": obs.max_F,
        "first_F5": {k: f5.get(k) for k in ("g", "h", "f", "elapsed_s")},
        "f5_reproduced": f5_reproduced,
        "closed_audit": closed,
        "solved": bool(kr.terminals),
        "solution_g": kr.first_g,
        "replay_ok": replay_ok,
        "replay_g": replay_g,
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
    _write_json(PROG, {"phase": "complete", "verdict": verdict, "max_F": obs.max_F, "stop": kr.stop_reason})
    print(f"VERDICT {verdict}", flush=True)
    print("DONE", flush=True)
    return payload


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        payload = {"experiment": EXPERIMENT, "verdict": "F5_PRODUCTION_CONTRACT_FAILURE", "contract_reason": f"{type(exc).__name__}: {exc}"}
        try:
            _write_json(RESULT, payload)
            write_report(payload)
        except Exception:
            pass
        print("VERDICT F5_PRODUCTION_CONTRACT_FAILURE", flush=True)
        print("DONE", flush=True)
        raise
