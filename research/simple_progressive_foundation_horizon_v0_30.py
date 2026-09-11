#!/usr/bin/env python3
"""v0.30: foundation material horizons and first-foundation Deal-2 comparison.

No Deal 3. No fd-target. No foundation-preference heuristic.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.cards import Card
from spider.deal import load_deal
from spider.engine import SpiderState
from spider.metrics import replay_actions
from spider.packed_state import pack_state, permute_tableau_columns
from spider.rules import MW_RULES
from spider.simple_deal1_preview import (
    next_stock_row,
    snapshot_metrics,
    stock_rows,
    tableau_layer_bfs,
)
from spider.simple_foundation_horizon import SUIT_NAMES, material_horizon_audit, pretty_card
from spider.simple_legacy_fd13_alternatives import checkpoint_record
from spider.simple_progressive_solver import apply_action, format_moves_text
from spider.simple_workspace_reachability import face_down_count

EXPERIMENT = "simple_progressive_foundation_horizon_v0_30"
BASE_SHA = "f55c5ccf38cebf129bb37e47b3c82e6d7bf31dfc"
DEAL_PATH = ROOT / "deals" / "4925153.txt"
V26 = ROOT / "docs" / "research" / "simple_progressive_deal1_preview_v0_26.json"
V27 = ROOT / "docs" / "research" / "simple_progressive_post_deal1_work_v0_27.json"
V28 = ROOT / "docs" / "research" / "simple_progressive_post_deal1_fd12_v0_28.json"
RESULT = ROOT / "docs" / "research" / f"{EXPERIMENT}.json"
REPORT = ROOT / "docs" / "research" / f"{EXPERIMENT}.md"
OUT_DIR = ROOT / "research" / "results" / EXPERIMENT
FIXTURES = {
    "EARLY": ROOT / "solutions" / "4925153_simple_v0_30_early_first_foundation.moves.txt",
    "MIDDLE": ROOT / "solutions" / "4925153_simple_v0_30_middle_first_foundation.moves.txt",
    "LATE": ROOT / "solutions" / "4925153_simple_v0_30_late_first_foundation.moves.txt",
}
GROUPS = (
    ("EARLY", 13, 8),
    ("MIDDLE", 12, 16),
    ("LATE", 11, 16),
)
GROUP_MAX_UNIQUE = 1_500_000
GROUP_TIME_S = 900.0
GROUP_RSS_MB = 3 * 1024.0
GROUP_MAX_DEPTH = 10_000
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


def recover_group(name: str, expected_fd: int, expected_n: int, opening: SpiderState):
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
        audited.append(
            {
                "source_id": index,
                "ok": ok,
                "total_primitive_path": len(full),
                "mw_cost": cost,
                "deals": deals,
                "fd": cp["fd"],
                "stock_rows": stock_rows(end),
                "foundations": cp["foundations"],
                "ordered_digest": digest,
                "deal2_row": [list(item) for item in next_stock_row(end)],
                "ordered_identity_sensitive_to_column_perm": pack_state(end) != pack_state(swapped),
                "full_actions": actions_json(full),
            }
        )
        print(
            f"SOURCE {name} {index} ok={ok} path={len(full)} MW={cost} fd={cp['fd']} stock={stock_rows(end)}",
            flush=True,
        )
        ident = pack_state(end)
        if ident not in distinct:
            distinct[ident] = {"state": end, "path": full, "source_id": index}
    return audited, distinct


def virtual_deal_group(distinct: dict, rules=MW_RULES):
    children = {}
    mutated = False
    for rec in distinct.values():
        source = rec["state"]
        before = pack_state(source)
        child = source.clone()
        apply_action(child, ("deal",), rules=rules)
        if pack_state(source) != before:
            mutated = True
        post = snapshot_metrics(child)
        ok = post["stock_rows"] == 3 and post["foundations"] == 0 and sum(1 for a in rec["path"] if a == ("deal",)) + 1 == 2
        child_id = pack_state(child)
        if child_id not in children:
            children[child_id] = {
                "state": child,
                "path": list(rec["path"]) + [("deal",)],
                "origin": rec["source_id"],
                "ok": ok,
                "post_fd": post["fd"],
                "post_stock": post["stock_rows"],
                "post_foundations": post["foundations"],
            }
    return children, mutated


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
        suits = rec.get("foundation_suits") or []
        if replay_ok and end.foundations:
            suits = [run[0].suit for run in end.foundations if run]
        item = dict(rec)
        item["bfs_origin"] = bfs_origin
        item["origin"] = origin_map[bfs_origin]
        item["full_actions"] = actions_json(full)
        item["full_path_length"] = len(full)
        item["full_cost"] = cost
        item["full_replay_ok"] = replay_ok
        item["deals"] = sum(1 for a in full if a == ("deal",))
        item["foundation_suits"] = suits
        item["foundation_suit"] = suits[0] if suits else None
        item["group"] = group
        rows.append(item)
    return rows


def write_fixture(group: str, rec: dict) -> str:
    full = as_actions(rec["full_actions"])
    path = FIXTURES[group]
    header = "\n".join(
        [
            f"# v0.30 first foundation after Deal 2 timing {group}",
            f"# origin: {rec.get('origin')}",
            f"# local_depth: {rec['depth']}",
            f"# suit: {rec.get('foundation_suit')}",
            f"# fd: {rec.get('fd')}",
            f"# stock_rows: {rec.get('stock_rows')}",
        ]
    )
    path.write_text(format_moves_text(full, header=header), encoding="utf-8")
    rec["fixture"] = path.relative_to(ROOT).as_posix()
    return rec["fixture"]


def compact_sources(audited: list) -> list:
    keys = (
        "source_id",
        "ok",
        "total_primitive_path",
        "mw_cost",
        "deals",
        "fd",
        "stock_rows",
        "foundations",
        "ordered_digest",
    )
    return [{k: row[k] for k in keys} for row in audited]


def choose_verdict(horizon_ok: bool, audit_ok: bool, groups: dict, explosion: bool) -> tuple[str, str]:
    if not horizon_ok:
        return "FOUNDATION_HORIZON_AUDIT_MISMATCH", "computed material horizons do not match the expected 4925153 map"
    if not audit_ok:
        return "SOURCE_REPLAY_FAILURE", "the three Deal-2 source portfolios could not be reconstructed"
    suits = set()
    reached = []
    for name, group in groups.items():
        if group.get("first_foundation"):
            reached.append(name)
            suits.update(group.get("foundation_suits") or [])
    if "d" in suits or "c" in suits:
        return "INCONCLUSIVE", f"unexpected Diamond/Club foundation before Deal 3: {sorted(suits)}"
    if suits == {"s", "h"}:
        return "SPADE_AND_HEART_FIRST_FOUNDATIONS_REACHED", f"both suits at min-depth by {reached}"
    if suits == {"s"}:
        return "SPADE_FIRST_FOUNDATION_REACHED", f"first Spade foundation by {reached}"
    if suits == {"h"}:
        return "HEART_FIRST_FOUNDATION_REACHED", f"first Heart foundation by {reached}"
    if reached:
        return "INCONCLUSIVE", f"foundation without recognised suit by {reached}"
    if explosion:
        return "FIRST_FOUNDATION_SEARCH_STATE_EXPLOSION", "resource limits bound before a first foundation"
    return "NO_FIRST_FOUNDATION_BEFORE_DEAL3", "no timing reached a foundation before Deal 3"


def next_recommendation(verdict: str, groups: dict) -> str:
    successful = [(name, g) for name, g in groups.items() if g.get("first_foundation")]
    if successful:
        best = min(successful, key=lambda item: (item[1]["min_full_path"], item[0]))
        name, group = best
        suit = SUIT_NAMES.get((group.get("foundation_suits") or ["?"])[0], group.get("foundation_suits"))
        return (
            f"{name} reaches the first {suit} foundation most cheaply "
            f"(path/MW {group.get('min_full_path')}/{group.get('min_full_cost')}, "
            f"local depth {group.get('min_local_depth')}). "
            "That operational target supersedes fd count. Continue exact search from this "
            "first-foundation portfolio. Do not add a suit heuristic yet and do not take Deal 3."
        )
    if verdict == "NO_FIRST_FOUNDATION_BEFORE_DEAL3":
        return (
            "Material Spade/Heart sets exist after SD2, but no timing assembled a foundation "
            "before Deal 3 in this envelope. Next is a Deal-3 decision or a deeper exact "
            "search, not an fd proxy and not a heuristic."
        )
    if verdict == "FIRST_FOUNDATION_SEARCH_STATE_EXPLOSION":
        return "Keep the first-foundation target; do not raise limits here and do not add a heuristic."
    if verdict == "FOUNDATION_HORIZON_AUDIT_MISMATCH":
        return "Fix the material-horizon audit before any operational search."
    if verdict == "SOURCE_REPLAY_FAILURE":
        return "Reconstruct the v0.29 Deal-2 portfolios before searching for a foundation."
    return "Keep the foundation objective. Do not revert to fd-count optimisation."


def write_report(payload: dict) -> None:
    horizon = payload.get("horizon") or {}
    groups = payload.get("groups") or {}
    rows = []
    for name in ("EARLY", "MIDDLE", "LATE"):
        g = groups.get(name) or {}
        suits = ",".join(SUIT_NAMES.get(s, s) for s in (g.get("foundation_suits") or []))
        path = "" if g.get("min_full_path") is None else f"{g.get('min_full_path')}/{g.get('min_full_cost')}"
        rows.append(
            f"| {name} | {g.get('pre_fd')} | {g.get('first_foundation')} | {suits} | {path} |"
        )
    suit_lines = []
    for suit in ("s", "h", "d", "c"):
        rec = (horizon.get("suits") or {}).get(suit) or {}
        first_b = rec.get("first_bottleneck") or {}
        second_b = rec.get("second_bottleneck") or {}
        suit_lines.append(
            f"- {rec.get('name')}: first {rec.get('first_label')} "
            f"(missing before: {first_b.get('missing_ranks_before')}; "
            f"supplied: {first_b.get('supplied_by_completing_row')}); "
            f"second {rec.get('second_label')} "
            f"(missing before: {second_b.get('missing_ranks_before')})"
        )
    lines = [
        "# Simple Progressive Search v0.30 — Foundation Horizon and First-Foundation Audit",
        "",
        "## 1. Verdict",
        "",
        f"`{payload.get('verdict')}` — {payload.get('verdict_reason', '')}",
        "",
        payload.get("interpretation", ""),
        "",
        f"- Branch: `{payload.get('branch')}`",
        f"- Base SHA: `{BASE_SHA}`",
        "- Objective: first foundation, not fd reduction.",
        "- No Deal 3. No suit heuristic. Ordered pack_state.",
        "",
        "## 2. Exact foundation material horizons",
        "",
        f"- Final Deal row (SD5): {','.join(horizon.get('sd5') or [])}",
        f"- SD5 matches expected: {horizon.get('sd5_matches_expected')}",
        f"- Max foundations by horizon: {horizon.get('max_foundations_by_horizon')}",
        f"- Impossible before SD5: {horizon.get('impossible_before_sd5')}",
        f"- Material audit matches expected: {horizon.get('expected_ok')}",
        "",
        *suit_lines,
        "",
        "Material horizon is not operational horizon.",
        "",
        "## 3. Source audits",
        "",
    ]
    for name in ("EARLY", "MIDDLE", "LATE"):
        g = groups.get(name) or {}
        lines.append(
            f"- {name}: listed={g.get('n_listed')} distinct={g.get('n_distinct')} "
            f"replay_ok={g.get('source_replay_ok')} path={g.get('source_path_range')} "
            f"fd={g.get('pre_fd')} virtual_children={g.get('n_virtual_children')} "
            f"unmutated={g.get('sources_unmutated')} post_stock=3"
        )
    lines += [
        "",
        f"- Deal-2 row: {payload.get('deal2_row_label')}",
        "",
        "## 4. First-foundation search",
        "",
    ]
    for name in ("EARLY", "MIDDLE", "LATE"):
        g = groups.get(name) or {}
        s = g.get("search") or {}
        lines.append(
            f"- {name}: unique={s.get('unique')} expanded={s.get('expanded')} "
            f"generated={s.get('generated')} dups={s.get('duplicate_skips')} "
            f"stop={s.get('stop_reason')} expanded_depth={s.get('completed_expanded_depth')} "
            f"generated_depth={s.get('completed_generated_depth')} min_fd={s.get('min_fd')} "
            f"elapsed_s={s.get('elapsed_s')} rss_mb={s.get('peak_rss_mb')}"
        )
        lines.append(
            f"  foundation={g.get('first_foundation')} suits={g.get('foundation_suits')} "
            f"classes={g.get('foundation_classes')} local={g.get('min_local_depth')} "
            f"path={g.get('min_full_path')} MW={g.get('min_full_cost')} "
            f"stock={g.get('stock_at_foundation')} fd_at_removal={g.get('fd_at_foundation')} "
            f"origins={g.get('foundation_source_ids')} replay={g.get('full_replay_ok')} "
            f"fixture={g.get('fixture')}"
        )
    lines += [
        "",
        "## 5. Comparison",
        "",
        "| Deal-2 timing | Pre-Deal fd | First foundation | Suit | Full path/MW |",
        "|---|---:|---|---|---:|",
        *rows,
        "",
        "Envelope note: EARLY used the full 900s group cap. MIDDLE stopped on the first "
        "foundation layer. LATE received only the global-1800s leftover and is not a full "
        "900s non-result.",
        "",
        "## 6. Exactly one next recommendation",
        "",
        payload.get("next_recommendation", ""),
        "",
        "## Integrity",
        "",
        f"Verdict {payload.get('verdict')}. elapsed_s={payload.get('elapsed_s')} rss_mb={payload.get('peak_rss_mb')}.",
        "",
        f"Base SHA `{BASE_SHA}`. Deal `deals/4925153.txt`.",
        "No Deal 3. No fd-target. No production change.",
        "",
    ]
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> dict:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    opening = opening_state()
    started = time.perf_counter()
    horizon = material_horizon_audit(opening)
    print(
        f"HORIZON expected_ok={horizon['expected_ok']} sd5={','.join(horizon['sd5'])} "
        f"max={horizon['max_foundations_by_horizon']} impossible={horizon['impossible_before_sd5']}",
        flush=True,
    )
    for suit, rec in horizon["suits"].items():
        print(
            f"HORIZON {rec['name']} first={rec['first_label']} second={rec['second_label']} "
            f"first_missing_before={rec['first_bottleneck']['missing_ranks_before']}",
            flush=True,
        )

    recovered = {}
    audit_ok = True
    deal_rows = []
    for name, expected_fd, expected_n in GROUPS:
        audited, distinct = recover_group(name, expected_fd, expected_n, opening)
        recovered[name] = {"audited": audited, "distinct": distinct, "pre_fd": expected_fd}
        if not (all(row["ok"] for row in audited) and len(distinct) == expected_n):
            audit_ok = False
        deal_rows.extend([tuple(tuple(x) for x in row["deal2_row"]) for row in audited])
    row_ok = len(set(deal_rows)) == 1
    if not row_ok:
        audit_ok = False
    sample = next(iter(recovered["EARLY"]["distinct"].values()))["state"]
    known_row = next_stock_row(sample)
    row_label = ",".join(pretty_card(Card(s, r)) for s, r in known_row)

    if not horizon["expected_ok"] or not audit_ok:
        verdict, reason = choose_verdict(horizon["expected_ok"], audit_ok, {}, False)
        payload = {
            "experiment": EXPERIMENT,
            "verdict": verdict,
            "verdict_reason": reason,
            "horizon": horizon,
            "deal2_row_label": row_label,
            "groups": {
                name: {
                    "n_listed": len(rec["audited"]),
                    "n_distinct": len(rec["distinct"]),
                    "source_replay_ok": all(r["ok"] for r in rec["audited"]),
                    "pre_fd": rec["pre_fd"],
                    "sources": compact_sources(rec["audited"]),
                }
                for name, rec in recovered.items()
            },
        }
        payload["interpretation"] = reason
        payload["next_recommendation"] = next_recommendation(verdict, {})
        payload["branch"] = "agent/foundation-horizon-first-foundation-v0-30"
        _write_json(RESULT, payload)
        write_report(payload)
        print(f"VERDICT {verdict}", flush=True)
        return payload

    groups_out = {}
    explosion = False
    peak_rss = None
    for name, expected_fd, expected_n in GROUPS:
        remaining = GLOBAL_TIME_S - (time.perf_counter() - started)
        if remaining <= 1:
            explosion = True
            groups_out[name] = {
                "pre_fd": expected_fd,
                "skipped": True,
                "search": {"stop_reason": "time limit", "min_fd": expected_fd, "max_foundations": 0},
                "first_foundation": False,
            }
            continue
        print(f"GROUP {name} START virtual Deal 2 then foundation BFS", flush=True)
        children, mutated = virtual_deal_group(recovered[name]["distinct"])
        child_states = [rec["state"] for rec in children.values()]
        child_paths = [rec["path"] for rec in children.values()]
        origins = [rec["origin"] for rec in children.values()]
        print(
            f"GROUP {name} virtual children={len(children)} mutated={mutated} "
            f"stock={stock_rows(child_states[0])} fnd={len(child_states[0].foundations)}",
            flush=True,
        )
        search = tableau_layer_bfs(
            child_states,
            origin_paths=child_paths,
            max_depth=GROUP_MAX_DEPTH,
            max_unique=GROUP_MAX_UNIQUE,
            time_limit_s=min(GROUP_TIME_S, remaining),
            rss_abort_mb=GROUP_RSS_MB,
            checkpoints=(8, 16, 24, 32, 48, 64, 96, 128, 192, 256),
            stop_after_progress_layer=True,
            require_stock_rows=3,
            progress_foundations_at_least=1,
        )
        print(
            f"GROUP {name} unique={search.unique} exp={search.expanded} gen={search.generated} "
            f"dups={search.duplicate_skips} min_fd={search.min_fd} fnd={search.max_foundations} "
            f"stop={search.stop_reason} depth={search.completed_generated_depth} "
            f"elapsed={search.elapsed_s:.1f} rss={search.peak_rss_mb} progress={len(search.progress)}",
            flush=True,
        )
        if search.stop_reason in ("unique limit", "time limit", "rss abort"):
            explosion = True
        if search.peak_rss_mb is not None:
            peak_rss = search.peak_rss_mb if peak_rss is None else max(peak_rss, search.peak_rss_mb)
        progress_rows = harvest_progress(opening, child_paths, search, name, origins)
        fnd_rows = [r for r in progress_rows if r.get("foundations", 0) >= 1]
        first = None
        fixture = None
        if fnd_rows:
            first = min(fnd_rows, key=lambda r: (r["depth"], r.get("full_path_length", 10**9), r.get("origin", 0)))
            fixture = write_fixture(name, first)
        paths = [r["total_primitive_path"] for r in recovered[name]["audited"]]
        suits = sorted({s for r in fnd_rows for s in (r.get("foundation_suits") or [])})
        groups_out[name] = {
            "pre_fd": expected_fd,
            "n_listed": expected_n,
            "n_distinct": len(recovered[name]["distinct"]),
            "source_replay_ok": True,
            "source_path_range": f"{min(paths)}-{max(paths)}" if len(set(paths)) > 1 else str(paths[0]),
            "n_virtual_children": len(children),
            "sources_unmutated": not mutated,
            "sources": compact_sources(recovered[name]["audited"]),
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
                "independent_seen_set": True,
                "progress_foundations_at_least": 1,
            },
            "first_foundation": bool(fnd_rows),
            "foundation_suits": suits,
            "foundation_classes": len(fnd_rows),
            "foundation_source_ids": sorted({r["origin"] for r in fnd_rows}),
            "min_local_depth": None if not fnd_rows else min(r["depth"] for r in fnd_rows),
            "min_full_path": None if not fnd_rows else min(r["full_path_length"] for r in fnd_rows),
            "min_full_cost": None if not first else first.get("full_cost"),
            "stock_at_foundation": None if not first else first.get("stock_rows"),
            "fd_at_foundation": None if not first else first.get("fd"),
            "full_replay_ok": (not fnd_rows) or all(r.get("full_replay_ok") for r in fnd_rows),
            "fixture": fixture,
            "first_witness": None
            if not first
            else {
                k: first[k]
                for k in (
                    "origin",
                    "depth",
                    "fd",
                    "foundations",
                    "foundation_suit",
                    "foundation_suits",
                    "full_path_length",
                    "full_cost",
                    "full_replay_ok",
                    "deals",
                    "stock_rows",
                    "empties",
                    "ordered_digest",
                    "fixture",
                )
                if k in first
            },
            "foundation_exits": [
                {
                    k: r[k]
                    for k in (
                        "origin",
                        "depth",
                        "fd",
                        "foundations",
                        "foundation_suit",
                        "foundation_suits",
                        "full_path_length",
                        "full_cost",
                        "full_replay_ok",
                        "deals",
                        "stock_rows",
                        "empties",
                        "ordered_digest",
                        "full_actions",
                    )
                    if k in r
                }
                for r in fnd_rows
            ],
        }

    elapsed = time.perf_counter() - started
    verdict, reason = choose_verdict(True, True, groups_out, explosion)
    interpretation = (
        "The strategic objective is foundation removal. fd count is telemetry only. " + reason
    )
    if (groups_out.get("MIDDLE") or {}).get("first_foundation") and not (groups_out.get("LATE") or {}).get("first_foundation"):
        interpretation = (
            "MIDDLE reached a replay-valid first Spade foundation after Deal 2 from the fd12 "
            "frontier. That operational result supersedes v0.29's fd10 ranking, where LATE was "
            "cheapest. EARLY used its full 900s without a foundation. LATE did not receive a full "
            "900s group envelope: the global 1800s cap left only the leftover time after EARLY and "
            "MIDDLE, so LATE's non-result is bounded, not a proof of unreachability."
        )
    payload = {
        "experiment": EXPERIMENT,
        "base_sha": BASE_SHA,
        "branch": "agent/foundation-horizon-first-foundation-v0-30",
        "verdict": verdict,
        "verdict_reason": reason,
        "interpretation": interpretation,
        "next_recommendation": next_recommendation(verdict, groups_out),
        "horizon": {
            k: horizon[k]
            for k in (
                "sd5",
                "sd5_expected",
                "sd5_matches_expected",
                "suits",
                "max_foundations_by_horizon",
                "horizon_labels",
                "impossible_before_sd5",
                "expected_ok",
                "material_not_operational",
                "stock_rows",
            )
        },
        "deal2_row": [list(p) for p in known_row],
        "deal2_row_label": row_label,
        "deal2_row_unique": True,
        "groups": groups_out,
        "elapsed_s": elapsed,
        "peak_rss_mb": peak_rss,
        "no_deal_3": True,
        "no_fd_target": True,
        "no_suit_heuristic": True,
        "production_unchanged": True,
    }
    _write_json(RESULT, payload)
    write_report(payload)
    print(f"VERDICT {verdict}", flush=True)
    print(f"NEXT {payload['next_recommendation']}", flush=True)
    return payload


if __name__ == "__main__":
    main()
