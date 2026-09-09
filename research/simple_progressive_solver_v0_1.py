#!/usr/bin/env python3
"""Independent E1/E2/E3 envelopes for the simple progressive solver on 4925153."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.deal import load_deal
from spider.engine import SpiderState
from spider.metrics import replay_actions
from spider.simple_progressive_solver import format_moves_text, solve_progressive
from spider.state_identity import canonical_state_key


EXPERIMENT = "simple_progressive_solver_v0_1"
BASE_SHA = "a10578240dd10d2c3c8a4b385ed2534ec341967f"
DEAL_PATH = ROOT / "deals" / "4925153.txt"
RESULT = ROOT / "docs" / "research" / f"{EXPERIMENT}.json"
REPORT = ROOT / "docs" / "research" / f"{EXPERIMENT}.md"
SOLUTION = ROOT / "solutions" / "4925153_simple_v0_1.moves.txt"
CHECKPOINTS = ROOT / "research" / "results" / EXPERIMENT

# Independent envelopes.  E3 is skipped when E2 throughput/memory cannot
# support it in a bounded run.
ENVELOPES = (
    ("E1", 100_000, 300.0),
    ("E2", 1_000_000, 1500.0),
    ("E3", 10_000_000, 2400.0),
)

STRATEGIC_EXPANSIONS = 400
STRATEGIC_SECONDS = 530.0  # P0 CURRENT_FUNNEL coalescing v0.1 wall


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temp.replace(path)


def load_opening() -> SpiderState:
    cards = list(load_deal(DEAL_PATH))
    return SpiderState.from_cards(cards)


def compact(opening: SpiderState, result) -> dict:
    replay = None
    if result.actions:
        end = opening.clone()
        paid = replay_actions(end, list(result.actions))
        replay = {
            "cost_matches": paid == result.cost,
            "foundations": len(end.foundations),
            "face_down": sum(len(col.face_down) for col in end.columns),
            "stock_rows": len(end.stock) // 10,
            "solved": end.is_solved(),
            "path_length": len(result.actions),
            "mobilityware_moves": paid,
        }
    stats = result.stats
    return {
        "solved": result.solved,
        "max_foundations": result.max_foundations,
        "identified_face_down": result.identified_face_down,
        "identified_stock_rows": result.identified_stock_rows,
        "pass_reached": result.pass_reached,
        "nodes": result.nodes,
        "elapsed_s": result.elapsed_s,
        "states_per_sec": result.states_per_sec,
        "cost": result.cost,
        "path_length": len(result.actions),
        "stop_reason": result.stop_reason,
        "replay_ok": result.replay_ok,
        "replay": replay,
        "opening_face_down": sum(len(col.face_down) for col in opening.columns),
        "opening_stock_rows": len(opening.stock) // 10,
        "first_foundation_path_length": len(result.first_foundation_actions),
        "stats": {
            "states_expanded": stats.states_expanded,
            "states_generated": stats.states_generated,
            "unique_exact_states": stats.unique_exact_states,
            "tt_hits": stats.tt_hits,
            "duplicate_children": stats.duplicate_children,
            "path_cycles": stats.path_cycles,
            "inverses": stats.inverses,
            "max_depth": stats.max_depth,
            "considered_by_tier": list(stats.considered_by_tier),
            "expanded_by_tier": list(stats.expanded_by_tier),
            "deals_considered": stats.deals_considered,
            "deals_executed": stats.deals_executed,
            "deal_now_choices": stats.deal_now_choices,
            "prepared_deal_choices": stats.prepared_deal_choices,
            "prep_calls": stats.prep_calls,
            "prep_nodes": stats.prep_nodes,
            "first_foundation_node": stats.first_foundation_node,
            "first_foundation_depth": stats.first_foundation_depth,
            "first_foundation_pass": stats.first_foundation_pass,
            "max_foundations": stats.max_foundations,
            "peak_rss_mb": stats.peak_rss_mb,
            "tt_hit_rate": (
                stats.tt_hits / max(1, stats.tt_hits + stats.states_expanded)
            ),
        },
    }


def run_envelope(name: str, max_nodes: int, time_limit_s: float, opening: SpiderState) -> dict:
    print(f"START {name} nodes={max_nodes} time={time_limit_s}", flush=True)
    started = time.perf_counter()
    result = solve_progressive(
        opening,
        max_nodes=max_nodes,
        time_limit_s=time_limit_s,
        target_foundations=8,
        max_pass=3,
        prep_ply=1,
    )
    payload = compact(opening, result)
    payload["elapsed_wall_s"] = time.perf_counter() - started
    payload["envelope"] = name
    payload["max_nodes"] = max_nodes
    payload["time_limit_s"] = time_limit_s
    print(
        f"DONE {name} solved={payload['solved']} fnd={payload['max_foundations']} "
        f"fd={payload['identified_face_down']} stock={payload['identified_stock_rows']} "
        f"nodes={payload['nodes']} sps={payload['states_per_sec']:.1f} "
        f"pass={payload['pass_reached']} stop={payload['stop_reason']} "
        f"replay={payload['replay_ok']}",
        flush=True,
    )
    if result.solved and result.replay_ok:
        header = (
            f"# Simple progressive solver v0.1 — deal 4925153 envelope {name}\n"
            f"# primitive_moves: {len(result.actions)}\n"
            f"# mobilityware_moves: {result.cost}\n"
            f"# states_expanded: {result.nodes}\n"
            f"# pass: {result.pass_reached}\n"
        )
        SOLUTION.write_text(
            format_moves_text(result.actions, header=header), encoding="utf-8"
        )
        payload["solution_path"] = str(SOLUTION.relative_to(ROOT)).replace("\\", "/")
        print(f"WROTE {SOLUTION}", flush=True)
    return payload


def choose_verdict(runs: dict) -> tuple[str, str]:
    ordered = [runs[name] for name, _n, _t in ENVELOPES if name in runs]
    if not ordered:
        return "INCONCLUSIVE", "no envelopes ran"
    best = ordered[-1]
    for row in ordered:
        if row.get("solved") and row.get("replay_ok"):
            return (
                "SIMPLE_SOLVER_COMPLETE_SOLUTION",
                f"{row['envelope']} solved 4925153 in {row['path_length']} primitive moves",
            )
    if any(row["max_foundations"] >= 1 and row.get("replay_ok") for row in ordered):
        hit = next(row for row in ordered if row["max_foundations"] >= 1)
        return (
            "SIMPLE_SOLVER_FOUNDATION_PROGRESS",
            f"{hit['envelope']} reached {hit['max_foundations']} replay-valid foundation(s)",
        )
    sps = best["states_per_sec"]
    unique = best["stats"]["unique_exact_states"]
    fd = best["identified_face_down"]
    if sps >= 200 and unique >= 20_000 and fd < 44:
        return (
            "SIMPLE_SOLVER_SEARCH_PROMISING",
            f"{best['envelope']} expanded {best['nodes']} exact states at {sps:.0f}/s "
            f"with joint fd={fd}; no foundation yet",
        )
    if sps < 50 and best["nodes"] < 20_000:
        return (
            "SIMPLE_SOLVER_STATE_EXPLOSION",
            "throughput too low for useful exact-state coverage",
        )
    if best["pass_reached"] >= 3 and best["stats"]["expanded_by_tier"][0] > 10 * max(
        1, sum(best["stats"]["expanded_by_tier"][1:])
    ):
        return (
            "SIMPLE_SOLVER_HEURISTIC_TRAP",
            "widening reached pass 3 but expansions remained concentrated in Tier A",
        )
    return (
        "SIMPLE_SOLVER_SEARCH_PROMISING",
        f"bounded exact search ran; best joint fd={fd} with {best['nodes']} expansions",
    )


def skip_e3(e2: dict) -> str | None:
    sps = e2["states_per_sec"]
    rss = e2["stats"].get("peak_rss_mb") or 0.0
    if e2.get("solved"):
        return "E2 already solved"
    if sps < 400:
        return f"E2 throughput {sps:.0f}/s cannot bound 10M nodes"
    if rss and rss > 2048:
        return f"E2 peak RSS {rss:.0f} MiB would not scale to 10M"
    estimate = 10_000_000 / max(sps, 1.0)
    if estimate > 2700:
        return f"E3 estimate {estimate:.0f}s exceeds bounded run"
    return None


def write_report(result: dict) -> None:
    runs = result["runs"]
    best_name = result["primary_envelope"]
    best = runs[best_name]
    stats = best["stats"]
    tt_rate = stats["tt_hit_rate"]
    strategic_sps = STRATEGIC_EXPANSIONS / STRATEGIC_SECONDS
    lines = [
        "# Simple Progressive Search Baseline v0.1",
        "",
        "## 1. Verdict",
        "",
        f"`{result['verdict']}` — {result['note']}.",
        "",
        "Competing solver, not a patch to the strategic controller.  Objective:",
        "any replay-valid complete solution of deal 4925153.  Move count is not",
        "optimised toward the 119-move external benchmark or the 172-move canonical line.",
        "",
        "## 2. Solver architecture",
        "",
        "One iterative DFS over ordinary legal Spider actions (tableau transfer and",
        "stock Deal).  Working state is mutated in place with column/stock snapshots",
        "for backtracking.  Children are ordered by a four-tier desirability band,",
        "then a cheap local score.  Exact packed identity (`pack_state`, same fields",
        "as `canonical_state_key`) plus the current relaxation pass is the",
        "transposition key.  Inverse moves, ancestor recurrence, and equivalent",
        "child states are suppressed locally.  Passes 0–3 widen permission from",
        "Tier A through D; remaining node/time budget is split across remaining",
        "passes so a huge A-graph cannot starve later tiers.  Deal is a planned",
        "action scored from the known next stock row, with a 1-ply (optional 2-ply)",
        "preparation lookahead.  No controller, scheduler, allocator, campaign,",
        "registry, project, or reservation objects.",
        "",
        "## 3. Move tiers/order",
        "",
        "| Tier | Pass | Meaning |",
        "| --- | ---: | --- |",
        "| A | 0 | foundation, reveal, same-suit extend, create empty, strongly constructive Deal |",
        "| B | 1 | mixed build, king-to-empty, moderate Deal, same-suit after a join-break |",
        "| C | 2 | join-break rework, consume empty, mediocre Deal |",
        "| D | 3 | remaining legal actions, including badly landing Deals |",
        "",
        "Within a permitted tier: foundation > reveal > empty > same-suit length,",
        "minus join-break / last-empty consumption.  An identified 1-ply Deal prep",
        "is boosted ahead of Deal-now.",
        "",
        "## 4. Exact-memory/backtracking model",
        "",
        "TT stores the highest pass at which a packed exact state was started and",
        "the highest pass at which it finished.  Skip if `seen` or `done` coverage",
        "is at least the current pass.  Broader coverage subsumes narrower.",
        "A pass-0 exhaustion does not mark pass 3.  Incomplete expansions (budget",
        "abort) are not marked done.  Path keys prevent ancestor recurrence.",
        "",
        "## 5. Perfect-information Deal planning",
        "",
        "Next row is `state.stock[-10:]` landing on columns 1–10.  Signals: same-suit",
        "parent, mixed rank adjacency, empty landings, buried tops, buried same-suit",
        "runs of length ≥ 3.  1-ply lookahead applies up to 12 cheap A/B tableau",
        "moves, scores the resulting Deal, and restores.  2-ply is attempted only",
        "when that candidate set is tiny.  Unrestricted Deal legality is obeyed",
        "(empties do not block Deal under `MW_RULES`).",
        "",
        "## 6. Throughput benchmark",
        "",
        "| Envelope | Expanded | Unique | s | states/s | TT hit rate | Peak RSS MiB | Max depth |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for name, _n, _t in ENVELOPES:
        if name not in runs:
            lines.append(f"| {name} | — | — | — | — | — | — | — |")
            continue
        row = runs[name]
        st = row["stats"]
        rss = st.get("peak_rss_mb")
        rss_s = f"{rss:.1f}" if rss is not None else "n/a"
        lines.append(
            f"| {name} | {row['nodes']} | {st['unique_exact_states']} | "
            f"{row['elapsed_s']:.1f} | {row['states_per_sec']:.1f} | "
            f"{st['tt_hit_rate']:.3f} | {rss_s} | {st['max_depth']} |"
        )
    lines.extend(
        [
            "",
            f"Strategic-controller historical rate (coalescing v0.1 P0, 400 expansions",
            f"in ~{STRATEGIC_SECONDS:.0f}s): **{strategic_sps:.2f} strategic expansions/s**.",
            "These are not semantically equivalent to primitive exact-state expansions.",
            "",
            "## 7. 4925153 search results",
            "",
        ]
    )
    for name, _n, _t in ENVELOPES:
        if name not in runs:
            if name == "E3" and result.get("e3_skip"):
                lines.append(f"- {name}: skipped ({result['e3_skip']}).")
            continue
        row = runs[name]
        replay = row.get("replay") or {}
        st = row["stats"]
        lines.append(
            f"- {name}: solved={row['solved']} foundations={row['max_foundations']} "
            f"joint fd={row['identified_face_down']} stock_rows={row['identified_stock_rows']} "
            f"cost={row['cost']} length={row['path_length']} pass={row['pass_reached']} "
            f"nodes={row['nodes']} unique={st['unique_exact_states']} "
            f"gen={st['states_generated']} tt_hits={st['tt_hits']} "
            f"dups={st['duplicate_children']} cycles={st['path_cycles']} "
            f"inverses={st['inverses']} depth={st['max_depth']} "
            f"tiers considered={st['considered_by_tier']} expanded={st['expanded_by_tier']} "
            f"deals considered/executed={st['deals_considered']}/{st['deals_executed']} "
            f"deal-now={st['deal_now_choices']} prepared={st['prepared_deal_choices']} "
            f"prep calls/nodes={st['prep_calls']}/{st['prep_nodes']} "
            f"stop={row['stop_reason']} replay={row['replay_ok']} "
            f"replay_fd={replay.get('face_down')} replay_stock={replay.get('stock_rows')}."
        )
    ff = stats
    lines.extend(
        [
            "",
            "## 8. First-foundation result",
            "",
        ]
    )
    if ff["first_foundation_node"] is None:
        lines.append(
            "No replay-valid foundation on 4925153 in the completed envelopes."
        )
    else:
        lines.append(
            f"First foundation at expanded node {ff['first_foundation_node']}, "
            f"depth {ff['first_foundation_depth']}, pass {ff['first_foundation_pass']}, "
            f"path length {best.get('first_foundation_path_length', best['path_length'])}."
        )
    lines.extend(
        [
            "",
            "## 9. Complete-solution result",
            "",
        ]
    )
    solved_row = next((runs[n] for n, *_ in ENVELOPES if n in runs and runs[n]["solved"]), None)
    if solved_row:
        lines.append(
            f"Yes. Envelope {solved_row['envelope']}: {solved_row['path_length']} primitive "
            f"moves, MobilityWare {solved_row['cost']}, expanded {solved_row['nodes']}, "
            f"unique {solved_row['stats']['unique_exact_states']}, "
            f"{solved_row['elapsed_s']:.1f}s, max depth {solved_row['stats']['max_depth']}, "
            f"pass {solved_row['pass_reached']}. Replay verified. "
            f"Artefact: `solutions/4925153_simple_v0_1.moves.txt`."
        )
    else:
        lines.append("No complete solution in the completed envelopes.")
    considered = stats["considered_by_tier"]
    expanded = stats["expanded_by_tier"]
    lines.extend(
        [
            "",
            "## 10. Search-space anatomy",
            "",
            f"On {best_name}, legal moves considered by tier A/B/C/D = {considered}.",
            f"Expanded by tier = {expanded}.",
            f"Duplicate children removed = {stats['duplicate_children']}; "
            f"path cycles = {stats['path_cycles']}; inverses = {stats['inverses']}.",
            f"Deals considered {stats['deals_considered']}, executed {stats['deals_executed']}; "
            f"prep lookahead calls {stats['prep_calls']} using {stats['prep_nodes']} nodes.",
            "Branching is dominated by ordinary tableau transfers; Deal is sparse relative",
            "to tableau children.  Exact TT and inverse cuts are the main reducers.",
            "",
            "## 11. Comparison with strategic-controller granularity",
            "",
            f"Simple solver primitive exact-state rate on {best_name}: "
            f"**{best['states_per_sec']:.1f}/s**.",
            f"Strategic controller recent 4-suit 400-expansion runs: about "
            f"**{strategic_sps:.2f} strategic expansions/s** (~{STRATEGIC_SECONDS:.0f}s wall,",
            "each expansion itself a tactical search of up to 300k nodes plus campaign",
            "machinery).  Memory here is one packed exact key per visited state",
            f"({stats['unique_exact_states']} unique; peak RSS "
            f"{stats.get('peak_rss_mb') or 'n/a'} MiB).",
            "Do not treat the two expansion types as equivalent.  The comparison is",
            "granularity: this solver asks how far cheap ordered exact backtracking",
            "gets when the unit of search is a legal Spider action.",
            "",
            f"Strategic controller first foundations on 4925153 in those runs: **0**.",
            f"This solver first foundations: **{best['max_foundations']}**; "
            f"complete solution: **{bool(solved_row)}**.",
            "",
            "## 12. One next bounded recommendation",
            "",
            result["next_recommendation"],
            "",
            "## Integrity",
            "",
            f"Base SHA `{result['base_sha']}`. Independent envelopes from `deals/4925153.txt`.",
            "Human canonical line was not used to seed, train, or guide search.",
            "Returned paths replay through `replay_actions`. Solver does not import",
            "planner policy. Anytime controller is unchanged.",
            "",
        ]
    )
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def next_recommendation(verdict: str) -> str:
    if verdict == "SIMPLE_SOLVER_COMPLETE_SOLUTION":
        return (
            "Keep this solver separate and measure solution length only after a second "
            "independent complete solve; do not fold it into the strategic controller."
        )
    if verdict == "SIMPLE_SOLVER_FOUNDATION_PROGRESS":
        return (
            "Rerun the same solver from the first-foundation state with the same "
            "A–D / exact-TT policy and a fresh E2 envelope; do not add campaign machinery."
        )
    if verdict == "SIMPLE_SOLVER_SEARCH_PROMISING":
        return (
            "Add iterative deepening on primitive depth (bands well above the 174-move "
            "human line, e.g. 80/160/320) so the same A–D exact-TT solver spends nodes "
            "on distinct early positions instead of 5000-move shuffles; do not add a controller."
        )
    if verdict == "SIMPLE_SOLVER_STATE_EXPLOSION":
        return (
            "Replace clone/pack in the inner loop with incremental exact keys; do not "
            "add a strategic layer."
        )
    if verdict == "SIMPLE_SOLVER_HEURISTIC_TRAP":
        return (
            "Change only the widening trigger so C/D permission arrives earlier in a "
            "single DFS, still without proof-pruning those moves."
        )
    if verdict == "SIMPLE_SOLVER_RULE_OR_ENGINE_BLOCKER":
        return (
            "Fix the shared engine bug that blocked legal Deal or identity, then rerun "
            "this same solver unchanged."
        )
    return (
        "Reproduce the harness on a clean worktree before judging the hypothesis; "
        "do not grow the strategic controller in response."
    )


def main() -> int:
    CHECKPOINTS.mkdir(parents=True, exist_ok=True)
    opening = load_opening()
    _ = canonical_state_key(opening)
    runs: dict = {}
    e3_skip = None
    for name, max_nodes, limit in ENVELOPES:
        if name == "E3":
            e3_skip = skip_e3(runs["E2"]) if "E2" in runs else "E2 missing"
            if e3_skip:
                print(f"SKIP E3 ({e3_skip})", flush=True)
                break
        path = CHECKPOINTS / f"{name}.json"
        measured = run_envelope(name, max_nodes, limit, opening)
        _write_json(path, measured)
        runs[name] = measured
        if measured.get("solved") and measured.get("replay_ok"):
            print("STOP complete solution; later envelopes not required", flush=True)
            break
    primary = [name for name, *_ in ENVELOPES if name in runs][-1]
    verdict, note = choose_verdict(runs)
    payload = {
        "experiment": EXPERIMENT,
        "base_sha": BASE_SHA,
        "deal": "deals/4925153.txt",
        "envelopes": [
            {"name": n, "max_nodes": a, "time_limit_s": b} for n, a, b in ENVELOPES
        ],
        "runs": runs,
        "primary_envelope": primary,
        "verdict": verdict,
        "note": note,
        "e3_skip": e3_skip,
        "next_recommendation": next_recommendation(verdict),
        "strategic_controller_ref": {
            "expansions": STRATEGIC_EXPANSIONS,
            "seconds": STRATEGIC_SECONDS,
            "expansions_per_sec": STRATEGIC_EXPANSIONS / STRATEGIC_SECONDS,
            "first_foundations": 0,
            "source": "docs/research/project_intent_coalescing_v0_1.json P0 CURRENT_FUNNEL",
        },
    }
    _write_json(RESULT, payload)
    write_report(payload)
    print(f"VERDICT {verdict}")
    print(f"WROTE {RESULT}")
    print(f"WROTE {REPORT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
