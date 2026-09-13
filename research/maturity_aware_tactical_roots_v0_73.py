#!/usr/bin/env python3
"""v0.73: maturity-aware tactical root selection.

Canonical 172 and the 192 suffix are evaluation only after search.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.assembly_policy import COMPLETION_LANES
from spider.autonomous_cost import checkpoints_from_trace
from spider.deal_preview import clear_preview_cache, preview_cache_stats
from spider.foundation_cashout import (
    replay_incumbent_suffix_for_eval,
    replay_to_stock_rows,
    require_eval_phase,
    search_foundation_cashout,
    select_tactical_target,
)
from spider.integrated_policy import AUTONOMOUS_INCUMBENT_MW, CANDIDATE_CEILING, load_autonomous_192, verify_autonomous_192
from spider.metrics import parse_moves_file, replay_actions
from spider.research_actions import is_deal
from spider.solution_forensics import load_opening
from spider.tactical_integration import (
    ROWS1_AUGMENT_FRACTION,
    STRATEGIC_LANES,
    TACTICAL_ROOT_LIMIT,
    TACTICAL_TERMINAL_LIMIT,
    analyse_tactical_root,
    choose_maturity_tactical_verdict,
    search_integrated_tactical,
    select_mature_tactical_roots,
    select_tactical_probe_roots,
)
from spider.whole_game_epoch_scheduler import (
    PORTFOLIO_WIDTH,
    SEARCH_RSS_MB,
    SEARCH_TIME_S,
    SEARCH_UNIQUE,
    reconcile_lower_bound_telemetry,
    save_solution,
)

EXPERIMENT = "maturity_aware_tactical_roots_v0_73"
BASE_SHA = "787773e55ce1ebf054f433ed9c89c7ce014c641d"
BRANCH = "agent/maturity-aware-tactical-roots-v0-73"
RESULT = ROOT / "docs" / "research" / f"{EXPERIMENT}.json"
REPORT = ROOT / "docs" / "research" / f"{EXPERIMENT}.md"
PROG = ROOT / "docs" / "research" / "maturity_aware_tactical_roots_progress_v0_73.json"
FIX = ROOT / "solutions" / "4925153_autonomous_v0_73.moves"
CANON = ROOT / "solutions" / "4925153_canonical.moves"
V067 = ROOT / "solutions" / "4925153_autonomous_v0_67.moves"
V072 = ROOT / "docs" / "research" / "integrated_tactical_cashout_v0_72.json"
CONT71 = ROOT / "docs" / "research" / "bounded_foundation_cashout_v0_71_continuation.json"


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


def slim_f(rec: dict) -> dict:
    if not rec:
        return {}
    return {
        k: rec.get(k)
        for k in (
            "g",
            "stock_rows",
            "face_down",
            "foundations",
            "foundation_suits",
            "empty_n",
            "legal_tableau",
            "boundaries_total",
            "best_ready_suit",
            "from_incumbent_ckpt",
            "portfolio_cat",
            "tactical_target",
            "tactical_delta_g",
            "control_slot",
            "maturity_rank",
            "ordered_digest",
            "post_assembly_h",
            "post_assembly_f",
            "assembly_h",
            "elapsed_s",
        )
    }


def slim_epoch(ep: dict) -> dict:
    return {
        "stock_rows": ep.get("stock_rows"),
        "input_roots": ep.get("input_roots"),
        "unique": ep.get("unique"),
        "expanded": ep.get("expanded"),
        "generated": ep.get("generated"),
        "min_g": ep.get("min_g"),
        "max_g": ep.get("max_g"),
        "max_foundations": ep.get("max_foundations"),
        "alloc_s": ep.get("alloc_s"),
        "alloc_s_strategic": ep.get("alloc_s_strategic"),
        "augment": ep.get("augment"),
        "elapsed_s": ep.get("elapsed_s"),
        "portfolio_cats": ep.get("portfolio_cats"),
        "stop_reason": ep.get("stop_reason"),
    }


def next_recommendation(verdict: str) -> str:
    if verdict == "MATURITY_TACTICAL_COST_IMPROVED":
        return "Promote the new autonomous incumbent and analyse the hierarchical-planning savings."
    if verdict == "MATURITY_TACTICAL_REDISCOVERS_F2":
        return "Inspect the integrated stock-empty continuation from that tactical F2 before changing tactical strategy."
    if verdict == "MATURITY_TACTICAL_IMPROVES_FUTURE":
        return "Improve future-value selection, not tactical search."
    if verdict == "MATURITY_TACTICAL_CASHOUT_POOR_FUTURE":
        return "Improve future-value selection, not tactical search."
    if verdict == "MATURITY_TACTICAL_ROOT_SELECTION_FIXED_PLANNER_FAILS":
        return "Diagnose planner budget/integration discrepancy against v0.71."
    if verdict == "MATURITY_TACTICAL_NO_GAIN":
        return "Diagnose planner budget/integration discrepancy against v0.71."
    return "Fix the contract before continuing."


def _slim_sel(rec: dict) -> dict:
    a = rec.get("_analysis") or analyse_tactical_root(rec)
    return {
        "g": rec.get("g"),
        "F": a.get("foundations"),
        "fd": a.get("face_down"),
        "cat": rec.get("portfolio_cat"),
        "control": bool(rec.get("control_slot") or rec.get("incumbent_control")),
        "n_ready": a.get("n_ready"),
        "cover": a.get("cover"),
        "blockers": a.get("relevant_blockers"),
        "k": a.get("k_min_blockers"),
        "a": a.get("a_min_blockers"),
        "gap": a.get("gap"),
        "maturity_key": list(a.get("maturity_key") or rec.get("maturity_key") or []),
        "ident": rec.get("ident") or rec.get("ordered_digest"),
    }


def write_report(p: dict) -> None:
    r1 = p.get("rows1") or {}
    tac = p.get("tactical") or {}
    audit = p.get("audit") or {}
    f2 = p.get("best_presd5_f2") or {}
    ar = p.get("after_run") or {}
    lines = [
        f"# {EXPERIMENT}",
        "",
        f"Verdict: `{p.get('verdict')}`",
        "",
        p.get("verdict_reason") or p.get("interpretation") or "",
        "",
        "## Maturity key",
        "",
        "cover, inaccessible joins, K, A, gap, -merge edges, buried, blockers, fd, -mobility, g.",
        "g is last. No suit names. No fitted weights.",
        "",
        "## v0.72 vs v0.73 selected roots (audit corpus)",
        "",
        f"- control selected now = {audit.get('control_selected')}",
        f"- old n = {len(audit.get('old') or [])} new n = {len(audit.get('new') or [])}",
        "",
    ]
    lines.append("old: " + json.dumps(audit.get("old") or [], default=str))
    lines.append("new: " + json.dumps(audit.get("new") or [], default=str))
    lines.extend(
        [
            "",
            "## Checkpoint sanity",
            "",
            str(p.get("sanity") or {}),
            "",
            "## Envelope",
            "",
            f"- 900 s / 800k unique / 2.5 GiB / width 256 / ceiling 191 / fraction {p.get('augment_fraction')}",
            "",
            "## Search totals",
            "",
            f"- unique={p.get('unique')} expanded={p.get('expanded')} generated={p.get('generated')}",
            f"- elapsed={p.get('elapsed_s')} stop={p.get('stop_reason')} maxF={p.get('max_foundations')}",
            f"- solved={p.get('solved')} g={p.get('solution_g')}",
            "",
            "## Rows=1 split",
            "",
            f"- alloc={r1.get('alloc_s')} strategic={r1.get('alloc_s_strategic')} tactical={tac.get('alloc_s')}",
            f"- strategic exp={r1.get('expanded')} unique={r1.get('unique')} maxF={r1.get('max_F')}",
            "",
            "## Tactical probes",
            "",
            f"- selected={tac.get('n_selected')} attempted={tac.get('n_probes')} found={tac.get('n_found')}",
            f"- terminals={tac.get('n_terminals')} control={tac.get('control_slot_used')}",
            f"- unique={tac.get('unique')} expanded={tac.get('expanded')} t={tac.get('elapsed_s')}",
            "",
        ]
    )
    for pr in tac.get("probes") or []:
        lines.append(
            f"- g={pr.get('root_g')} rank={pr.get('maturity_rank')} control={pr.get('control_slot')} "
            f"target={pr.get('target_suit')} cover={pr.get('cover')} found={pr.get('found')} "
            f"term_g={pr.get('cheapest_g')} Δ={pr.get('delta_g')} exp={pr.get('expanded')} t={pr.get('elapsed_s')}"
        )
    lines.extend(
        [
            "",
            "## Best pre-SD5 F2",
            "",
            str(f2 or "none"),
            "",
            "## After-run",
            "",
            f"- incumbent F2 g={ar.get('incumbent_f2_g')} v0.71 g={ar.get('v071_g')}",
            f"- same as v0.71={ar.get('same_as_v071')} same as incumbent={ar.get('same_as_incumbent')}",
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
    )
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(str(x) for x in lines) + "\n", encoding="utf-8")


def build_audit_corpus(opening) -> list:
    actions = parse_moves_file(V067)
    ck = replay_to_stock_rows(opening, actions, target_rows=1)
    corpus = [
        {
            "g": ck["g"],
            "ordered_digest": ck["ordered_digest"],
            "ident": ck["whole_game_identity"],
            "full_actions": ck["prefix_actions"],
            "incumbent_control": True,
            "portfolio_cat": "incumbent",
            "stock_rows": 1,
        }
    ]
    if V072.exists():
        data = json.loads(V072.read_text(encoding="utf-8"))
        for pr in (data.get("tactical") or {}).get("probes") or []:
            ident = pr.get("root_ident")
            if not ident:
                continue
            corpus.append(
                {
                    "g": int(pr.get("root_g") or 0),
                    "ordered_digest": ident,
                    "ident": ident,
                    "full_actions": [],
                    "portfolio_cat": "cheap" if int(pr.get("root_g") or 0) < 20 else "readiness",
                    "n_ready": pr.get("n_ready"),
                    "stock_rows": 1,
                }
            )
    return corpus


def main() -> dict:
    opening, _raw, _labels = load_opening()
    print("VERIFY autonomous 192", flush=True)
    inc = verify_autonomous_192(opening)
    if not inc.get("ok"):
        payload = {
            "experiment": EXPERIMENT,
            "incumbent_fail": True,
            "verdict": "MATURITY_TACTICAL_CONTRACT_FAILURE",
        }
        _write_json(RESULT, _jsonable(payload))
        write_report(payload)
        print("VERDICT MATURITY_TACTICAL_CONTRACT_FAILURE", flush=True)
        print("DONE", flush=True)
        return payload

    print("AUDIT root selection vs v0.72", flush=True)
    corpus = build_audit_corpus(opening)
    old = select_tactical_probe_roots(corpus, limit=8, cost_ceiling=191)
    new = select_mature_tactical_roots(corpus, limit=8, cost_ceiling=191)
    control_selected = any(r.get("control_slot") for r in new)
    audit = {
        "corpus_n": len(corpus),
        "old": [_slim_sel(r) for r in old],
        "new": [_slim_sel(r) for r in new],
        "control_selected": control_selected,
        "old_has_control": any(r.get("incumbent_control") or r.get("portfolio_cat") == "incumbent" for r in old),
        "v072_bug": (not any(r.get("incumbent_control") or r.get("portfolio_cat") == "incumbent" for r in old))
        and control_selected,
    }
    print(
        f"AUDIT old={len(old)} new={len(new)} control_now={control_selected} "
        f"old_control={audit['old_has_control']}",
        flush=True,
    )
    _write_json(PROG, {"phase": "audit", "audit": {"control_selected": control_selected, "v072_bug": audit["v072_bug"]}})

    print("SANITY 2s tactical probe from control root", flush=True)
    sanity = {"ran": False}
    control_rec = next((r for r in new if r.get("control_slot")), None)
    if control_rec is not None:
        st_digest = control_rec["ordered_digest"]
        g0 = int(control_rec["g"])
        from spider.packed_state import unpack_state

        state = unpack_state(bytes.fromhex(st_digest))
        target = select_tactical_target(state, g0)
        res_s = search_foundation_cashout(
            ordered_digest=st_digest,
            root_g=g0,
            target_suit=target["suit"],
            max_unique=4_000,
            time_limit_s=2.0,
            rss_abort_mb=SEARCH_RSS_MB,
            cost_ceiling=CANDIDATE_CEILING,
            portfolio_limit=4,
            skip_preview=True,
        )
        sanity = {
            "ran": True,
            "root_g": g0,
            "target": target["suit"],
            "found": bool(res_s.found),
            "first_g": res_s.first_g,
            "cheapest_g": res_s.cheapest_g,
            "elapsed_s": res_s.elapsed_s,
            "unique": res_s.unique,
            "note": "sanity only; not substituted into the whole-game run",
        }
        print(
            f"SANITY found={sanity['found']} first={sanity['first_g']} cheapest={sanity['cheapest_g']} "
            f"t={sanity['elapsed_s']:.2f}s",
            flush=True,
        )

    print(
        f"SEARCH maturity-aware tactical ceiling=191 900s fraction={ROWS1_AUGMENT_FRACTION}",
        flush=True,
    )
    clear_preview_cache()
    t0 = time.perf_counter()
    res = search_integrated_tactical(opening=opening)
    print(
        f"DONE stop={res.stop_reason} unique={res.unique} expanded={res.expanded} "
        f"best={res.solution_g} maxF={res.max_foundations} t={res.elapsed_s:.1f}s",
        flush=True,
    )
    tracker = getattr(res, "transition_tracker", None)
    r1 = next((ep for ep in res.epochs if ep.get("stock_rows") == 1), {})
    cheap = {str(k): slim_f(v) for k, v in sorted(res.foundations_cheap.items())}
    first = {str(k): slim_f(v) for k, v in sorted(res.foundations_first.items())}
    frontier = []
    for n, rec in sorted(res.foundations_cheap.items()):
        frontier.append(
            {
                "F": n,
                "g": rec.get("g"),
                "rows": rec.get("stock_rows"),
                "fd": rec.get("face_down"),
                "suits": rec.get("foundation_suits"),
                "cat": rec.get("portfolio_cat"),
                "from_incumbent_ckpt": rec.get("from_incumbent_ckpt"),
                "tactical_target": rec.get("tactical_target"),
                "h": rec.get("assembly_h"),
            }
        )
    cheap_f2 = cheap.get("2") or {}
    best_f2 = None
    if cheap_f2.get("stock_rows") == 1:
        best_f2 = {
            "g": cheap_f2.get("g"),
            "fd": cheap_f2.get("face_down"),
            "F": 2,
            "suits": cheap_f2.get("foundation_suits"),
            "stock_rows": 1,
            "legal": cheap_f2.get("legal_tableau"),
            "from_incumbent_ckpt": cheap_f2.get("from_incumbent_ckpt"),
            "portfolio_cat": cheap_f2.get("portfolio_cat"),
            "tactical_target": cheap_f2.get("tactical_target"),
            "digest": cheap_f2.get("ordered_digest"),
            "tactical_delta_g": cheap_f2.get("tactical_delta_g"),
            "control_slot": cheap_f2.get("control_slot"),
            "post_assembly_h": cheap_f2.get("post_assembly_h"),
            "post_assembly_f": cheap_f2.get("post_assembly_f"),
        }

    improved = (
        res.solved
        and res.replay_ok
        and res.solution_g is not None
        and int(res.solution_g) < AUTONOMOUS_INCUMBENT_MW
        and res.solution_actions
    )
    replay_ok = bool(res.replay_ok)
    replay_g = res.replay_g
    if improved:
        save_solution(
            res.solution_actions,
            FIX,
            g=int(res.solution_g),
            label="Autonomous v0.73 maturity-aware tactical solution",
        )
        end = opening.clone()
        replay_g = replay_actions(end, list(res.solution_actions))
        replay_ok = (
            replay_g == int(res.solution_g)
            and end.is_solved()
            and sum(1 for a in res.solution_actions if is_deal(a)) == 5
            and len(end.foundations) == 8
            and not end.stock
            and all(c.is_empty() for c in end.columns)
        )

    print("EVAL canonical after search", flush=True)
    canon_g = replay_actions(opening.clone(), parse_moves_file(CANON))
    print("EVAL after-run v0.71 and incumbent suffix", flush=True)
    require_eval_phase("after-run incumbent suffix")
    actions_192 = parse_moves_file(V067)
    prefix = replay_to_stock_rows(opening, actions_192, target_rows=1)
    inc_suffix = replay_incumbent_suffix_for_eval(
        opening, actions_192, prefix_n=int(prefix["n_prefix"]), root_g=int(prefix["g"])
    )
    v71 = json.loads(CONT71.read_text(encoding="utf-8")) if CONT71.exists() else {}
    after_run = {
        "incumbent_f2_g": inc_suffix.get("foundation_g"),
        "incumbent_f2_digest": inc_suffix.get("ordered_digest"),
        "incumbent_preview": inc_suffix.get("deal_preview"),
        "v071_g": v71.get("terminal_g"),
        "v071_digest": v71.get("terminal_digest"),
        "v072_best_presd5_f2": None,
        "v073_best_presd5_f2": best_f2,
        "same_as_v071": bool(best_f2 and v71.get("terminal_digest") and best_f2.get("digest") == v71.get("terminal_digest")),
        "same_as_incumbent": bool(
            best_f2 and inc_suffix.get("ordered_digest") and best_f2.get("digest") == inc_suffix.get("ordered_digest")
        ),
    }
    aug = r1.get("augment") or {}
    payload = {
        "experiment": EXPERIMENT,
        "base_sha": BASE_SHA,
        "branch": BRANCH,
        "policy_reads_canonical": False,
        "incumbent_g": AUTONOMOUS_INCUMBENT_MW,
        "incumbent_verify": {k: inc.get(k) for k in inc if k != "actions"},
        "canonical_eval_g": canon_g,
        "audit": audit,
        "sanity": sanity,
        "maturity_key_order": [
            "cover",
            "inaccessible_joins",
            "k_min_blockers",
            "a_min_blockers",
            "gap",
            "-legal_merge_edges",
            "buried_components",
            "relevant_blockers",
            "face_down",
            "-legal_mobility",
            "g",
        ],
        "envelope": {
            "time_s": SEARCH_TIME_S,
            "unique": SEARCH_UNIQUE,
            "rss_abort_mb": SEARCH_RSS_MB,
            "candidate_ceiling": CANDIDATE_CEILING,
            "portfolio_width": PORTFOLIO_WIDTH,
            "lanes": list(STRATEGIC_LANES),
            "completion_lanes": list(COMPLETION_LANES),
        },
        "augment_fraction": ROWS1_AUGMENT_FRACTION,
        "elapsed_s": res.elapsed_s,
        "wall_s": time.perf_counter() - t0,
        "unique": res.unique,
        "expanded": res.expanded,
        "generated": res.generated,
        "states_per_s": res.states_per_s,
        "stop_reason": res.stop_reason,
        "max_foundations": res.max_foundations,
        "solved": res.solved,
        "solution_g": res.solution_g,
        "replay_ok": replay_ok,
        "replay_g": replay_g,
        "accounting_fail": res.accounting_fail,
        "foundations": {"first": first, "cheap": cheap},
        "frontier": frontier,
        "epochs": [slim_epoch(ep) for ep in res.epochs],
        "rows1": {
            "s": r1.get("elapsed_s"),
            "alloc_s": r1.get("alloc_s"),
            "alloc_s_strategic": r1.get("alloc_s_strategic"),
            "expanded": r1.get("expanded"),
            "unique": r1.get("unique"),
            "max_F": r1.get("max_foundations"),
            "lane_exp": r1.get("lane_exp"),
            "portfolio_cats": r1.get("portfolio_cats"),
            "augment": aug,
        },
        "tactical": {
            "n_probes": aug.get("n_probes"),
            "n_selected": aug.get("n_selected"),
            "n_ready_roots": aug.get("n_ready_roots"),
            "n_found": aug.get("found"),
            "n_terminals": aug.get("n_terminals"),
            "n_terminals_raw": aug.get("n_terminals_raw"),
            "control_slot_used": aug.get("control_slot_used"),
            "unique": aug.get("unique"),
            "expanded": aug.get("expanded"),
            "elapsed_s": aug.get("elapsed_s"),
            "alloc_s": aug.get("alloc_s"),
            "lane_exp": aug.get("lane_exp"),
            "probes": aug.get("probes"),
        },
        "lanes": {"expansions": res.lane_exp, "pops": res.lane_pops},
        "tracker": None if tracker is None else tracker.stats(),
        "best_presd5_f2": best_f2,
        "preview_perf": preview_cache_stats(),
        "bound_perf": {
            "prunes": res.lower_bound_prunes,
            "calls": res.lower_bound_calls,
            "seconds": res.lower_bound_s,
            "prunes_by_F": dict(res.prunes_by_F or {}),
            "reconcile": reconcile_lower_bound_telemetry(res),
        },
        "checkpoint": {"injected": res.incumbent_injected, "survived": res.incumbent_survived},
        "after_run": after_run,
        "r2_r3_active": False,
    }
    if improved:
        payload["solution_file"] = str(FIX.relative_to(ROOT)).replace("\\", "/")
        payload["solution_actions"] = [
            list(a) if a != ("deal",) else ["deal"] for a in res.solution_actions
        ]
    verdict, reason = choose_maturity_tactical_verdict(payload)
    payload["verdict"] = verdict
    payload["verdict_reason"] = reason
    payload["interpretation"] = reason
    payload["next_recommendation"] = next_recommendation(verdict)
    payload = _jsonable(payload)
    _write_json(RESULT, payload)
    _write_json(
        PROG,
        {
            "phase": "complete",
            "verdict": verdict,
            "control_selected": control_selected,
            "tactical": payload.get("tactical"),
            "best_presd5_f2": best_f2,
            "solution_g": payload.get("solution_g"),
            "max_foundations": payload.get("max_foundations"),
        },
    )
    write_report(payload)
    print(f"VERDICT {verdict}", flush=True)
    print("DONE", flush=True)
    return payload


if __name__ == "__main__":
    main()
