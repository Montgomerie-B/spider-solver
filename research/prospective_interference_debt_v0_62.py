#!/usr/bin/env python3
"""v0.62: prospective interference-debt whole-game optimisation.

One policy, one 900 s run. Canonical 172 is analysis/evaluation only.
Search reads only the autonomous 198 incumbent.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.autonomous_cost import load_machine_incumbent, replay_solution_trace
from spider.metrics import parse_moves_file, replay_actions
from spider.prospective_debt import (
    DEBT_HARVEST_CATS,
    DEBT_LANES,
    choose_debt_verdict,
    search_debt_optimisation,
)
from spider.research_actions import apply_action, is_deal, stock_rows
from spider.solution_forensics import (
    AUTO_MOVES,
    CANON_MOVES,
    extract_epochs,
    instrumented_replay,
    load_opening,
    rehandling_summary,
)
from spider.structural_analysis import compact_interference, interference_debt
from spider.whole_game_anytime import opening_state
from spider.whole_game_epoch_scheduler import (
    PORTFOLIO_WIDTH,
    SEARCH_RSS_MB,
    SEARCH_TIME_S,
    SEARCH_UNIQUE,
    save_solution,
)

EXPERIMENT = "prospective_interference_debt_v0_62"
BASE_SHA = "6c729be374de4f570e78cffad3a6062403ee4822"
BRANCH = "agent/prospective-interference-debt-v0-62"
RESULT = ROOT / "docs" / "research" / f"{EXPERIMENT}.json"
REPORT = ROOT / "docs" / "research" / f"{EXPERIMENT}.md"
PROG = ROOT / "docs" / "research" / "prospective_interference_progress_v0_62.json"
FIX = ROOT / "solutions" / "4925153_autonomous_v0_62.moves"
META = ROOT / "solutions" / "4925153_autonomous_v0_62.json"


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


def debt_along_route(opening, actions) -> list:
    state = opening.clone()
    g = 0
    deal_n = 0
    rows = []

    def snap(label, after_deal=False):
        d = interference_debt(state)
        rec = compact_interference(d)
        rec["label"] = label
        rec["g"] = g
        rec["stock_rows"] = stock_rows(state)
        rec["after_deal"] = after_deal
        rec["same_suit_bonds"] = int(d["visible_cards"]) - int(d["visible_components"])
        rec["by_suit"] = d["by_suit"]
        return rec

    rows.append(snap("opening"))
    for action in actions:
        if is_deal(action):
            rows.append(snap(f"pre-SD{deal_n + 1}"))
            g += apply_action(state, action)
            deal_n += 1
            rows.append(snap(f"post-SD{deal_n}", after_deal=True))
            continue
        g += apply_action(state, action)
    rows.append(snap("solved"))
    return rows


def _post_sd5(snaps):
    for rec in snaps:
        if rec["label"] == "post-SD5":
            return rec
    return None


def forensic_bundle(opening, actions, expected_g, labels):
    trace = instrumented_replay(opening, actions, labels, expected_g=expected_g)
    rh = rehandling_summary(trace)
    eps = extract_epochs(trace, opening, actions, labels)
    post = next(ep for ep in eps if ep["label"] == "post-SD5")
    return {
        "g": trace["g"],
        "tableau": trace["tableau_commands"],
        "zero_cost": trace["zero_cost_commands"],
        "bucket_mw": trace["bucket_mw"],
        "rehandle_exclusive": trace["bucket_mw"].get("REHANDLE"),
        "rehandle_actions": rh["rehandle_actions"],
        "n_repeat_paid_movers": rh["n_repeat_paid_movers"],
        "n_cards_paid_after_attach": rh["n_cards_paid_after_attach"],
        "mean_paid_per_card": round(
            sum(r["paid_actions"] for r in trace["lifecycle"].values()) / max(1, len(trace["lifecycle"])),
            3,
        ),
        "mixed_park_identities": sum(
            1 for r in trace["lifecycle"].values() if r.get("mixed_park_g") is not None
        ),
        "post_sd5_enter_g": post["enter"]["g"],
        "post_sd5_remaining": post["enter"]["remaining_cost"],
        "post_sd5_delta": post["delta_g"],
        "post_sd5_tableau_n": post["tableau_n"],
        "post_sd5_zero_cost": post["zero_cost"],
        "post_sd5_fd": post["enter"]["face_down"],
        "post_sd5_bonds": post["enter"]["same_suit_bonds"],
        "post_sd5_foundations": post["enter"]["foundations"],
    }


def metric_tracks_rehandling(auto_snaps, canon_snaps) -> str:
    a5 = _post_sd5(auto_snaps)
    c5 = _post_sd5(canon_snaps)
    if not a5 or not c5:
        return "unknown"
    # Cheaper remaining route should not have *clearly more* unresolved debt.
    if c5["boundaries_total"] > a5["boundaries_total"] + 2 and c5["component_layers"] > a5["component_layers"]:
        return "invalid"
    if (
        a5["boundaries_total"] >= c5["boundaries_total"]
        or a5["component_layers"] >= c5["component_layers"]
        or a5["mixed_supports"] >= c5["mixed_supports"]
    ):
        return "aligned"
    return "mixed"


def next_recommendation(verdict: str) -> str:
    if verdict == "INTERFERENCE_DEBT_COST_IMPROVED":
        return "Continue autonomous cost optimisation and diagnose which epochs produced the saving."
    if verdict == "INTERFERENCE_DEBT_REDUCES_REHANDLING_ONLY":
        return "Ask whether saved rehandling was offset by extra excavation or readiness cost before changing weights."
    if verdict == "INTERFERENCE_DEBT_SIGNAL_INVALID":
        return "Do not increase weighting. Move to operational foundation viability / excavation-gated cash-out."
    if verdict == "INTERFERENCE_DEBT_CONTRACT_FAILURE":
        return "Stop solver work until the contract failure is diagnosed."
    return (
        "Do not increase interference weighting. Next v0.61 hypothesis: "
        "excavation-gated foundation cash-out / operational viability. "
        "Do not copy the 172 route."
    )


def slim_epoch(ep: dict) -> dict:
    return {
        "stock_rows": ep.get("stock_rows"),
        "input_roots": ep.get("input_roots"),
        "unique": ep.get("unique"),
        "expanded": ep.get("expanded"),
        "generated": ep.get("generated"),
        "min_g": ep.get("min_g"),
        "max_g": ep.get("max_g"),
        "min_face_down": ep.get("min_face_down"),
        "max_foundations": ep.get("max_foundations"),
        "n_ready": ep.get("n_ready"),
        "lane_exp": ep.get("lane_exp"),
        "portfolio_cats": ep.get("portfolio_cats"),
        "interference": ep.get("interference"),
        "incumbent_in_portfolio": bool(
            (ep.get("portfolio_cats") or {}).get("incumbent")
        ),
        "best_durability": None
        if not ep.get("best_durability")
        else {
            k: ep["best_durability"].get(k)
            for k in (
                "g",
                "foundations",
                "face_down",
                "boundaries_total",
                "component_layers",
                "mixed_supports",
                "n_ready",
            )
        },
        "best_readiness": None
        if not ep.get("best_readiness")
        else {
            k: ep["best_readiness"].get(k)
            for k in ("g", "foundations", "face_down", "n_ready", "cover", "ready_fd")
        },
        "stop_reason": ep.get("stop_reason"),
        "elapsed_s": ep.get("elapsed_s"),
    }


def write_report(p: dict) -> None:
    sanity = p.get("sanity") or {}
    lines = [
        f"# {EXPERIMENT}",
        "",
        f"Verdict: `{p.get('verdict')}`",
        "",
        p.get("interpretation", ""),
        "",
        "## Contract",
        "",
        f"- Base `{p.get('base_sha')}`",
        f"- Branch `{p.get('branch')}`",
        "- Search does not read `solutions/4925153_canonical.moves`",
        "- Interference is a function of the current state only",
        "- Exact SPK1/SPS1 TT and cheapest-g dominance unchanged",
        "- Candidate ceiling 197; g is still corrected MW",
        "",
        "## Generic metric",
        "",
        "Unresolved same-suit component boundaries (off-suit descending vs",
        "rank-break), accessible vs buried, stacked component layers,",
        "mixed-support of the exposed movable run, visible-component",
        "fragmentation. Lexicographic DURABILITY uses foundations, then",
        "boundaries, layers, mixed-supports, face-down, readiness cover, g.",
        "No historical rehandle counter and no weighted 172-fit score.",
        "",
        "## Sanity (Deal boundaries, analysis only)",
        "",
        json.dumps(sanity, indent=2, sort_keys=True)[:8000],
        "",
        "## Envelope",
        "",
        json.dumps(p.get("envelope"), indent=2, sort_keys=True),
        "",
        "## Totals",
        "",
        json.dumps(
            {
                k: p.get(k)
                for k in (
                    "elapsed_s",
                    "unique",
                    "expanded",
                    "generated",
                    "states_per_s",
                    "stop_reason",
                    "solution_g",
                    "incumbent_g",
                    "max_foundations",
                    "min_face_down",
                    "incumbent_injected",
                    "incumbent_survived",
                )
            },
            indent=2,
            sort_keys=True,
        ),
        "",
        "## Lanes",
        "",
        json.dumps(p.get("lanes"), indent=2, sort_keys=True),
        "",
        "## Foundations",
        "",
        json.dumps(p.get("foundations"), indent=2, sort_keys=True)[:6000],
        "",
        "## Candidate forensics",
        "",
        json.dumps(p.get("candidate_forensics"), indent=2, sort_keys=True),
        "",
        "## Incumbent forensics",
        "",
        json.dumps(p.get("incumbent_forensics"), indent=2, sort_keys=True),
        "",
        "## Next recommendation",
        "",
        p.get("next_recommendation", ""),
        "",
    ]
    REPORT.write_text("\n".join(str(x) for x in lines) + "\n", encoding="utf-8")


def main() -> dict:
    opening, _raw, labels = load_opening()
    print("SANITY incumbent 198", flush=True)
    auto_actions = parse_moves_file(AUTO_MOVES)
    assert replay_actions(opening.clone(), auto_actions) == 198
    auto_snaps = debt_along_route(opening, auto_actions)
    print("SANITY canonical 172 (analysis only)", flush=True)
    canon_actions = parse_moves_file(CANON_MOVES)
    assert replay_actions(opening.clone(), canon_actions) == 172
    canon_snaps = debt_along_route(opening, canon_actions)
    signal = metric_tracks_rehandling(auto_snaps, canon_snaps)
    a5 = _post_sd5(auto_snaps)
    c5 = _post_sd5(canon_snaps)
    print(
        f"POST-SD5 debt auto b={a5['boundaries_total']} layers={a5['component_layers']} "
        f"mixed={a5['mixed_supports']} | canon b={c5['boundaries_total']} "
        f"layers={c5['component_layers']} mixed={c5['mixed_supports']} signal={signal}",
        flush=True,
    )
    inc = load_machine_incumbent(opening)
    print(f"SEARCH ceiling={inc['g'] - 1} 900s", flush=True)
    t0 = time.perf_counter()
    res = search_debt_optimisation(opening=opening, incumbent_trace=inc)
    print(
        f"DONE stop={res.stop_reason} unique={res.unique} expanded={res.expanded} "
        f"best={res.solution_g} t={res.elapsed_s:.1f}s",
        flush=True,
    )
    _write_json(
        PROG,
        {
            "stop_reason": res.stop_reason,
            "unique": res.unique,
            "expanded": res.expanded,
            "generated": res.generated,
            "solution_g": res.solution_g,
            "elapsed_s": res.elapsed_s,
            "lane_exp": res.lane_exp,
            "lane_pops": res.lane_pops,
            "max_foundations": res.max_foundations,
            "min_face_down": res.min_face_down,
            "incumbent_injected": res.incumbent_injected,
            "incumbent_survived": res.incumbent_survived,
            "epochs": [slim_epoch(ep) for ep in res.epochs],
            "foundations_cheap": {str(k): v for k, v in sorted(res.foundations_cheap.items())},
            "foundations_first": {str(k): v for k, v in sorted(res.foundations_first.items())},
            "sanity_post_sd5": {"auto": a5, "canon": c5, "signal": signal},
        },
    )
    print("WROTE progress snapshot", flush=True)
    inc_for = forensic_bundle(opening, auto_actions, 198, labels)
    cand_for = None
    cand_snaps = None
    improved = (
        res.solved
        and res.replay_ok
        and res.solution_g is not None
        and int(res.solution_g) < int(inc["g"])
        and res.solution_actions
    )
    rehandling_improved = False
    if improved:
        cand_for = forensic_bundle(opening, res.solution_actions, int(res.solution_g), labels)
        cand_snaps = debt_along_route(opening, res.solution_actions)
        rehandling_improved = int(cand_for["rehandle_exclusive"]) < int(inc_for["rehandle_exclusive"])
        deals = sum(1 for a in res.solution_actions if is_deal(a))
        save_solution(res.solution_actions, FIX, g=int(res.solution_g))
        _write_json(
            META,
            {
                "g": res.solution_g,
                "previous_incumbent": inc["g"],
                "replay_g": res.replay_g,
                "replay_ok": True,
                "deals": deals,
                "path": str(FIX.relative_to(ROOT)).replace("\\", "/"),
                "branch": BRANCH,
                "base_sha": BASE_SHA,
            },
        )
    elif res.solved and res.replay_ok and res.solution_actions and int(res.solution_g or 198) >= 198:
        # do not write a duplicate 198 solution
        cand_for = forensic_bundle(opening, res.solution_actions, int(res.solution_g), labels)

    payload = {
        "experiment": EXPERIMENT,
        "base_sha": BASE_SHA,
        "branch": BRANCH,
        "policy_reads_canonical": False,
        "metric_history_free": True,
        "sanity": {
            "signal": signal,
            "auto_post_sd5": a5,
            "canon_post_sd5": c5,
            "auto_boundaries": [
                {k: r.get(k) for k in ("label", "g", "stock_rows", "boundaries_total", "component_layers", "mixed_supports", "max_layer_depth", "face_down", "foundations", "visible_components")}
                for r in auto_snaps
                if r["label"] in ("opening", "pre-SD1", "post-SD1", "pre-SD2", "post-SD2", "pre-SD3", "post-SD3", "pre-SD4", "post-SD4", "pre-SD5", "post-SD5", "solved")
                or r.get("after_deal")
                or r["label"].startswith("pre-")
                or r["label"].startswith("post-")
                or r["label"] in ("opening", "solved")
            ],
            "canon_boundaries": [
                {k: r.get(k) for k in ("label", "g", "stock_rows", "boundaries_total", "component_layers", "mixed_supports", "max_layer_depth", "face_down", "foundations", "visible_components")}
                for r in canon_snaps
                if r["label"] in ("opening", "solved") or r["label"].startswith("pre-") or r["label"].startswith("post-")
            ],
        },
        "envelope": {
            "time_s": SEARCH_TIME_S,
            "unique": SEARCH_UNIQUE,
            "rss_abort_mb": SEARCH_RSS_MB,
            "candidate_ceiling_initial": inc["g"] - 1,
            "portfolio_width": PORTFOLIO_WIDTH,
            "harvest_slack": -1,
            "remaining_deal_bound": True,
            "lanes": list(DEBT_LANES),
            "harvest_cats": list(DEBT_HARVEST_CATS),
        },
        "elapsed_s": res.elapsed_s,
        "wall_s": time.perf_counter() - t0,
        "peak_rss_mb": res.peak_rss_mb,
        "unique": res.unique,
        "expanded": res.expanded,
        "generated": res.generated,
        "duplicate_skips": res.duplicate_skips,
        "stale_skips": res.stale_skips,
        "states_per_s": res.states_per_s,
        "stop_reason": res.stop_reason,
        "min_g": res.min_g,
        "max_g": res.max_g,
        "lanes": {"names": list(DEBT_LANES), "pops": res.lane_pops, "expansions": res.lane_exp, "stale": res.lane_stale},
        "class_displaced": res.class_displaced,
        "incumbent_injected": res.incumbent_injected,
        "incumbent_survived": res.incumbent_survived,
        "candidate_ceiling": res.candidate_ceiling,
        "incumbent_g": inc["g"],
        "solved": res.solved,
        "solution_g": res.solution_g,
        "replay_ok": res.replay_ok,
        "replay_g": res.replay_g,
        "accounting_fail": res.accounting_fail,
        "max_foundations": res.max_foundations,
        "min_face_down": res.min_face_down,
        "foundations": {
            "first": {str(k): v for k, v in sorted(res.foundations_first.items())},
            "cheap": {str(k): v for k, v in sorted(res.foundations_cheap.items())},
        },
        "epochs": [slim_epoch(ep) for ep in res.epochs],
        "best_state": res.best_state,
        "best_readiness": res.best_readiness,
        "best_durability": res.best_durability,
        "incumbent_forensics": inc_for,
        "candidate_forensics": cand_for,
        "candidate_debt_path": None
        if cand_snaps is None
        else [
            {k: r.get(k) for k in ("label", "g", "boundaries_total", "component_layers", "mixed_supports", "face_down", "foundations")}
            for r in cand_snaps
            if r["label"] in ("opening", "solved") or r["label"].startswith("pre-") or r["label"].startswith("post-")
        ],
        "rehandling_improved": rehandling_improved,
        "metric_signal": signal,
        "production_unchanged": True,
        "no_new_solution_if_not_improved": not improved,
    }
    if improved:
        payload["solution_file"] = str(FIX.relative_to(ROOT)).replace("\\", "/")
        payload["improvement"] = int(inc["g"]) - int(res.solution_g)
    verdict, interpretation = choose_debt_verdict(payload)
    payload["verdict"] = verdict
    payload["interpretation"] = interpretation
    payload["next_recommendation"] = next_recommendation(verdict)
    payload = _jsonable(payload)
    _write_json(RESULT, payload)
    _write_json(
        PROG,
        {
            "epochs": payload.get("epochs"),
            "foundations_cheap": payload.get("foundations", {}).get("cheap"),
            "solution_g": payload.get("solution_g"),
            "stop_reason": payload.get("stop_reason"),
            "lanes": payload.get("lanes"),
            "sanity_post_sd5": {"auto": a5, "canon": c5, "signal": signal},
        },
    )
    write_report(payload)
    print(f"VERDICT {verdict}", flush=True)
    print("DONE", flush=True)
    return payload


if __name__ == "__main__":
    main()
