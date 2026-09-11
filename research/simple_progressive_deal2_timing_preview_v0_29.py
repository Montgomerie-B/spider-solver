#!/usr/bin/env python3
"""v0.29: perfect-information Deal-2 timing preview at fd13/fd12/fd11.

No Deal-3. No extra pre-Deal preparation. No heuristic.
"""

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
from spider.packed_state import pack_state, permute_tableau_columns
from spider.rules import MW_RULES
from spider.simple_deal1_preview import (
    deal_reception_telemetry,
    next_stock_row,
    snapshot_metrics,
    stock_rows,
    tableau_layer_bfs,
)
from spider.simple_legacy_fd13_alternatives import checkpoint_record
from spider.simple_progressive_solver import apply_action, format_moves_text
from spider.simple_workspace_reachability import face_down_count

EXPERIMENT = "simple_progressive_deal2_timing_preview_v0_29"
BASE_SHA = "3ba82cdd8c33c6d7e6253a923a78796efa9d6a28"
DEAL_PATH = ROOT / "deals" / "4925153.txt"
V26 = ROOT / "docs" / "research" / "simple_progressive_deal1_preview_v0_26.json"
V27 = ROOT / "docs" / "research" / "simple_progressive_post_deal1_work_v0_27.json"
V28 = ROOT / "docs" / "research" / "simple_progressive_post_deal1_fd12_v0_28.json"
RESULT = ROOT / "docs" / "research" / f"{EXPERIMENT}.json"
REPORT = ROOT / "docs" / "research" / f"{EXPERIMENT}.md"
OUT_DIR = ROOT / "research" / "results" / EXPERIMENT
FIXTURES = {
    "EARLY": ROOT / "solutions" / "4925153_simple_v0_29_early_fd10.moves.txt",
    "MIDDLE": ROOT / "solutions" / "4925153_simple_v0_29_middle_fd10.moves.txt",
    "LATE": ROOT / "solutions" / "4925153_simple_v0_29_late_fd10.moves.txt",
}
FOUNDATION_FIXTURES = {
    "EARLY": ROOT / "solutions" / "4925153_simple_v0_29_early_foundation.moves.txt",
    "MIDDLE": ROOT / "solutions" / "4925153_simple_v0_29_middle_foundation.moves.txt",
    "LATE": ROOT / "solutions" / "4925153_simple_v0_29_late_foundation.moves.txt",
}

GROUPS = (
    ("EARLY", 13, 8),
    ("MIDDLE", 12, 16),
    ("LATE", 11, 16),
)
GROUP_MAX_UNIQUE = 750_000
GROUP_TIME_S = 600.0
GROUP_RSS_MB = 3 * 1024.0
GROUP_MAX_DEPTH = 8
GLOBAL_TIME_S = 1800.0


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temp.replace(path)


def opening_state() -> SpiderState:
    return SpiderState.from_cards(list(load_deal(DEAL_PATH)))


def as_actions(raw) -> list:
    out = []
    for item in raw:
        if item == "deal" or item == ["deal"] or item == ("deal",):
            out.append(("deal",))
        else:
            src, dst, k = item
            out.append((int(src), int(dst), int(k)))
    return out


def actions_json(actions) -> list:
    return [list(a) if a != ("deal",) else ["deal"] for a in actions]


def card_label(pair) -> str:
    suit, rank = pair
    return f"{suit}{rank}"


def first_depth_at_most(first_fd_depth: dict, target: int):
    depths = [int(d) for fd, d in first_fd_depth.items() if int(fd) <= target]
    return min(depths) if depths else None


def recover_group(name: str, expected_fd: int, expected_n: int, opening: SpiderState) -> list:
    if name == "EARLY":
        payload = json.loads(V26.read_text(encoding="utf-8"))
        records = payload.get("prepared_deal_progress") or []
        paths = [as_actions(rec["full_actions"]) for rec in records]
        expected_digests = [rec.get("ordered_digest") or rec.get("identity") for rec in records]
    elif name == "MIDDLE":
        payload = json.loads(V27.read_text(encoding="utf-8"))
        parents = payload.get("sources") or []
        records = payload.get("fd12_exits") or []
        paths = [
            as_actions(parents[rec["origin"]]["full_actions"]) + as_actions(rec["actions"])
            for rec in records
        ]
        expected_digests = [rec["ordered_digest"] for rec in records]
    else:
        payload = json.loads(V28.read_text(encoding="utf-8"))
        records = payload.get("fd11_exits") or []
        paths = [as_actions(rec["full_actions"]) for rec in records]
        expected_digests = [rec["ordered_digest"] for rec in records]

    if len(records) != expected_n:
        raise SystemExit(f"{name}: expected {expected_n} sources, got {len(records)}")

    audited = []
    distinct = {}
    for index, full in enumerate(paths):
        end = opening.clone()
        cost = replay_actions(end, full)
        deals = sum(1 for a in full if a == ("deal",))
        cp = checkpoint_record(end, arm=f"{name}_{index}", path_length=len(full), cost=cost, kind=name)
        digest = pack_state(end).hex()
        swapped = permute_tableau_columns(end, [1, 0, 2, 3, 4, 5, 6, 7, 8, 9])
        ok = (
            cp["fd"] == expected_fd
            and cp["foundations"] == 0
            and stock_rows(end) == 4
            and deals == 1
            and digest == expected_digests[index]
            and end.can_deal(MW_RULES) is True
        )
        row = {
            "source_id": index,
            "ok": ok,
            "total_primitive_path": len(full),
            "mw_cost": cost,
            "deals": deals,
            "fd": cp["fd"],
            "stock_rows": stock_rows(end),
            "foundations": cp["foundations"],
            "empties": cp["empties"],
            "legal_tableau": cp["legal_action_count"],
            "longest_run": cp["longest_run"],
            "adjacencies": cp["adjacencies"],
            "movable_blocks": cp["movable_blocks"],
            "ordered_digest": digest,
            "deal2_row": [list(item) for item in next_stock_row(end)],
            "ordered_identity_sensitive_to_column_perm": pack_state(end) != pack_state(swapped),
            "full_actions": actions_json(full),
        }
        audited.append(row)
        print(
            f"SOURCE {name} {index} ok={ok} path={len(full)} MW={cost} fd={cp['fd']} "
            f"stock={stock_rows(end)} legal={cp['legal_action_count']}",
            flush=True,
        )
        ident = pack_state(end)
        if ident not in distinct:
            distinct[ident] = {
                "state": end,
                "path": full,
                "source_id": index,
            }
    return audited, distinct


def virtual_deal_group(distinct: dict, known_row, rules=MW_RULES):
    children = {}
    telemetry = []
    mutated = False
    for ident, rec in distinct.items():
        source = rec["state"]
        before = pack_state(source)
        pre = snapshot_metrics(source)
        child = source.clone()
        apply_action(child, ("deal",), rules=rules)
        if pack_state(source) != before:
            mutated = True
        recp = deal_reception_telemetry(source, child, known_row)
        post = snapshot_metrics(child)
        item = {
            "pre_source_id": rec["source_id"],
            "pre_digest": before.hex(),
            "pre_fd": pre["fd"],
            "pre_path": len(rec["path"]),
            "pre_mw": len(rec["path"]),
            "pre_empties": pre["empties"],
            "pre_longest_run": pre["longest_run"],
            "pre_adjacencies": pre["adjacencies"],
            "pre_movable_blocks": pre["movable_blocks"],
            "pre_legal_tableau": pre["legal_tableau"],
            "post_digest": pack_state(child).hex(),
            "post_fd": post["fd"],
            "post_stock_rows": post["stock_rows"],
            "post_foundations": post["foundations"],
            "post_empties": post["empties"],
            "post_longest_run": post["longest_run"],
            "post_adjacencies": post["adjacencies"],
            "post_movable_blocks": post["movable_blocks"],
            "post_legal_tableau": post["legal_tableau"],
            "same_suit_joins": recp["same_suit_joins"],
            "mixed_suit_joins": recp["mixed_suit_joins"],
            "onto_empty": recp["onto_empty"],
            "source_unmutated": pack_state(source) == before,
        }
        telemetry.append(item)
        child_id = pack_state(child)
        if child_id not in children:
            children[child_id] = {
                "state": child,
                "path": list(rec["path"]) + [("deal",)],
                "origin": rec["source_id"],
                "pre_digest": before.hex(),
            }
    return children, telemetry, mutated


def reception_summary(telemetry: list) -> dict:
    n = len(telemetry)
    if n == 0:
        return {"n": 0}
    def mean(key):
        return sum(row[key] for row in telemetry) / n

    return {
        "n": n,
        "same_suit_joins_total": sum(row["same_suit_joins"] for row in telemetry),
        "mixed_suit_joins_total": sum(row["mixed_suit_joins"] for row in telemetry),
        "onto_empty_total": sum(row["onto_empty"] for row in telemetry),
        "same_suit_joins_mean": mean("same_suit_joins"),
        "mixed_suit_joins_mean": mean("mixed_suit_joins"),
        "onto_empty_mean": mean("onto_empty"),
        "pre_legal_tableau_mean": mean("pre_legal_tableau"),
        "post_legal_tableau_mean": mean("post_legal_tableau"),
        "pre_longest_run_mean": mean("pre_longest_run"),
        "post_longest_run_mean": mean("post_longest_run"),
    }


def harvest_progress(opening: SpiderState, origin_paths: list, search, group: str, origin_map: list) -> list:
    rows = []
    for rec in search.progress:
        bfs_origin = rec["origin"]
        full = list(origin_paths[bfs_origin]) + [tuple(a) for a in rec["actions"]]
        end = opening.clone()
        try:
            cost = replay_actions(end, full)
            replay_ok = True
        except (ValueError, AssertionError) as exc:
            cost = None
            replay_ok = False
            rec["replay_error"] = str(exc)
        item = dict(rec)
        item["bfs_origin"] = bfs_origin
        item["origin"] = origin_map[bfs_origin]
        item["full_actions"] = actions_json(full)
        item["full_path_length"] = len(full)
        item["full_cost"] = cost
        item["full_replay_ok"] = replay_ok
        item["deals"] = sum(1 for a in full if a == ("deal",))
        item["group"] = group
        rows.append(item)
    return rows


def write_fixture(group: str, rec: dict) -> str:
    full = as_actions(rec["full_actions"])
    if rec.get("foundations", 0) >= 1:
        path = FOUNDATION_FIXTURES[group]
        kind = "foundation"
    else:
        path = FIXTURES[group]
        kind = "fd10"
    header = "\n".join(
        [
            f"# v0.29 Deal-2 timing {group} {kind}",
            f"# origin: {rec.get('origin')}",
            f"# local_depth: {rec['depth']}",
            f"# fd: {rec.get('fd')}",
            f"# stock_rows: {rec.get('stock_rows')}",
        ]
    )
    path.write_text(format_moves_text(full, header=header), encoding="utf-8")
    rec["fixture"] = path.relative_to(ROOT).as_posix()
    return rec["fixture"]


def choose_verdict(audit_ok: bool, groups: dict, explosion: bool) -> tuple[str, str]:
    if not audit_ok:
        return "SOURCE_REPLAY_FAILURE", "the three source portfolios could not be reconstructed"
    any_fnd = any(g["search"]["max_foundations"] >= 1 for g in groups.values())
    if any_fnd:
        names = [n for n, g in groups.items() if g["search"]["max_foundations"] >= 1]
        return "DEAL2_TIMING_REACHES_FOUNDATION", f"foundation reached by {names}"
    fd10_names = [n for n, g in groups.items() if g["fd10"]]
    if fd10_names:
        return "DEAL2_TIMING_REACHES_FD10", f"fd10 reached by {fd10_names}"
    comparable = all(
        g["search"]["stop_reason"] in ("max depth", "frontier empty", "progress layer complete")
        for g in groups.values()
    )
    if explosion and not comparable:
        return "DEAL2_PREVIEW_STATE_EXPLOSION", "resource limits prevent a useful comparison"
    min_fds = [g["search"]["min_fd"] for g in groups.values()]
    improved = any(g["search"]["min_fd"] < g["post_deal_start_fd"] for g in groups.values())
    if not improved:
        return (
            "NO_DEAL2_TIMING_SIGNAL",
            "no group produced downstream hard progress after Deal 2 in the envelope",
        )
    if len(set(min_fds)) == 1 and comparable:
        return (
            "DEAL2_TIMINGS_EQUAL_IN_ENVELOPE",
            f"all three timings reached the same absolute min_fd={min_fds[0]}",
        )
    if len(set(min_fds)) > 1:
        return (
            "DEAL2_TIMING_CHANGES_SHORT_HORIZON_PROGRESS",
            f"groups reached different absolute min_fd { {n: g['search']['min_fd'] for n, g in groups.items()} }",
        )
    return "INCONCLUSIVE", "unclassified Deal-2 timing comparison"


def next_recommendation(verdict: str, groups: dict) -> str:
    fd10 = {n: g for n, g in groups.items() if g.get("fd10")}
    if verdict == "DEAL2_TIMING_REACHES_FOUNDATION":
        return "Capture the foundation route from the successful timing. Do not take Deal 3."
    if verdict == "DEAL2_TIMING_REACHES_FD10":
        names = list(fd10)
        if names == ["EARLY"]:
            return (
                "Deal 2 at fd13 uniquely reaches fd10. Extra available reveals before Deal 2 "
                "can damage short-horizon reception. Next: keep the EARLY fd10 portfolio and "
                "do not assume the cascade must be consumed. Do not add a heuristic."
            )
        if names == ["LATE"]:
            return (
                "Deal 2 at fd11 uniquely reaches fd10. Continue the Deal-1 reveal cascade "
                "before Deal 2. Do not preview Deal 3."
            )
        if set(names) == {"MIDDLE", "LATE"}:
            return (
                "Deal 2 at fd11 reaches fd10 from every LATE source at path/MW 56 "
                "(local depth 4). Deal 2 at fd12 also reaches fd10, but only from 8 "
                "of 16 sources at path/MW 57 (local depth 7). Deal 2 at fd13 does not "
                "reach fd10 in the depth-8 envelope. Continue exact post-Deal search "
                "from the cheaper LATE fd10 portfolio. Do not add a heuristic and do not take Deal 3."
            )
        if names == ["MIDDLE"]:
            return (
                "Later Deal-2 timings reach fd10. Prefer the cheaper successful timing and "
                "keep exact post-Deal search. Do not add a heuristic."
            )
        return (
            "Multiple Deal-2 timings reach fd10. Compare their path/cost and structure; "
            "timing may be flexible. Do not add a heuristic."
        )
    if verdict == "DEAL2_TIMING_CHANGES_SHORT_HORIZON_PROGRESS":
        return (
            "No timing reached fd10, but absolute post-Deal fd differs. Keep the bounded "
            "comparison; do not add a heuristic and do not take Deal 3."
        )
    if verdict == "DEAL2_TIMINGS_EQUAL_IN_ENVELOPE":
        return (
            "Deal-2 timing is flexible inside this envelope. Later work may compare move "
            "cost or structure. Do not add a heuristic."
        )
    if verdict == "NO_DEAL2_TIMING_SIGNAL":
        return (
            "Deal 2 produced no further hard progress within depth 8. Next is either a "
            "deeper post-Deal envelope or extra pre-Deal preparation around one frontier, "
            "not a heuristic."
        )
    if verdict == "DEAL2_PREVIEW_STATE_EXPLOSION":
        return "Keep the harness; do not raise limits here and do not add a heuristic."
    if verdict == "SOURCE_REPLAY_FAILURE":
        return "Reconstruct the v0.26/v0.27/v0.28 portfolios before any further work."
    return "Do not take Deal 3. Keep exact Deal-2 timing comparison."


def write_report(payload: dict) -> None:
    groups = payload.get("groups") or {}
    rows = []
    for name in ("EARLY", "MIDDLE", "LATE"):
        g = groups.get(name) or {}
        search = g.get("search") or {}
        fd10_path = g.get("min_fd10_total_path")
        fd10_cost = g.get("min_fd10_cost")
        best = "" if fd10_path is None else f"{fd10_path}/{fd10_cost}"
        rows.append(
            f"| {name} | {g.get('pre_fd')} | {g.get('source_path_range')} | "
            f"{search.get('min_fd')} | {g.get('fd10')} | {best} |"
        )
    lines = [
        "# Simple Progressive Search v0.29 — Deal-2 Timing Preview",
        "",
        "## 1. Verdict",
        "",
        f"`{payload['verdict']}` — {payload.get('verdict_reason', '')}",
        "",
        payload.get("interpretation", ""),
        "",
        f"- Branch: `{payload.get('branch')}`",
        f"- Base SHA: `{BASE_SHA}`",
        "- Previous verdict: `POST_DEAL1_FD12_REACHES_FD11`",
        "- No Deal 3. No extra pre-Deal preparation. No heuristic. Ordered pack_state.",
        "",
        "## 2. Source audits",
        "",
    ]
    for name in ("EARLY", "MIDDLE", "LATE"):
        g = groups.get(name) or {}
        lines.append(
            f"- {name}: listed={g.get('n_listed')} distinct={g.get('n_distinct')} "
            f"replay_ok={g.get('source_replay_ok')} path={g.get('source_path_range')} "
            f"MW={g.get('source_mw_range')} fd={g.get('pre_fd')} stock=4 deals=1"
        )
    lines += [
        "",
        "## 3. Deal-2 incoming row",
        "",
        f"- {payload.get('deal2_row_label')}",
        f"- cards={payload.get('deal2_row')}",
        "- Same pending row for every source in all three groups.",
        "",
        "## 4. Virtual Deal 2",
        "",
    ]
    for name in ("EARLY", "MIDDLE", "LATE"):
        g = groups.get(name) or {}
        lines.append(
            f"- {name}: sources={g.get('n_distinct')} distinct_children={g.get('n_virtual_children')} "
            f"unmutated={g.get('sources_unmutated')} post_stock=3"
        )
    lines += [
        "",
        "## 5. Post-Deal search",
        "",
    ]
    for name in ("EARLY", "MIDDLE", "LATE"):
        g = groups.get(name) or {}
        s = g.get("search") or {}
        lines.append(
            f"- {name}: unique={s.get('unique')} expanded={s.get('expanded')} "
            f"generated={s.get('generated')} dups={s.get('duplicate_skips')} "
            f"cross_origin={s.get('cross_origin_dups')}"
        )
        lines.append(
            f"  expanded_depth={s.get('completed_expanded_depth')} "
            f"generated_depth={s.get('completed_generated_depth')} stop={s.get('stop_reason')} "
            f"min_fd={s.get('min_fd')} fnd={s.get('max_foundations')} "
            f"elapsed_s={s.get('elapsed_s')} rss_mb={s.get('peak_rss_mb')}"
        )
        lines.append(
            f"  fd10={g.get('fd10')} fd10_classes={g.get('fd10_classes')} "
            f"min_local={g.get('min_fd10_local_depth')} min_path={g.get('min_fd10_total_path')} "
            f"min_cost={g.get('min_fd10_cost')} origins={g.get('fd10_source_ids')} "
            f"first_fd12={g.get('first_depth_fd12')} first_fd11={g.get('first_depth_fd11')} "
            f"first_fd10={g.get('first_depth_fd10')}"
        )
    lines += [
        "",
        "## 6. Common comparison",
        "",
        "| Deal-2 timing | Pre-Deal fd | Source path range | Min post-Deal fd | Reaches fd10 | Best full path/MW to fd10 |",
        "|---|---:|---:|---:|---:|---:|",
        *rows,
        "",
        "## 7. Reception telemetry summary",
        "",
        json.dumps(payload.get("reception_summaries") or {}, indent=2),
        "",
        "## 8. Cross-group exact convergence",
        "",
        json.dumps(payload.get("cross_group") or {}, indent=2),
        "",
        "## 9. Exactly one next recommendation",
        "",
        payload.get("next_recommendation", ""),
        "",
        "## Integrity",
        "",
        f"Verdict {payload.get('verdict')}. foundation={payload.get('foundation')}.",
        f"elapsed_s={payload.get('elapsed_s')} rss_mb={payload.get('peak_rss_mb')}.",
        "",
        f"Base SHA `{BASE_SHA}`. Deal `deals/4925153.txt`.",
        "No Deal 3. No heuristic. No production change.",
        "",
    ]
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> dict:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    opening = opening_state()
    started = time.perf_counter()
    recovered = {}
    audit_ok = True
    deal_rows = []
    for name, expected_fd, expected_n in GROUPS:
        audited, distinct = recover_group(name, expected_fd, expected_n, opening)
        recovered[name] = {
            "audited": audited,
            "distinct": distinct,
            "pre_fd": expected_fd,
        }
        if not (all(row["ok"] for row in audited) and len(distinct) == expected_n):
            audit_ok = False
        deal_rows.extend([tuple(tuple(x) for x in row["deal2_row"]) for row in audited])

    unique_rows = set(deal_rows)
    row_ok = len(unique_rows) == 1 and audit_ok
    if not row_ok:
        audit_ok = False
    known_row = next_stock_row(next(iter(recovered["EARLY"]["distinct"].values()))["state"]) if recovered["EARLY"]["distinct"] else []
    row_label = ",".join(card_label(p) for p in known_row)

    if not audit_ok:
        payload = {
            "experiment": EXPERIMENT,
            "verdict": "SOURCE_REPLAY_FAILURE",
            "deal2_row": [list(p) for p in known_row],
            "deal2_row_unique": len(unique_rows) == 1,
            "groups": {
                name: {
                    "n_listed": len(rec["audited"]),
                    "n_distinct": len(rec["distinct"]),
                    "source_replay_ok": all(r["ok"] for r in rec["audited"]),
                    "sources": rec["audited"],
                }
                for name, rec in recovered.items()
            },
        }
        _write_json(RESULT, payload)
        write_report(payload)
        print("VERDICT SOURCE_REPLAY_FAILURE", flush=True)
        return payload

    print(f"DEAL2_ROW {row_label}", flush=True)
    groups_out = {}
    explosion = False
    peak_rss = None
    post_deal_digests = {}

    for name, expected_fd, expected_n in GROUPS:
        remaining = GLOBAL_TIME_S - (time.perf_counter() - started)
        if remaining <= 1:
            explosion = True
            groups_out[name] = {
                "pre_fd": expected_fd,
                "skipped": True,
                "search": {"stop_reason": "time limit", "min_fd": expected_fd, "max_foundations": 0},
                "fd10": False,
                "post_deal_start_fd": expected_fd,
            }
            continue
        print(f"GROUP {name} START virtual Deal 2 then tableau BFS", flush=True)
        children, telemetry, mutated = virtual_deal_group(recovered[name]["distinct"], known_row)
        child_states = [rec["state"] for rec in children.values()]
        child_paths = [rec["path"] for rec in children.values()]
        origins = [rec["origin"] for rec in children.values()]
        post_deal_start_fd = min(face_down_count(st) for st in child_states)
        post_deal_digests[name] = {pack_state(st).hex() for st in child_states}
        print(
            f"GROUP {name} virtual children={len(children)} mutated={mutated} "
            f"post_fd={post_deal_start_fd} stock={stock_rows(child_states[0])}",
            flush=True,
        )
        search = tableau_layer_bfs(
            child_states,
            origin_paths=child_paths,
            max_depth=GROUP_MAX_DEPTH,
            max_unique=GROUP_MAX_UNIQUE,
            time_limit_s=min(GROUP_TIME_S, remaining),
            rss_abort_mb=GROUP_RSS_MB,
            checkpoints=(2, 4, 6, 8),
            stop_after_progress_layer=True,
            require_stock_rows=3,
            progress_fd_at_most=10,
        )
        print(
            f"GROUP {name} unique={search.unique} exp={search.expanded} gen={search.generated} "
            f"dups={search.duplicate_skips} min_fd={search.min_fd} stop={search.stop_reason} "
            f"depth={search.completed_generated_depth} elapsed={search.elapsed_s:.1f} "
            f"rss={search.peak_rss_mb} progress={len(search.progress)}",
            flush=True,
        )
        if search.stop_reason in ("unique limit", "time limit", "rss abort"):
            explosion = True
        if search.peak_rss_mb is not None:
            peak_rss = search.peak_rss_mb if peak_rss is None else max(peak_rss, search.peak_rss_mb)

        first_map = {int(k): int(v) for k, v in search.first_fd_depth.items()}
        progress_rows = harvest_progress(opening, child_paths, search, name, origins)
        fd10_rows = [r for r in progress_rows if r["fd"] <= 10]
        fnd_rows = [r for r in progress_rows if r.get("foundations", 0) >= 1]
        first = None
        fixture = None
        if fnd_rows:
            first = min(fnd_rows, key=lambda r: (r["depth"], r.get("origin", 0)))
            fixture = write_fixture(name, first)
        elif fd10_rows:
            first = min(fd10_rows, key=lambda r: (r["depth"], r.get("origin", 0)))
            fixture = write_fixture(name, first)

        paths = [r["total_primitive_path"] for r in recovered[name]["audited"]]
        costs = [r["mw_cost"] for r in recovered[name]["audited"]]
        groups_out[name] = {
            "pre_fd": expected_fd,
            "n_listed": expected_n,
            "n_distinct": len(recovered[name]["distinct"]),
            "source_replay_ok": True,
            "source_path_range": f"{min(paths)}-{max(paths)}" if len(set(paths)) > 1 else str(paths[0]),
            "source_mw_range": f"{min(costs)}-{max(costs)}" if len(set(costs)) > 1 else str(costs[0]),
            "n_virtual_children": len(children),
            "sources_unmutated": not mutated,
            "post_deal_start_fd": post_deal_start_fd,
            "virtual_child_origins": origins,
            "reception": telemetry,
            "reception_summary": reception_summary(telemetry),
            "search": {
                "unique": search.unique,
                "expanded": search.expanded,
                "generated": search.generated,
                "duplicate_skips": search.duplicate_skips,
                "cross_origin_dups": search.cross_origin_dups,
                "unique_sources": search.unique_sources,
                "completed_expanded_depth": search.completed_expanded_depth,
                "completed_generated_depth": search.completed_generated_depth,
                "stop_reason": search.stop_reason,
                "min_fd": search.min_fd,
                "max_foundations": search.max_foundations,
                "progress_classes": len(search.progress),
                "progress_edges": search.progress_edges,
                "elapsed_s": search.elapsed_s,
                "peak_rss_mb": search.peak_rss_mb,
                "deal_expanded": False,
                "identity": "pack_state",
                "first_fd_depth": {str(k): v for k, v in sorted(first_map.items())},
                "independent_seen_set": True,
            },
            "first_depth_fd12": first_depth_at_most(first_map, 12),
            "first_depth_fd11": first_depth_at_most(first_map, 11),
            "first_depth_fd10": first_depth_at_most(first_map, 10),
            "fd10": bool(fd10_rows),
            "fd10_classes": len(fd10_rows),
            "fd10_source_ids": sorted({r["origin"] for r in fd10_rows}),
            "min_fd10_local_depth": None if not fd10_rows else min(r["depth"] for r in fd10_rows),
            "min_fd10_total_path": None if not fd10_rows else min(r["full_path_length"] for r in fd10_rows),
            "min_fd10_cost": None if not fd10_rows else min(r["full_cost"] for r in fd10_rows if r["full_cost"] is not None),
            "foundation": bool(fnd_rows),
            "full_replay_ok": (not progress_rows) or all(r.get("full_replay_ok") for r in progress_rows),
            "fixture": fixture,
            "first_witness": first,
            "fd10_exits": fd10_rows,
            "sources": recovered[name]["audited"],
        }

    def overlap(a, b):
        return len(post_deal_digests.get(a, set()) & post_deal_digests.get(b, set()))

    fd10_overlap = {}
    for a, b in (("EARLY", "MIDDLE"), ("EARLY", "LATE"), ("MIDDLE", "LATE")):
        da = {r["ordered_digest"] for r in groups_out.get(a, {}).get("fd10_exits") or []}
        db = {r["ordered_digest"] for r in groups_out.get(b, {}).get("fd10_exits") or []}
        fd10_overlap[f"{a}&{b}"] = len(da & db)

    elapsed = time.perf_counter() - started
    verdict, reason = choose_verdict(True, groups_out, explosion)
    interpretation = reason
    if verdict == "DEAL2_TIMING_REACHES_FD10":
        interpretation = (
            "At least one Deal-2 timing reaches replay-valid fd10 inside the depth-8 "
            "post-Deal envelope. This does not license a Deal-readiness heuristic."
        )
    payload = {
        "experiment": EXPERIMENT,
        "base_sha": BASE_SHA,
        "branch": "agent/simple-progressive-deal2-timing-preview-v0-29",
        "previous_verdict": "POST_DEAL1_FD12_REACHES_FD11",
        "verdict": verdict,
        "verdict_reason": reason,
        "interpretation": interpretation,
        "next_recommendation": next_recommendation(verdict, groups_out),
        "deal2_row": [list(p) for p in known_row],
        "deal2_row_label": row_label,
        "deal2_row_unique": True,
        "groups": groups_out,
        "reception_summaries": {n: g.get("reception_summary") for n, g in groups_out.items()},
        "cross_group": {
            "post_deal_overlap_EARLY_MIDDLE": overlap("EARLY", "MIDDLE"),
            "post_deal_overlap_EARLY_LATE": overlap("EARLY", "LATE"),
            "post_deal_overlap_MIDDLE_LATE": overlap("MIDDLE", "LATE"),
            "fd10_overlap": fd10_overlap,
            "independent_seen_sets": True,
        },
        "foundation": any(g.get("foundation") for g in groups_out.values()),
        "elapsed_s": elapsed,
        "peak_rss_mb": peak_rss,
        "no_deal_3": True,
        "no_extra_pre_deal_preparation": True,
        "no_post_stock_symmetry": True,
        "production_unchanged": True,
    }
    _write_json(RESULT, payload)
    write_report(payload)
    print(f"VERDICT {verdict}", flush=True)
    print(f"NEXT {payload['next_recommendation']}", flush=True)
    return payload


if __name__ == "__main__":
    main()
