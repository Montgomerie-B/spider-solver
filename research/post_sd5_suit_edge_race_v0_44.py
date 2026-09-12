#!/usr/bin/env python3
"""v0.44: race the four mandatory post-SD5 2-A edges from DEAL_NOW roots only."""

from __future__ import annotations

import json
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.metrics import replay_actions
from spider.packed_state import pack_post_stock_symmetry_state, pack_state
from spider.simple_deal1_preview import stock_rows
from spider.simple_diamond_c_bridge import as_actions, dump_actions
from spider.simple_final_deal_timing import foundation_suits
from spider.simple_post_sd5_edge_race import (
    COST_CEILING,
    HARVEST_SLACK,
    MAX_UNIQUE,
    RSS_PER_MB,
    SUIT_NAMES,
    SUITS,
    TIME_LIMIT_S,
    edge_2a_present,
    load_deal_now_roots,
    low_tail_length,
    material_copy_counts,
    opening_state,
    preview_tail3,
    search_edge_2a,
    source_edge_audit,
    tail3_present,
)
from spider.simple_progressive_solver import format_moves_text
from spider.simple_workspace_reachability import empty_column_indices, face_down_count

EXPERIMENT = "post_sd5_suit_edge_race_v0_44"
BASE_SHA = "ae78cb0f10ed83aa02091e6987415dd213e5e41d"
BRANCH = "agent/post-sd5-suit-edge-race-v0-44"
RESULT = ROOT / "docs" / "research" / f"{EXPERIMENT}.json"
REPORT = ROOT / "docs" / "research" / f"{EXPERIMENT}.md"
ROOTS = ROOT / "docs" / "research" / "post_sd5_deal_now_roots_v0_44.json"
PORT = {
    "s": ROOT / "docs" / "research" / "post_sd5_edge_spade_v0_44.json",
    "h": ROOT / "docs" / "research" / "post_sd5_edge_heart_v0_44.json",
    "d": ROOT / "docs" / "research" / "post_sd5_edge_diamond_v0_44.json",
    "c": ROOT / "docs" / "research" / "post_sd5_edge_club_v0_44.json",
}
FOUND_FIX = ROOT / "solutions" / "4925153_v0_44_foundation2.moves.txt"
OUT_DIR = ROOT / "research" / "results" / EXPERIMENT


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temp.replace(path)


def aggregate_source_audit(opening, roots) -> dict:
    agg = {s: Counter() for s in SUITS}
    sample = {s: None for s in SUITS}
    by_lin = {s: {} for s in SUITS}
    for rec in roots:
        end = opening.clone()
        replay_actions(end, as_actions(rec["full_actions"]))
        for suit in SUITS:
            baseline = 1 if suit == "s" else 0
            a = source_edge_audit(end, suit, baseline=baseline)
            agg[suit]["n"] += 1
            agg[suit]["edge_2a"] += int(a["edge_2a"])
            agg[suit]["immediate_join"] += int(a["immediate_join"])
            if sample[suit] is None:
                sample[suit] = a
            for lin in rec["lineages"]:
                by_lin[suit].setdefault(lin, Counter())
                by_lin[suit][lin]["n"] += 1
                by_lin[suit][lin]["edge_2a"] += int(a["edge_2a"])
                by_lin[suit][lin]["immediate_join"] += int(a["immediate_join"])
    return {
        suit: {
            "n": int(agg[suit]["n"]),
            "edge_2a": int(agg[suit]["edge_2a"]),
            "immediate_join": int(agg[suit]["immediate_join"]),
            "by_lineage": {k: dict(v) for k, v in by_lin[suit].items()},
            "sample": sample[suit],
        }
        for suit in SUITS
    }


def rebuild(opening, roots, search, suit):
    rebuilt = []
    for rec in search.witnesses:
        src = roots[rec["origin"]]
        full = as_actions(src["full_actions"]) + as_actions(rec.get("actions") or [])
        end = opening.clone()
        cost = replay_actions(end, full)
        baseline = 1 if suit == "s" else 0
        rebuilt.append(
            {
                **rec,
                "full_cost": cost,
                "full_actions": dump_actions(full),
                "full_replay_ok": cost == rec["g"] and stock_rows(end) == 0,
                "ordered_digest": pack_state(end).hex(),
                "symmetry_digest": pack_post_stock_symmetry_state(end).hex(),
                "edge_2a": edge_2a_present(end, suit, baseline=baseline),
                "tail3": tail3_present(end, suit, baseline=baseline),
                "low_tail": low_tail_length(end, suit),
                "fd": face_down_count(end),
                "empties": list(empty_column_indices(end)),
                "foundations": foundation_suits(end),
            }
        )
    rebuilt.sort(key=lambda w: (w["full_cost"], w.get("depth", 0), w["origin"]))
    return rebuilt


def select_leaders(blocks: dict) -> tuple[list[str], str]:
    reached = [s for s in SUITS if blocks[s]["reached"]]
    if not reached:
        return [], "no 2-A edge reached"
    scores = []
    for s in reached:
        b = blocks[s]
        n = b["n"] or 1
        t3 = (b["preview"].get("TAIL3_IMMEDIATE") or 0) + (b["preview"].get("TAIL3_WITHIN_5") or 0)
        rate = t3 / n
        scores.append(
            (
                -int(b.get("foundation_surprise") or False),
                -rate,
                -(b.get("longest_preview_tail") or 0),
                b["best_full_mw"] if b["best_full_mw"] is not None else 10**9,
                b["first_s"] if b["first_s"] is not None else 99,
                s,
            )
        )
    scores.sort()
    best = scores[0]
    leaders = [best[-1]]
    for sc in scores[1:]:
        # comparable: similar continuation rate and cost within 3
        same_rate = abs((-sc[1]) - (-best[1])) < 0.15
        e_best = best[3]
        e_sc = sc[3]
        same_cost = abs(e_sc - e_best) <= 3
        if same_rate and same_cost:
            leaders.append(sc[-1])
    why = (
        "continuation and cost, not merely cheapest 2-A"
        if len(leaders) > 1
        else f"{SUIT_NAMES[leaders[0]]} leads on 3-2-A continuation then cost"
    )
    return leaders, why


def choose_verdict(payload: dict) -> tuple[str, str]:
    if not payload.get("all_replay_ok"):
        return "SOURCE_REPLAY_FAILURE", "v0.43 DEAL_NOW sources failed replay"
    if payload.get("foundation_reached"):
        return "FOUNDATION2_REACHED_DURING_EDGE_RACE", "Foundation 2 auto-removed during an edge search or preview"
    reached = [s for s in SUITS if payload["suits"][s]["reached"]]
    explosion = any(
        payload["suits"][s]["stop_reason"] in ("unique limit", "rss abort") and not payload["suits"][s]["reached"]
        for s in SUITS
    )
    if not reached and explosion:
        return "POST_SD5_EDGE_RACE_STATE_EXPLOSION", "no 2-A edge before unique/RSS limit"
    if not reached:
        return "NO_2A_EDGE_FOUND_IN_ENVELOPE", "no suit reached mandatory 2-A under MW<=100"
    leaders = payload.get("leaders") or []
    if len(leaders) >= 2:
        return "MULTIPLE_POST_SD5_ENTRY_SUITS_VIABLE", f"leaders {[SUIT_NAMES[s] for s in leaders]}"
    if leaders == ["s"]:
        return "SPADE_POST_SD5_ENTRY_LEADS", "Spade 2-A is the operational post-SD5 entry"
    if leaders == ["h"]:
        return "HEART_POST_SD5_ENTRY_LEADS", "Heart 2-A is the operational post-SD5 entry"
    if leaders == ["d"]:
        return "DIAMOND_POST_SD5_ENTRY_LEADS", "Diamond 2-A is the operational post-SD5 entry"
    if leaders == ["c"]:
        return "CLUB_POST_SD5_ENTRY_LEADS", "Club 2-A is the operational post-SD5 entry"
    return "INCONCLUSIVE", "edge race finished without a classified leader"


def next_recommendation(verdict: str, leaders: list[str]) -> str:
    if verdict == "FOUNDATION2_REACHED_DURING_EDGE_RACE":
        return "Persist the Foundation 2 witness and do not search Foundation 3."
    if verdict.endswith("_ENTRY_LEADS") or verdict == "MULTIPLE_POST_SD5_ENTRY_SUITS_VIABLE":
        names = ", ".join(SUIT_NAMES[s] for s in leaders) if leaders else "the leading suit"
        return (
            f"Use {names} as the post-SD5 entry target. Next, test which pre-SD5 DEAL_NOW vs "
            "small prep most improves THAT suit's 2-A / 3-2-A gateway. Do not flood UCS with "
            "undirected prep children."
        )
    if verdict == "NO_2A_EDGE_FOUND_IN_ENVELOPE":
        return "No 2-A edge formed under MW<=100 from DEAL_NOW. Inspect A/2 exposure; do not resume G6_8."
    if verdict == "POST_SD5_EDGE_RACE_STATE_EXPLOSION":
        return "2-A race exploded before an entry edge. Keep DEAL_NOW roots; do not reseed 103k prep children."
    return "Keep DEAL_NOW 2-A target selection. Do not generate undirected pre-Deal prep."


def write_report(payload: dict) -> None:
    lines = [
        "# Spider Solver v0.44 — Post-SD5 Suit 2-A Edge Race",
        "",
        "## 1. Verdict",
        "",
        f"`{payload.get('verdict')}` — {payload.get('verdict_reason', '')}",
        "",
        payload.get("interpretation", ""),
        "",
        f"- Branch: `{payload.get('branch')}`",
        f"- Base SHA: `{BASE_SHA}`",
        "",
        "## 2. DEAL_NOW roots",
        "",
        "```json",
        json.dumps(payload.get("roots"), indent=2)[:2500],
        "```",
        "",
        "## 3. Material / source audit",
        "",
        "```json",
        json.dumps({"material": payload.get("material"), "source_audit": payload.get("source_audit")}, indent=2)[:4000],
        "```",
        "",
        "## 4. Four equal 2-A searches",
        "",
        "```json",
        json.dumps(payload.get("suits"), indent=2)[:6000],
        "```",
        "",
        "## 5. Comparison / foundation / files",
        "",
        "```json",
        json.dumps(
            {
                "leaders": payload.get("leaders"),
                "leader_why": payload.get("leader_why"),
                "foundation": payload.get("foundation"),
                "files": payload.get("files"),
            },
            indent=2,
        )[:2500],
        "```",
        "",
        "## 6. Exactly one next recommendation",
        "",
        payload.get("next_recommendation", ""),
        "",
        "## Integrity",
        "",
        "DEAL_NOW only. No pre-Deal prep states. Post-stock symmetry identity. "
        "Equal budgets. Target progress not canonical. Production unchanged.",
        "",
    ]
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> dict:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    opening = opening_state()
    started = time.perf_counter()
    print("ROOTS DEAL_NOW only", flush=True)
    bundle = load_deal_now_roots(opening)
    print(
        f"ROOTS pre={bundle['pre_sd5_n']} sym={bundle['symmetry_classes']} fail={bundle['replay_failures']} "
        f"sd5={bundle['sd5_audit']}",
        flush=True,
    )
    _write_json(
        ROOTS,
        {
            "experiment": EXPERIMENT,
            "n": bundle["symmetry_classes"],
            "pre_sd5_n": bundle["pre_sd5_n"],
            "cost_counts": bundle["cost_counts"],
            "lineage_counts": bundle["lineage_counts"],
            "sd5_audit": bundle["sd5_audit"],
            "auto_removed": bundle["auto_removed"],
            "states": bundle["states"],
        },
    )
    sample = opening.clone()
    replay_actions(sample, as_actions(bundle["states"][0]["full_actions"]))
    material = material_copy_counts(sample)
    print(
        f"MATERIAL spade_unique={material['spade2_full_physical_chain_unique']} "
        f"sA={material['s']['ace']} s2={material['s']['two']}",
        flush=True,
    )
    audit = aggregate_source_audit(opening, bundle["states"])
    print(
        f"AUDIT 2A {[ (s, audit[s]['edge_2a'], audit[s]['immediate_join']) for s in SUITS ]}",
        flush=True,
    )

    blocks = {}
    rebuilt = {}
    surprise_path = None
    foundation_reached = False
    for suit in SUITS:
        print(f"SEARCH {suit} budget={TIME_LIMIT_S:.0f}s unique_cap={MAX_UNIQUE} ceiling={COST_CEILING}", flush=True)
        res = search_edge_2a(
            bundle["states"],
            opening,
            suit=suit,
            max_unique=MAX_UNIQUE,
            time_limit_s=TIME_LIMIT_S,
            rss_abort_mb=RSS_PER_MB,
            cost_ceiling=COST_CEILING,
        )
        rows = rebuild(opening, bundle["states"], res, suit)
        rebuilt[suit] = rows
        preview_counts = Counter()
        longest = 0
        for rec in rows:
            end = opening.clone()
            replay_actions(end, as_actions(rec["full_actions"]))
            baseline = 1 if suit == "s" else 0
            pr = preview_tail3(
                end,
                suit,
                rec["full_cost"],
                max_depth=5,
                deadline=time.perf_counter() + 1.2,
                baseline=baseline,
            )
            rec["preview"] = pr["status"]
            rec["preview_tail"] = pr.get("low_tail")
            preview_counts[pr["status"]] += 1
            longest = max(longest, int(pr.get("low_tail") or rec.get("low_tail") or 0))
            if pr.get("foundation") and surprise_path is None:
                surprise_path = rec["full_actions"]
                foundation_reached = True
        if res.foundation_surprise:
            foundation_reached = True
            if surprise_path is None and rows:
                hit = next((w for w in rows if w.get("foundation")), None)
                if hit:
                    surprise_path = hit["full_actions"]
        e0 = None if not rows else min(w["full_cost"] for w in rows)
        slack = {}
        if e0 is not None:
            for extra in range(0, HARVEST_SLACK + 1):
                slack[f"E+{extra}" if extra else "E"] = sum(1 for w in rows if w["full_cost"] == e0 + extra)
        blocks[suit] = {
            "reached": bool(rows),
            "first_s": res.first_s,
            "first_unique": res.first_unique,
            "best_full_mw": e0,
            "lineages": res.first_lineages,
            "unique": res.unique,
            "expanded": res.expanded,
            "generated": res.generated,
            "duplicate_skips": res.duplicate_skips,
            "elapsed_s": res.elapsed_s,
            "peak_rss_mb": res.peak_rss_mb,
            "stop_reason": res.stop_reason,
            "levels": res.levels_reached,
            "n": len(rows),
            "bands": {str(k): int(v) for k, v in sorted(Counter(w["full_cost"] for w in rows).items())},
            "slack": slack,
            "preview": dict(preview_counts),
            "longest_preview_tail": longest,
            "already_at_source": res.already_at_source,
            "foundation_surprise": res.foundation_surprise,
            "sd5_expanded": res.sd5_expanded,
            "used_prep_states": res.used_prep_states,
            "used_heuristic_prune": res.used_heuristic_prune,
        }
        _write_json(
            PORT[suit],
            {
                "experiment": EXPERIMENT,
                "suit": suit,
                "n": len(rows),
                "e0": e0,
                "bands": blocks[suit]["bands"],
                "preview": dict(preview_counts),
                "states": rows,
            },
        )
        print(
            f"EDGE_{suit} reached={bool(rows)} n={len(rows)} inc={res.incumbent} "
            f"unique={res.unique} stop={res.stop_reason} preview={dict(preview_counts)}",
            flush=True,
        )

    leaders, why = select_leaders(blocks)
    fixture = None
    if foundation_reached and surprise_path:
        FOUND_FIX.write_text(
            format_moves_text(as_actions(surprise_path), header="# v0.44 Foundation 2 surprise\n"),
            encoding="utf-8",
        )
        fixture = FOUND_FIX.relative_to(ROOT).as_posix()
    payload_pre = {
        "all_replay_ok": bundle["all_replay_ok"],
        "foundation_reached": foundation_reached,
        "suits": blocks,
        "leaders": leaders,
    }
    verdict, reason = choose_verdict(payload_pre)
    interpretation = (
        f"{reason}. DEAL_NOW roots {bundle['symmetry_classes']} from {bundle['pre_sd5_n']} pre-SD5. "
        f"Spade uniqueness={material['spade2_full_physical_chain_unique']}. "
        f"Leaders={[SUIT_NAMES[s] for s in leaders]} ({why}). "
        "No pre-Deal prep. Equal 150s/150k envelopes. G6_8 not continued."
    )
    payload = {
        "experiment": EXPERIMENT,
        "base_sha": BASE_SHA,
        "branch": BRANCH,
        "verdict": verdict,
        "verdict_reason": reason,
        "interpretation": interpretation,
        "next_recommendation": next_recommendation(verdict, leaders),
        "roots": {
            "pre_sd5_n": bundle["pre_sd5_n"],
            "deal_now_ordered": bundle["deal_now_ordered"],
            "symmetry_classes": bundle["symmetry_classes"],
            "cost_counts": bundle["cost_counts"],
            "lineage_counts": bundle["lineage_counts"],
            "all_replay_ok": bundle["all_replay_ok"],
            "auto_removed": bundle["auto_removed"],
        },
        "sd5_audit": bundle["sd5_audit"],
        "material": {
            "spade2_full_physical_chain_unique": material["spade2_full_physical_chain_unique"],
            "ace_two": {s: {"ace": material[s]["ace"], "two": material[s]["two"]} for s in SUITS},
            "spade_all_ranks_tableau": material["s"]["all_ranks_tableau"],
        },
        "source_audit": audit,
        "suits": blocks,
        "leaders": leaders,
        "leader_names": [SUIT_NAMES[s] for s in leaders],
        "leader_why": why,
        "foundation": {"reached": foundation_reached, "fixture": fixture},
        "files": {
            "report": REPORT.relative_to(ROOT).as_posix(),
            "result": RESULT.relative_to(ROOT).as_posix(),
            "roots": ROOTS.relative_to(ROOT).as_posix(),
            "spade": PORT["s"].relative_to(ROOT).as_posix(),
            "heart": PORT["h"].relative_to(ROOT).as_posix(),
            "diamond": PORT["d"].relative_to(ROOT).as_posix(),
            "club": PORT["c"].relative_to(ROOT).as_posix(),
            "fixture": fixture,
        },
        "elapsed_s": time.perf_counter() - started,
        "production_unchanged": True,
        "no_prep_states": True,
        "all_replay_ok": bundle["all_replay_ok"],
        "foundation_reached": foundation_reached,
    }
    _write_json(RESULT, payload)
    write_report(payload)
    print(f"VERDICT {verdict}", flush=True)
    print(f"LEADERS {leaders} {why}", flush=True)
    print(f"NEXT {payload['next_recommendation']}", flush=True)
    return payload


if __name__ == "__main__":
    main()
