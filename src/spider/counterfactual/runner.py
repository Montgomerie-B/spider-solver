"""Profile runner for controlled counterfactual continuations.

One search runs at a time. The deep profile is used only when the caller
asks for it. Visited states are discarded after each search. This module
does not write an incumbent, a campaign, or a canonical solution file.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import time
from pathlib import Path
from typing import Callable, Optional, Sequence

from spider.consequence_search import run_stockempty_consequence
from spider.engine import SpiderState
from spider.metrics import export_actions_to_moves_file, format_action, parse_moves_file
from spider.packed_state import unpack_state
from spider.research_actions import all_legal_actions

from .boundaries import (
    SearchWatch,
    checkpoint_from_actions,
    original_next_boundary,
    parse_canonical,
    structurally_promising,
)
from .budget import resolve_profile
from .classify import SPEC_CATEGORIES
from .experiment import (
    BASELINE_ACTIONS,
    BASELINE_MW,
    REFERENCE_ACTIONS,
    REFERENCE_MW,
    SCHEMA_VERSION,
    CounterfactualError,
    _one_pass,
    _public_root,
    _verify_solution,
    interpret,
    one_ply,
    rank_tableau_moves,
    reconstruct_roots,
    reference_horizon,
    validate_route,
)
from .policies import POLICIES, policy_actions
from .suffixes import index_route, validate_splice


ROOT_KEYS = {
    "pre-action-25": "A",
    "post-sd3": "B",
}
_MIN_SLICE_S = 2.0


def survivor_sort_key(search: dict) -> tuple:
    """Order unfinished branches for a deeper pass.

    Exact 185 suffix hits come first. The 172 hit is ignored. Experimental
    debt is ignored. Column-4 disorder is only the last tie-break.
    """

    watch = search.get("watch") or {}
    probe = search.get("probe") or {}
    hit = 0 if watch.get("baseline_suffix_hit") else 1
    foundations = int(probe.get("max_foundations") or 0)
    g_at = probe.get("g_at_max_foundations")
    g_at = 10**9 if g_at is None else int(g_at)
    bonds = int(watch.get("max_bonds_seen") or 0)
    face_down = 10**9
    disorder = 10**9
    for item in watch.get("stock_boundaries") or []:
        if item.get("immediate_deal"):
            continue
        face_down = min(face_down, int(item.get("face_down", face_down)))
        disorder = min(disorder, int(item.get("focus_disorder", disorder)))
    return (hit, -foundations, g_at, -bonds, face_down, disorder)


def run_profile(
    deal_path: Path,
    baseline_path: Path,
    reference_path: Path,
    *,
    roots: Sequence[str],
    policy: str = "all",
    profile_name: str = "pilot",
    overrides: Optional[dict] = None,
    focus_column: int = 4,
    artifact_dir: Optional[Path] = None,
    progress: Optional[Callable[[str], None]] = None,
) -> dict:
    """Run one named profile. ``roots`` are ``pre-action-25`` and/or ``post-sd3``."""

    if profile_name not in ("pilot", "screen", "deep"):
        raise CounterfactualError(f"unknown profile: {profile_name}")
    profile = resolve_profile(profile_name, overrides)
    deal_path = Path(deal_path)
    baseline_path = Path(baseline_path)
    reference_path = Path(reference_path)
    started = time.perf_counter()
    baseline = validate_route(
        deal_path, baseline_path, expected_mw=BASELINE_MW, expected_actions=BASELINE_ACTIONS
    )
    reference = validate_route(
        deal_path, reference_path, expected_mw=REFERENCE_MW, expected_actions=REFERENCE_ACTIONS
    )
    actions = parse_moves_file(baseline_path)
    reference_actions = parse_moves_file(reference_path)
    built = reconstruct_roots(deal_path, actions, focus_column=focus_column)
    focus_index = focus_column - 1
    human_post_sd3 = reference_horizon(deal_path, reference_actions, 3, focus_index=focus_index)
    _log(progress, "indexing the verified 185 for exact suffix reuse")
    baseline_index = index_route(deal_path, actions)
    reference_index = index_route(deal_path, reference_actions)
    ceiling = BASELINE_MW - 1
    names = [_require_root(name) for name in roots]
    if not names:
        raise CounterfactualError("no experimental root selected")
    experiments = []
    for name in names:
        experiments.append(
            _run_root(
                built[name],
                policy_name=policy,
                profile=profile,
                deal_path=deal_path,
                ceiling=ceiling,
                focus_index=focus_index,
                baseline_index=baseline_index,
                reference_index=reference_index,
                human_post_sd3=human_post_sd3,
                artifact_dir=None if artifact_dir is None else Path(artifact_dir),
                progress=progress,
            )
        )
    document = _document(
        deal_path=deal_path,
        baseline=baseline,
        reference=reference,
        profile=profile,
        experiments=experiments,
        ceiling=ceiling,
        started=started,
        repo=_repo_root(),
    )
    document["interpretation"] = interpret(document["experiments"])
    return document


def _run_root(
    root: dict,
    *,
    policy_name: str,
    profile: dict,
    deal_path: Path,
    ceiling: int,
    focus_index: int,
    baseline_index: dict,
    reference_index: dict,
    human_post_sd3: dict,
    artifact_dir: Optional[Path],
    progress: Optional[Callable[[str], None]],
) -> dict:
    policies = _select_policies(root["name"], policy_name)
    state = unpack_state(bytes.fromhex(root["ordered_digest"]))
    root_g = int(root["cumulative_g"])
    prefix = list(root["prefix_actions_internal"])
    suffix = list(root["suffix_actions_internal"])
    forbidden = suffix[0] if root["name"] == "A" else None
    root_stock_len = len(state.stock)
    store = bytes.fromhex(root["ordered_digest"])
    _log(progress, f"experiment {root['name']} measuring the original suffix to the next deal")
    original = original_next_boundary(state, suffix, root_g=root_g, focus_index=focus_index)
    deadline = time.perf_counter() + float(profile["total_time_s"])
    ply = {}
    for item in policies:
        ply[item["name"]] = one_ply(root, focus_index=focus_index, kind=item["kind"], limit=8)

    ranked = {}
    screened_rows = {}
    width = int(profile["candidate_width"])
    for item in policies:
        mode = "soft" if item["kind"] == "soft" else "construction"
        table = rank_tableau_moves(root, focus_index=focus_index, kind=item["kind"], rank_mode=mode)
        ranked[item["name"]] = table
        screened_rows[item["name"]] = list(table["rows"][:width])

    root_stage = float(profile["root_fraction"]) * float(profile["total_time_s"])
    per_root = min(float(profile["root_time_s"]), root_stage / max(1, len(policies)))
    searches = []
    for item in policies:
        _log(progress, f"experiment {root['name']} {item['name']} root worker")
        searches.append(
            _run_bounded(
                policy=item,
                role="root_worker",
                search_g=root_g,
                search_digest=root["ordered_digest"],
                forced=[],
                opening_prefix=prefix,
                artifact_dir=artifact_dir,
                root_state=state,
                root_g=root_g,
                root_name=root["name"],
                focus_index=focus_index,
                policy_root_store=store,
                root_stock_len=root_stock_len,
                forbidden=forbidden,
                deal_path=deal_path,
                ceiling=ceiling,
                time_limit_s=per_root,
                max_unique=int(profile["root_unique"]),
                profile=profile,
                deadline=deadline,
                baseline_index=baseline_index,
                reference_index=reference_index,
                progress=progress,
            )
        )

    n_screen = sum(len(rows) for rows in screened_rows.values())
    screen_stage = float(profile["screen_fraction"]) * float(profile["total_time_s"])
    per_screen = min(float(profile["screen_time_s"]), screen_stage / max(1, n_screen))
    screens = []
    flat_candidates = []
    for item in policies:
        results = []
        table = ranked[item["name"]]
        for offset, row in enumerate(screened_rows[item["name"]], start=1):
            _log(progress, f"experiment {root['name']} {item['name']} screen {offset} {row['canonical']}")
            search = _run_bounded(
                policy=item,
                role="screen",
                search_g=int(row["child_g"]),
                search_digest=row["ordered_digest"],
                forced=[row["action"]],
                opening_prefix=prefix + [row["action"]],
                artifact_dir=artifact_dir,
                root_state=state,
                root_g=root_g,
                root_name=root["name"],
                focus_index=focus_index,
                policy_root_store=store,
                root_stock_len=root_stock_len,
                forbidden=forbidden,
                deal_path=deal_path,
                ceiling=ceiling,
                time_limit_s=per_screen,
                max_unique=int(profile["screen_unique"]),
                profile=profile,
                deadline=deadline,
                baseline_index=baseline_index,
                reference_index=reference_index,
                progress=progress,
            )
            published = _public_row(row, offset)
            published["search"] = search
            published["survivor_key"] = list(survivor_sort_key(search))
            results.append(published)
            flat_candidates.append((item, published))
        screens.append(
            {
                "policy": item["name"],
                "rank_mode": "soft" if item["kind"] == "soft" else "construction",
                "enumerated_tableau": table["enumerated_tableau"],
                "unique_children": table["unique_children"],
                "screened": len(results),
                "not_screened": max(0, table["unique_children"] - len(results)),
                "retained": len(results),
                "deal_legal_under_policy": table["deal_legal"],
                "planned_time_s": per_screen,
                "planned_unique": int(profile["screen_unique"]),
                "batches": [{"pass": 1, "results": results}],
                "note": (
                    "Short screen of policy-legal tableau children. Deal stays with the root worker. "
                    "Screen rank is not a verdict, and a cleaner child is not a cheaper solution."
                ),
            }
        )

    deep_pool = []
    per_policy_count = {}
    ordered = sorted(flat_candidates, key=lambda pair: tuple(pair[1]["survivor_key"]))
    for item, published in ordered:
        if int(per_policy_count.get(item["name"], 0)) >= int(profile["deep_survivors"]):
            continue
        search = published["search"]
        if search.get("status") == "SOLVED_VALID" and search.get("improves_on_baseline"):
            continue
        per_policy_count[item["name"]] = int(per_policy_count.get(item["name"], 0)) + 1
        deep_pool.append((item, published))

    deep_rows = []
    if deep_pool and float(profile["deep_time_s"]) > 0 and int(profile["deep_survivors"]) > 0:
        left = deadline - time.perf_counter()
        per_deep = min(float(profile["deep_time_s"]), max(0.0, left) / max(1, len(deep_pool)))
        for item, published in deep_pool:
            action = parse_canonical(published["canonical"])
            child = next(
                row for row in screened_rows[item["name"]] if row["canonical"] == published["canonical"]
            )
            _log(progress, f"experiment {root['name']} {item['name']} deep {published['canonical']}")
            search = _run_bounded(
                policy=item,
                role="deep",
                search_g=int(child["child_g"]),
                search_digest=child["ordered_digest"],
                forced=[action],
                opening_prefix=prefix + [action],
                artifact_dir=artifact_dir,
                root_state=state,
                root_g=root_g,
                root_name=root["name"],
                focus_index=focus_index,
                policy_root_store=store,
                root_stock_len=root_stock_len,
                forbidden=forbidden,
                deal_path=deal_path,
                ceiling=ceiling,
                time_limit_s=per_deep,
                max_unique=int(profile["deep_unique"]),
                profile=profile,
                deadline=deadline,
                baseline_index=baseline_index,
                reference_index=reference_index,
                progress=progress,
            )
            deep_rows.append(
                {
                    "policy": item["name"],
                    "screen_rank": published["screen_rank"],
                    "canonical": published["canonical"],
                    "cost": published["cost"],
                    "suit_boundary_delta": published["suit_boundary_delta"],
                    "bonds_delta": published["bonds_delta"],
                    "face_down_delta": published["face_down_delta"],
                    "survivor_key": list(published["survivor_key"]),
                    "search": search,
                }
            )

    _accept_reference_afterward(
        searches,
        screens,
        deep_rows,
        deal_path=deal_path,
        prefix=prefix,
        ceiling=ceiling,
        artifact_dir=artifact_dir,
        root_name=root["name"],
    )
    handoff = _stock_empty_handoff(
        searches + [row["search"] for screen in screens for batch in screen["batches"] for row in batch["results"]]
        + [row["search"] for row in deep_rows],
        deadline=deadline,
        ceiling=ceiling,
        profile=profile,
        deal_path=deal_path,
        progress=progress,
        root_name=root["name"],
    )
    comparisons = _comparisons(original, searches, screens, deep_rows)
    _write_checkpoints(artifact_dir, root["name"], comparisons, searches, screens, deep_rows)
    horizon = None
    if root["name"] == "B":
        horizon = {
            "machine_g_before_deal": root.get("g_before_this_deal"),
            "machine_g_after_deal": root["cumulative_g"],
            "reference_g_before_deal": human_post_sd3["g_before_deal"],
            "reference_g_after_deal": human_post_sd3["cumulative_g"],
            "machine_ahead_by": int(human_post_sd3["cumulative_g"]) - int(root["cumulative_g"]),
            "reference_focus_disorder": human_post_sd3["focus_disorder"],
            "machine_focus_disorder": root["focus_disorder"],
            "note": (
                "Same stock horizon: immediately after each route's own third deal. "
                "The reference route is not an ancestor of this state and was not used to rank candidates."
            ),
        }
    elapsed = max(0.0, float(profile["total_time_s"]) - max(0.0, deadline - time.perf_counter()))
    return {
        "name": root["name"],
        "root_key": "pre-action-25" if root["name"] == "A" else "post-sd3",
        "priority": "higher" if root["name"] == "B" else "secondary",
        "root": _public_root(root),
        "one_ply": ply,
        "original_boundary": original,
        "searches": searches,
        "candidate_screens": screens,
        "deep_searches": deep_rows,
        "stock_empty_handoff": handoff,
        "comparisons": comparisons,
        "stock_horizon": horizon,
        "elapsed_s": round(elapsed, 3),
        "budget_s": float(profile["total_time_s"]),
    }


def _run_bounded(
    *,
    policy: dict,
    role: str,
    search_g: int,
    search_digest: str,
    forced: Sequence,
    opening_prefix: Sequence,
    artifact_dir: Optional[Path],
    root_state: SpiderState,
    root_g: int,
    root_name: str,
    focus_index: int,
    policy_root_store: bytes,
    root_stock_len: int,
    forbidden,
    deal_path: Path,
    ceiling: int,
    time_limit_s: float,
    max_unique: int,
    profile: dict,
    deadline: float,
    baseline_index: dict,
    reference_index: dict,
    progress: Optional[Callable[[str], None]],
) -> dict:
    planned = {
        "time_limit_s": float(time_limit_s),
        "max_unique": int(max_unique),
        "max_depth": profile.get("max_depth"),
        "rss_abort_mb": float(profile["rss_abort_mb"]),
        "search_width_used": 1,
    }
    slot = _take(deadline, time_limit_s)
    if slot is None:
        return _synthetic(policy, role, "TIME_LIMIT", "experiment budget", planned, "The experiment deadline had less than 2 seconds left.")
    start_state = unpack_state(bytes.fromhex(search_digest))
    legal = all_legal_actions(start_state)
    allowed = policy_actions(
        policy["kind"],
        start_state,
        focus_index=focus_index,
        root_stock_len=root_stock_len,
        root_store=policy_root_store,
        forbidden=forbidden,
    )
    if legal and not allowed:
        return _synthetic(
            policy,
            role,
            "POLICY_BLOCKED",
            "policy blocked",
            planned,
            "The policy removed every engine-legal action. The legal list itself was not changed.",
        )
    watch = SearchWatch(
        root_stock_len=root_stock_len,
        origin_g=int(search_g),
        focus_index=focus_index,
        baseline_index=baseline_index,
        reference_index=reference_index,
    )
    try:
        result = _one_pass(
            search_g=int(search_g),
            search_digest=search_digest,
            policy=policy,
            ceiling=ceiling,
            time_limit_s=float(slot),
            max_unique=int(max_unique),
            focus_index=focus_index,
            policy_root_store=policy_root_store,
            root_stock_len=root_stock_len,
            forbidden=forbidden,
            origin_g=root_g,
            deal_path=deal_path,
            opening_prefix=list(opening_prefix),
            forced_actions=list(forced),
            experiment_name=root_name,
            max_depth=profile.get("max_depth"),
            rss_abort_mb=float(profile["rss_abort_mb"]),
            watch=watch,
        )
    except Exception as exc:
        failed = _synthetic(policy, role, "ERROR", "error", planned, str(exc))
        failed["error"] = f"{type(exc).__name__}: {exc}"
        return failed
    result["role"] = role
    result["planned"] = planned
    result["search_digest"] = search_digest
    result["search_g"] = int(search_g)
    result["opening_canonical"] = [format_action(action) for action in opening_prefix]
    result["watch"] = _align_watch(result.get("watch"), root_state, root_g, forced, focus_index)
    if result.get("status") not in SPEC_CATEGORIES:
        result["status"] = "ERROR"
    _accept_suffix(
        result,
        source="baseline-185",
        deal_path=deal_path,
        prefix=list(opening_prefix)[: len(list(opening_prefix)) - len(list(forced))],
        forced=forced,
        ceiling=ceiling,
        artifact_dir=artifact_dir,
        root_name=root_name,
        afterward=False,
    )
    if result.get("suffix_reuse") and result["suffix_reuse"].get("accepted"):
        _log(progress, f"{policy['name']} {role} accepted an exact 185 suffix at g {result.get('terminal_g')}")
    return result


def _accept_suffix(
    search: dict,
    *,
    source: str,
    deal_path: Path,
    prefix: Sequence,
    forced: Sequence,
    ceiling: int,
    artifact_dir: Optional[Path],
    root_name: str,
    afterward: bool,
) -> None:
    watch = search.get("watch") or {}
    key = "baseline_suffix_hit" if source == "baseline-185" else "reference_suffix_hit"
    hit = watch.get(key)
    if not hit:
        return
    if search.get("improves_on_baseline"):
        search.setdefault("suffix_attempts", []).append(
            {
                "source": source,
                "afterward": afterward,
                "ok": None,
                "skipped": "a verified improvement is already recorded",
                "used_to_choose_candidates": False,
            }
        )
        return
    try:
        path = [parse_canonical(text) for text in hit.get("path") or []]
        suffix = [parse_canonical(text) for text in hit.get("suffix") or []]
        opening = list(prefix) + list(forced) + path
        checked = validate_splice(
            deal_path,
            opening,
            suffix,
            bytes.fromhex(hit["store_hex"]),
            int(hit["g"]),
        )
    except Exception as exc:
        checked = {"ok": False, "error": f"splice failed: {exc}"}
    record = {
        "source": source,
        "afterward": afterward,
        "used_to_choose_candidates": False,
        "catalog_g": hit.get("catalog_g"),
        "reached_g": hit.get("g"),
        "saving_vs_catalog_g": hit.get("saving_vs_catalog_g"),
        "validation": {k: v for k, v in checked.items() if k != "error" or True},
    }
    search.setdefault("suffix_attempts", []).append(
        {
            "source": source,
            "afterward": afterward,
            "ok": bool(checked.get("ok")),
            "total_mw": checked.get("total_mw"),
            "improves_on_baseline": bool(checked.get("improves_on_baseline")),
            "error": checked.get("error"),
            "used_to_choose_candidates": False,
        }
    )
    if not checked.get("ok"):
        search["suffix_reuse"] = record
        return
    replay = {
        "ok": True,
        "total_mw": int(checked["total_mw"]),
        "packed_total_mw": int(checked.get("packed_total_mw") or checked["total_mw"]),
        "foundations": int(checked.get("foundations") or 0),
        "stock_remaining": int(checked.get("stock_remaining") or 0),
        "explicit_actions": int(checked.get("explicit_actions") or 0),
        "source": source,
        "afterward": afterward,
        "error": None,
    }
    improves = bool(checked.get("improves_on_baseline")) and int(checked["total_mw"]) <= int(ceiling)
    record["accepted"] = True
    search["suffix_reuse"] = record
    search["status"] = "SOLVED_VALID"
    search["replay"] = replay
    search["terminal_g"] = int(checked["total_mw"])
    search["improves_on_baseline"] = improves
    search["improvement_vs_baseline"] = BASELINE_MW - int(checked["total_mw"])
    search["accepted_by"] = source if not afterward else f"{source}-afterward"
    full = list(forced) + path + suffix
    search["continuation"] = [format_action(action) for action in full]
    search["verified_total_mw"] = int(checked["total_mw"])
    if improves and artifact_dir is not None:
        written = _write_solution(artifact_dir, root_name, search, opening + suffix)
        search["moves_path"] = written
        replay["moves_path"] = written


def _accept_reference_afterward(searches, screens, deep_rows, *, deal_path, prefix, ceiling, artifact_dir, root_name) -> None:
    """Validate 172 hits only after survivor ranking and deep searches have been chosen."""

    bag = list(searches)
    for screen in screens:
        for batch in screen["batches"]:
            for row in batch["results"]:
                bag.append(row["search"])
    for row in deep_rows:
        bag.append(row["search"])
    for search in bag:
        watch = search.get("watch") or {}
        if not watch.get("reference_suffix_hit"):
            continue
        # The opening prefix stored on the search continuation is not reliable.
        # Reference validation uses the hit path relative to the experiment prefix
        # only when the search started at the experiment root (no forced move).
        # Candidate hits include the forced move inside path_from_experiment_root
        # when alignment ran; the stored hit path is from the search start.
        forced = []
        path_from_root = (watch.get("reference_suffix_hit") or {}).get("path_from_experiment_root")
        if path_from_root:
            # Alignment stored the forced move plus the search path. The splice
            # opener is the experiment prefix plus that full path. Pass it as
            # prefix and leave forced empty by rewriting the hit path.
            hit = dict(watch["reference_suffix_hit"])
            hit["path"] = list(path_from_root)
            watch = dict(watch)
            watch["reference_suffix_hit"] = hit
            search_for_call = dict(search)
            search_for_call["watch"] = watch
            _accept_suffix(
                search_for_call,
                source="reference-172",
                deal_path=deal_path,
                prefix=prefix,
                forced=forced,
                ceiling=ceiling,
                artifact_dir=artifact_dir,
                root_name=root_name,
                afterward=True,
            )
            _copy_acceptance(search, search_for_call)
        else:
            _accept_suffix(
                search,
                source="reference-172",
                deal_path=deal_path,
                prefix=prefix,
                forced=[],
                ceiling=ceiling,
                artifact_dir=artifact_dir,
                root_name=root_name,
                afterward=True,
            )


def _copy_acceptance(target: dict, source: dict) -> None:
    for key in (
        "suffix_reuse",
        "suffix_attempts",
        "status",
        "replay",
        "terminal_g",
        "improves_on_baseline",
        "improvement_vs_baseline",
        "accepted_by",
        "continuation",
        "moves_path",
    ):
        if key in source:
            target[key] = source[key]


def _stock_empty_handoff(searches: Sequence[dict], *, deadline, ceiling, profile, deal_path, progress, root_name) -> Optional[dict]:
    """One consequence-search handoff from the cheapest unsolved empty-stock state."""

    if any(item.get("improves_on_baseline") for item in searches):
        return {"invoked": False, "reason": "A verified improvement was already in hand."}
    best = None
    owner = None
    for search in searches:
        empty = (search.get("watch") or {}).get("stock_empty_unsolved")
        if not empty:
            continue
        if best is None or int(empty["g"]) < int(best["g"]):
            best = empty
            owner = search
    if best is None:
        return {
            "invoked": False,
            "reason": (
                "No generated state had an empty stock. run_stockempty_consequence was not called. "
                "The root worker remains the ordinary bounded search."
            ),
        }
    slot = _take(deadline, float(profile["deep_time_s"]) or 30.0)
    if slot is None:
        return {"invoked": False, "reason": "An empty-stock state was seen after the experiment deadline."}
    _log(progress, f"experiment {root_name} handing the cheapest empty-stock state to consequence search")
    try:
        kernel = run_stockempty_consequence(
            [{"g": int(best["g"]), "ordered_digest": best["store_hex"]}],
            ceiling=int(ceiling),
            time_limit_s=float(slot),
            max_unique=int(profile["deep_unique"]),
            rss_abort_mb=float(profile["rss_abort_mb"]),
            stop_on_first_terminal=True,
        )
    except Exception as exc:
        return {"invoked": True, "status": "ERROR", "error": f"{type(exc).__name__}: {exc}"}
    record = {
        "invoked": True,
        "ceiling": int(ceiling),
        "stop_reason": kernel.stop_reason,
        "expanded": kernel.expanded,
        "unique": kernel.unique,
        "elapsed_s": round(kernel.elapsed_s, 3),
        "from_g": int(best["g"]),
        "note": (
            "Existing stock-empty consequence search. The local ceiling was passed explicitly. "
            "The temporary column restriction has already lifted because the stock length changed."
        ),
    }
    if not kernel.terminals or owner is None:
        record["status"] = "TIME_LIMIT" if kernel.stop_reason == "time limit" else (
            "EXHAUSTED" if kernel.stop_reason == "complete" else "NODE_LIMIT"
        )
        record["verified"] = False
        return record
    terminal = min(kernel.terminals, key=lambda item: int(item["g"]))
    endgame = list(kernel.reconstruct(int(terminal["node"])))
    record["terminal_g"] = int(terminal["g"])
    record["endgame_actions"] = [format_action(action) for action in endgame]
    record["verified"] = False
    record["status"] = "UNVERIFIED_HANDOFF"
    if owner.get("search_digest") and owner.get("opening_canonical") is not None:
        opening = [parse_canonical(text) for text in owner["opening_canonical"]]
        path = [parse_canonical(text) for text in best.get("path") or []]
        replay = _verify_solution(
            deal_path,
            opening,
            path + endgame,
            owner["search_digest"],
            int(owner["search_g"]),
        )
        record["replay"] = replay
        record["verified"] = bool(replay.get("ok"))
        if replay.get("ok"):
            record["status"] = "SOLVED_VALID"
            owner["status"] = "SOLVED_VALID"
            owner["replay"] = replay
            owner["terminal_g"] = int(replay["total_mw"])
            owner["improves_on_baseline"] = int(replay["total_mw"]) <= int(ceiling)
            owner["improvement_vs_baseline"] = BASELINE_MW - int(replay["total_mw"])
            owner["accepted_by"] = "stock-empty-consequence"
            owner["continuation"] = list(best.get("path") or []) + record["endgame_actions"]
        else:
            record["status"] = "INVALID"
    return record


def _comparisons(original: dict, searches, screens, deep_rows) -> list:
    rows = [
        {
            "name": "reference-suffix",
            "policy": "REFERENCE_SUFFIX",
            "stage": "known-line",
            "status": "REFERENCE_SUFFIX",
            "effort_note": "known line, not searched",
            "boundary": original,
            "immediate_deal": False,
            "structurally_promising": False,
            "debt_moved_to_column_7_or_8": _debt_moved(original),
            "terminal_value": "verified baseline suffix, not a new solution",
        }
    ]
    def add(policy_name, stage, search, canonical=None):
        boundary = _best_boundary(search)
        promising = search.get("status") != "SOLVED_VALID" and _promising(boundary, original)
        label = "Structurally promising, terminal value unresolved." if promising else None
        rows.append(
            {
                "name": f"{policy_name}-{stage}" + (f"-{canonical}" if canonical else ""),
                "policy": policy_name,
                "stage": stage,
                "first_action": canonical,
                "status": search.get("status"),
                "stop_reason": search.get("stop_reason"),
                "effort": search.get("effort"),
                "planned": search.get("planned"),
                "boundary": boundary,
                "earliest_boundary": _labeled(search, "earliest_stock_boundary"),
                "immediate_deal": bool(boundary and boundary.get("immediate_deal")),
                "structurally_promising": promising,
                "structural_label": label,
                "debt_moved_to_column_7_or_8": _debt_moved(boundary) if boundary else False,
                "improves_on_baseline": bool(search.get("improves_on_baseline")),
                "terminal_g": search.get("terminal_g"),
                "accepted_by": search.get("accepted_by"),
                "probe": search.get("probe"),
                "max_bonds_seen": (search.get("watch") or {}).get("max_bonds_seen"),
                "baseline_suffix_hit": _hit_brief((search.get("watch") or {}).get("baseline_suffix_hit")),
                "reference_suffix_hit": _hit_brief((search.get("watch") or {}).get("reference_suffix_hit")),
            }
        )

    for search in searches:
        add(search.get("policy"), "root", search)
    for screen in screens:
        for batch in screen["batches"]:
            for row in batch["results"]:
                add(screen["policy"], "screen", row["search"], row.get("canonical"))
    for row in deep_rows:
        add(row["policy"], "deep", row["search"], row.get("canonical"))
    return rows


def _best_boundary(search: dict) -> Optional[dict]:
    items = (search.get("watch") or {}).get("stock_boundaries") or []
    prepared = [item for item in items if item.get("label") == "best_scored_stock_boundary" and not item.get("immediate_deal")]
    if prepared:
        return prepared[0]
    best = [item for item in items if item.get("label") == "best_scored_stock_boundary"]
    return best[0] if best else None


def _labeled(search: dict, label: str) -> Optional[dict]:
    for item in (search.get("watch") or {}).get("stock_boundaries") or []:
        if item.get("label") == label:
            return item
    return None


def _promising(boundary: Optional[dict], original: dict) -> bool:
    if original.get("kind") != "original_suffix_next_stock_boundary":
        return False
    return structurally_promising(boundary, original)


def _debt_moved(boundary: Optional[dict]) -> bool:
    if not boundary:
        return False
    transfer = boundary.get("debt_transfer_from_root") or {}
    if int(transfer.get("focus_debt_delta") or 0) >= 0:
        return False
    for item in transfer.get("columns_7_and_8") or []:
        if int(item.get("delta") or 0) > 0:
            return True
    return False


def _hit_brief(hit: Optional[dict]) -> Optional[dict]:
    if not hit:
        return None
    return {
        "source": hit.get("source"),
        "g": hit.get("g"),
        "catalog_g": hit.get("catalog_g"),
        "saving_vs_catalog_g": hit.get("saving_vs_catalog_g"),
        "suffix_length": hit.get("suffix_length"),
        "used_to_choose_candidates": False,
    }


def _align_watch(summary, root_state, root_g, forced, focus_index):
    if not summary or not forced:
        return summary
    aligned = dict(summary)
    bounds = []
    for item in summary.get("stock_boundaries") or []:
        try:
            actions = list(forced) + [parse_canonical(text) for text in item.get("actions") or []]
            bounds.append(
                checkpoint_from_actions(
                    root_state,
                    actions,
                    label=item.get("label") or "stock_boundary",
                    root_g=root_g,
                    focus_index=focus_index,
                )
            )
        except Exception as exc:
            copied = dict(item)
            copied["align_error"] = str(exc)
            bounds.append(copied)
    aligned["stock_boundaries"] = bounds
    for key in ("baseline_suffix_hit", "reference_suffix_hit"):
        hit = summary.get(key)
        if not hit:
            continue
        copied = dict(hit)
        copied["path_from_experiment_root"] = [format_action(action) for action in forced] + list(hit.get("path") or [])
        aligned[key] = copied
    return aligned


def _write_checkpoints(artifact_dir, root_name, comparisons, searches, screens, deep_rows) -> None:
    if artifact_dir is None:
        return
    directory = Path(artifact_dir) / "checkpoints"
    directory.mkdir(parents=True, exist_ok=True)
    promising = [row for row in comparisons if row.get("structurally_promising") or row.get("improves_on_baseline")]
    payload = {
        "root": root_name,
        "promising_or_solved": promising,
        "root_searches": [
            {
                "policy": item.get("policy"),
                "status": item.get("status"),
                "stop_reason": item.get("stop_reason"),
                "effort": item.get("effort"),
            }
            for item in searches
        ],
    }
    (directory / f"{root_name}_summary.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    for row in deep_rows:
        name = f"{root_name}_{row['policy']}_deep_{row['screen_rank']}.json"
        (directory / name).write_text(
            json.dumps(
                {
                    "root": root_name,
                    "policy": row["policy"],
                    "first_action": row["canonical"],
                    "status": row["search"].get("status"),
                    "stop_reason": row["search"].get("stop_reason"),
                    "effort": row["search"].get("effort"),
                    "continuation": row["search"].get("continuation"),
                    "replay": row["search"].get("replay"),
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )


def _write_solution(artifact_dir: Path, root_name: str, search: dict, actions: Sequence) -> str:
    directory = Path(artifact_dir) / "moves"
    directory.mkdir(parents=True, exist_ok=True)
    safe_policy = str(search.get("policy") or "policy")
    safe_role = str(search.get("role") or "search")
    path = directory / f"{root_name}_{safe_policy}_{safe_role}.moves"
    resolved = path.resolve()
    root = Path(artifact_dir).resolve()
    if root not in resolved.parents and resolved != root:
        raise CounterfactualError("refusing to write a move file outside the experimental directory")
    export_actions_to_moves_file(
        list(actions),
        path,
        header=(
            "Experimental counterfactual candidate. Not an incumbent and not a canonical solution. "
            f"Policy {safe_policy}. Role {safe_role}."
        ),
    )
    return str(path)


def _public_row(row: dict, rank: int) -> dict:
    return {
        "screen_rank": rank,
        "canonical": row["canonical"],
        "cost": row["cost"],
        "suit_boundary_delta": row["suit_boundary_delta"],
        "bonds_delta": row["bonds_delta"],
        "face_down_delta": row["face_down_delta"],
        "child_g": row["child_g"],
        "child_hash": row["child_hash"],
        "rank_key": row["rank_key"],
    }


def _synthetic(policy: dict, role: str, status: str, stop_reason: str, planned: dict, note: str) -> dict:
    return {
        "policy": policy["name"],
        "kind": policy["kind"],
        "role": role,
        "status": status,
        "stop_reason": stop_reason,
        "expanded": 0,
        "generated": 0,
        "unique": 0,
        "elapsed_s": 0.0,
        "peak_rss_mb": None,
        "depth_skips": 0,
        "terminal_g": None,
        "continuation": [],
        "replay": None,
        "improves_on_baseline": False,
        "improvement_vs_baseline": None,
        "continuation_mw": None,
        "preserves_recorded_free_whole_column_moves": None,
        "planned": planned,
        "effort": {
            "elapsed_s": 0.0,
            "expanded": 0,
            "generated": 0,
            "unique": 0,
            "peak_rss_mb": None,
            "time_limit_s": 0.0,
            "planned_time_limit_s": planned.get("time_limit_s"),
            "max_unique": planned.get("max_unique"),
            "max_depth": planned.get("max_depth"),
            "rss_abort_mb": planned.get("rss_abort_mb"),
        },
        "probe": {
            "max_foundations": 0,
            "g_at_max_foundations": None,
            "min_focus_suit_boundaries_seen": None,
            "note": note,
        },
        "watch": None,
        "note": note,
    }


def _take(deadline: float, desired: float) -> Optional[float]:
    if desired is None or float(desired) <= 0:
        return None
    left = float(deadline) - time.perf_counter()
    if left < _MIN_SLICE_S:
        return None
    return min(float(desired), left)


def _select_policies(experiment_name: str, requested: str) -> list:
    chosen = []
    for policy in POLICIES:
        if experiment_name not in policy["experiments"]:
            continue
        if requested in (None, "", "all") or policy["name"] == requested:
            chosen.append(policy)
    if requested not in (None, "", "all") and not chosen:
        raise CounterfactualError(
            f"policy {requested} does not apply to experiment {experiment_name}",
            code=2,
        )
    return chosen


def _require_root(name: str) -> str:
    if name not in ROOT_KEYS:
        raise CounterfactualError(f"unknown root: {name}", code=2)
    return ROOT_KEYS[name]


def _document(*, deal_path, baseline, reference, profile, experiments, ceiling, started, repo) -> dict:
    elapsed = time.perf_counter() - started
    peaks = []
    for experiment in experiments:
        for search in _all_search_dicts(experiment):
            peak = (search.get("effort") or {}).get("peak_rss_mb")
            if peak is not None:
                peaks.append(float(peak))
    return {
        "schema": SCHEMA_VERSION,
        "mode": "profile",
        "spec_note": (
            "Sections 7 through 17 govern this run. Policies at one root share a state, a ceiling, "
            "and a stage budget. A lower experimental debt score is not a cheaper solution. "
            "TIME_LIMIT is not EXHAUSTED. The 172 route does not choose candidates. "
            "The deep profile runs only when it is requested by name."
        ),
        "deal_path": str(deal_path),
        "deal_sha256": hashlib.sha256(Path(deal_path).read_bytes()).hexdigest(),
        "baseline": baseline,
        "reference": reference,
        "git": _git_identity(repo),
        "local_ceiling": ceiling,
        "ceiling_rule": (
            f"Search prunes any child with corrected MW above {ceiling}. "
            f"The verified baseline is {BASELINE_MW}. The ceiling is a local experimental bound, "
            "not the production ceiling. The original 185 suffix is retained and is not returned "
            "as a search result unless an exact later state is reached at a strictly lower g and "
            "the spliced suffix replays."
        ),
        "profile": profile,
        "resource_settings": {
            "workers_requested": profile["workers_requested"],
            "workers_used": profile["workers_used"],
            "workers_note": profile["workers_note"],
            "search_width_requested": profile.get("search_width"),
            "search_width_used": 1,
            "search_width_note": (
                "One best-g lane is used so every policy expands in the same cost order. "
                "candidate_width caps how many first moves are screened."
            ),
            "elapsed_s": round(elapsed, 3),
            "peak_rss_mb": None if not peaks else round(max(peaks), 3),
        },
        "policies": [
            {"name": policy["name"], "kind": policy["kind"], "summary": policy["summary"]}
            for policy in POLICIES
        ],
        "intervention_definitions": [
            {"name": policy["name"], "kind": policy["kind"], "summary": policy["summary"], "experiments": list(policy["experiments"])}
            for policy in POLICIES
        ],
        "experiments": experiments,
        "search": {
            "kernel": "spider.search_kernel.run_search",
            "identity": "pack_whole_game_identity while stock remains",
            "store": "pack_state",
            "lower_bound": "stock_empty_assembly_h, which is 0 while stock remains",
            "lane": "single best-g lane; C2 appends structural tie-break keys after g",
            "not_used": (
                "campaign worker, incumbent registry, production ceiling, and search_whole_game. "
                "run_stockempty_consequence is reserved for an unsolved empty-stock state and "
                "receives this experiment's ceiling."
            ),
            "population": "Visited states are discarded. Checkpoints record a few promising states, not a campaign.",
            "time_limit_s": profile["total_time_s"],
            "max_unique": profile["deep_unique"],
            "candidate_width": profile["candidate_width"],
            "candidate_time_s": profile["screen_time_s"],
            "candidate_unique": profile["screen_unique"],
            "widen_passes_experiment_b": 1,
            "root_worker": "One bounded best-g worker per policy from the shared root.",
            "candidate_screen": "Short searches of tableau children, then a deeper pass on the strongest survivors.",
            "candidate_rank": "Survivor order is suffix hit, foundations, g, bonds, face-down, then column-4 disorder.",
            "stock_empty_worker_reason": (
                "The ordinary worker searches while stock remains. Consequence search is a handoff, "
                "not the control."
            ),
        },
        "limitations": [
            "A structurally cleaner column is supporting evidence only.",
            "The first solved terminal under the ceiling is one verified line, not a proof of the minimum.",
            "An unresolved budget is not evidence that the 185 decisions are optimal.",
            "C1 exhaustion shows only that the restriction contained no cheaper solution.",
            "TIME_LIMIT is not EXHAUSTED.",
            "Deal-now is legal and is not a prepared tableau.",
            "The experimental debt score is recorded and is not an optimisation target.",
            "A 172 suffix match is examined after ranking and does not choose the candidate.",
        ],
    }


def _all_search_dicts(experiment: dict):
    yield from experiment.get("searches", [])
    for screen in experiment.get("candidate_screens", []):
        for batch in screen.get("batches", []):
            for row in batch.get("results", []):
                yield row["search"]
    for row in experiment.get("deep_searches", []):
        yield row["search"]


def _git_identity(repo: Path) -> dict:
    def read(*args):
        try:
            return subprocess.check_output(
                ["git", *args], cwd=repo, text=True, stderr=subprocess.DEVNULL
            ).strip()
        except (subprocess.CalledProcessError, FileNotFoundError, OSError):
            return ""

    return {"branch": read("rev-parse", "--abbrev-ref", "HEAD"), "head": read("rev-parse", "HEAD")}


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _log(progress: Optional[Callable[[str], None]], message: str) -> None:
    if progress is not None:
        progress(message)
