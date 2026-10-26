"""Bounded legal-state search, isolated from the production controller.

Every authoritative legal action is generated. Strategic scores change
order only. They do not drop a successor, and they are not admissible
bounds. Cold mode does not accept an incumbent cost.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from spider.engine import SpiderState
from spider.human_strategy.context import build_context
from spider.human_strategy.evaluation import (
    admissible_remaining,
    longest_same_suit_run,
    same_suit_bonds,
)
from spider.human_strategy.portfolio import build_candidates
from spider.human_strategy.profiles import Profile
from spider.metrics import Action, format_action, replay_actions
from spider.packed_state import pack_state, pack_whole_game_identity, unpack_state
from spider.planner.space_lifecycle import empty_count
from spider.research_actions import (
    all_legal_actions,
    apply_action,
    face_down_count,
    is_deal,
    step_cost,
)
from spider.search_kernel import KernelResult, SearchLimits, reconstruct_path, run_search
from spider.state_identity import canonical_state_key
from spider.whole_game_anytime import lane_keys, opening_root, search_whole_game

SCHEMA = "spider-global-search-0.124"
# Same hard path cap the original anytime search uses. It is not g + h.
HARD_COST_CEILING = 300


def _rows(state: SpiderState) -> int:
    return len(state.stock) // 10


def strategy_features(state: SpiderState) -> tuple:
    """One ordering tuple. Lower is preferred.

    Foundations are one component. Face-down count, same-suit structure,
    empty columns, and stock stage are others. Corrected cost is applied
    by the caller. This tuple is not an admissible bound.
    """

    return (
        face_down_count(state) - 20 * len(state.foundations),
        -same_suit_bonds(state),
        -longest_same_suit_run(state),
        -empty_count(state),
        _rows(state),
    )


def strategic_action_order(
    state: SpiderState,
    actions: Sequence[Action],
    *,
    seed: int = 0,
) -> List[Action]:
    """Sort every legal action. The returned list has the same members."""

    ranked = []
    for index, action in enumerate(actions):
        if is_deal(action):
            primary = (1, 0, 0, 0, 0)
        else:
            src, dst, k = action
            src_col = state.columns[src]
            dst_col = state.columns[dst]
            run = src_col.face_up[-k:]
            top = dst_col.top()
            same = (
                0
                if top is not None
                and run
                and top.suit == run[0].suit
                and top.rank == run[0].rank + 1
                else 1
            )
            reveal = 0 if len(src_col.face_up) == k and src_col.face_down else 1
            onto_empty = 0 if dst_col.is_empty() else 1
            primary = (0, same, reveal, onto_empty, -int(k))
        if seed == 0:
            tie = index
        else:
            tie = (seed * 1_000_003 + index * 97 + step_cost(state, action)) % 1_000_000_007
        ranked.append((primary, tie, index, action))
    ranked.sort()
    ordered = [item[-1] for item in ranked]
    if set(ordered) != set(actions) or len(ordered) != len(actions):
        raise RuntimeError("strategic ordering dropped a legal action")
    return ordered


def _strategy_lanes(state: SpiderState, g: int) -> Dict[str, tuple]:
    keys = lane_keys(state, g)
    keys["strategy"] = strategy_features(state) + (int(g),)
    return keys


@dataclass
class GlobalSearchResult:
    schema: str = SCHEMA
    variant: str = "strategy"
    mode: str = "cold"
    solved: bool = False
    replay_ok: bool = False
    solution_g: Optional[int] = None
    replay_g: Optional[int] = None
    actions: Tuple[Action, ...] = ()
    max_foundations: int = 0
    best_partial: Optional[dict] = None
    foundation_times: Dict[int, dict] = field(default_factory=dict)
    strata: Dict[str, dict] = field(default_factory=dict)
    unique: int = 0
    expanded: int = 0
    generated: int = 0
    duplicate_skips: int = 0
    stale_skips: int = 0
    lower_bound_prunes: int = 0
    heuristic_exclusions: int = 0
    elapsed_s: float = 0.0
    cpu_s: float = 0.0
    peak_rss_mb: Optional[float] = None
    stop_reason: str = ""
    seed: int = 0
    incumbent_cost: Optional[int] = None
    imported_incumbent: bool = False
    stock_deals: int = 0
    cost_ceiling: Optional[int] = None
    ceiling_kind: str = "none"
    lane_pops: Dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict:
        partial = None if self.best_partial is None else dict(self.best_partial)
        if partial is not None:
            partial["actions"] = [
                format_action(action) for action in partial.get("actions") or []
            ]
        return {
            "schema": self.schema,
            "variant": self.variant,
            "mode": self.mode,
            "solved": self.solved,
            "replay_ok": self.replay_ok,
            "solution_g": self.solution_g,
            "replay_g": self.replay_g,
            "actions": [format_action(action) for action in self.actions],
            "max_foundations": self.max_foundations,
            "best_partial": partial,
            "foundation_times": {str(key): value for key, value in self.foundation_times.items()},
            "strata": self.strata,
            "unique": self.unique,
            "expanded": self.expanded,
            "generated": self.generated,
            "duplicate_skips": self.duplicate_skips,
            "stale_skips": self.stale_skips,
            "lower_bound_prunes": self.lower_bound_prunes,
            "heuristic_exclusions": self.heuristic_exclusions,
            "legal_actions_dropped": 0,
            "stock_deals": self.stock_deals,
            "elapsed_s": round(self.elapsed_s, 3),
            "cpu_s": round(self.cpu_s, 3),
            "peak_rss_mb": None if self.peak_rss_mb is None else round(self.peak_rss_mb, 2),
            "stop_reason": self.stop_reason,
            "seed": self.seed,
            "incumbent_cost": self.incumbent_cost,
            "imported_incumbent": self.imported_incumbent,
            "cost_ceiling": self.cost_ceiling,
            "ceiling_kind": self.ceiling_kind,
            "lane_pops": self.lane_pops,
            "notes": (
                "duplicate_skips are exact-state dominances inside the kernel. "
                "heuristic_exclusions is 0 because every legal action is generated. "
                "strategy features order one lane. They do not prove a state impossible. "
                "A hard_path_cap skips g above that integer. It is not an admissible bound. "
                "admissible_incumbent prunes only when g + admissible_remaining cannot beat the imported ceiling."
            ),
        }


def _partial_record(state: SpiderState, g: int, node: int, elapsed: float) -> dict:
    return {
        "g": int(g),
        "node": int(node),
        "elapsed_s": round(float(elapsed), 3),
        "foundations": len(state.foundations),
        "face_down": face_down_count(state),
        "bonds": same_suit_bonds(state),
        "longest_run": longest_same_suit_run(state),
        "empty_columns": empty_count(state),
        "stock_rows": _rows(state),
        "stock_cards": len(state.stock),
        "solved": bool(state.is_solved()),
    }


def _better_partial(candidate: dict, current: Optional[dict]) -> bool:
    """Report key. Foundations help, then structure, then cost. Not a prune."""

    if current is None:
        return True
    new = (
        0 if candidate["solved"] else 1,
        -int(candidate["foundations"]),
        int(candidate["face_down"]),
        -int(candidate["bonds"]),
        -int(candidate["longest_run"]),
        int(candidate["stock_rows"]),
        int(candidate["g"]),
    )
    old = (
        0 if current["solved"] else 1,
        -int(current["foundations"]),
        int(current["face_down"]),
        -int(current["bonds"]),
        -int(current["longest_run"]),
        int(current["stock_rows"]),
        int(current["g"]),
    )
    return new < old


def search_strategy_guided(
    opening: SpiderState,
    *,
    time_limit_s: float,
    max_unique: int,
    rss_abort_mb: float,
    seed: int = 0,
    mode: str = "cold",
    incumbent_cost: Optional[int] = None,
    cost_ceiling: Optional[int] = HARD_COST_CEILING,
) -> GlobalSearchResult:
    """Best-first legal graph search with one extra strategy lane.

    ``mode="cold"`` rejects an incumbent cost. The default ceiling is the
    original hard path cap, with no admissible remainder. ``mode="optimise"``
    prunes only when ``g + admissible_remaining`` cannot beat ``incumbent_cost``.
    """

    if mode not in {"cold", "optimise"}:
        raise ValueError(f"unknown mode {mode!r}")
    if mode == "cold" and incumbent_cost is not None:
        raise ValueError("cold search refuses an incumbent cost")
    if mode == "optimise" and incumbent_cost is None:
        raise ValueError("optimise search requires an incumbent cost")
    if mode == "optimise":
        ceiling: Optional[int] = int(incumbent_cost) - 1
        if cost_ceiling is not None:
            ceiling = min(ceiling, int(cost_ceiling))
        ceiling_kind = "admissible_incumbent"
    else:
        ceiling = None if cost_ceiling is None else int(cost_ceiling)
        ceiling_kind = "none" if ceiling is None else "hard_path_cap"
    out = GlobalSearchResult(
        variant="strategy",
        mode=mode,
        seed=int(seed),
        incumbent_cost=None if incumbent_cost is None else int(incumbent_cost),
        imported_incumbent=mode == "optimise",
        cost_ceiling=ceiling,
        ceiling_kind=ceiling_kind,
    )
    started = time.perf_counter()
    cpu_started = time.process_time()
    best_node = 0

    def on_progress(kr: KernelResult, state: SpiderState, g: int, node: int) -> None:
        nonlocal best_node
        elapsed = time.perf_counter() - started
        rec = _partial_record(state, g, node, elapsed)
        found = int(rec["foundations"])
        if found > out.max_foundations:
            out.max_foundations = found
        if found not in out.foundation_times and found > 0:
            out.foundation_times[found] = {
                "elapsed_s": rec["elapsed_s"],
                "g": rec["g"],
                "face_down": rec["face_down"],
                "stock_rows": rec["stock_rows"],
            }
        key = f"f{found}_stock{rec['stock_rows']}"
        held = out.strata.get(key)
        if held is None or (rec["face_down"], -rec["bonds"], rec["g"]) < (
            held["face_down"],
            -held["bonds"],
            held["g"],
        ):
            out.strata[key] = {k: v for k, v in rec.items()}
        if _better_partial(rec, out.best_partial):
            out.best_partial = rec
            best_node = node

    def order(state: SpiderState, actions: List[Action]) -> List[Action]:
        return strategic_action_order(state, actions, seed=seed)

    ceiling = None if incumbent_cost is None else int(incumbent_cost) - 1

    def lower_bound(state: SpiderState, g: int) -> int:
        return admissible_remaining(state)

    kr = run_search(
        [opening_root(opening)],
        limits=SearchLimits(
            max_unique=int(max_unique),
            time_limit_s=float(time_limit_s),
            rss_abort_mb=float(rss_abort_mb),
            cost_ceiling=ceiling,
        ),
        identity_fn=pack_whole_game_identity,
        store_fn=pack_state,
        unpack_fn=unpack_state,
        lane_names=(
            "cost",
            "foundation",
            "reveal",
            "workspace",
            "construction",
            "prep",
            "epoch",
            "strategy",
        ),
        lane_keys_fn=_strategy_lanes,
        is_terminal=lambda st: st.is_solved(),
        actions_fn=all_legal_actions,
        action_order=order,
        on_progress=on_progress,
        lower_bound_fn=None if mode == "cold" else lower_bound,
        stop_on_first_terminal=True,
    )
    out.unique = kr.unique
    out.expanded = kr.expanded
    out.generated = kr.generated
    out.duplicate_skips = kr.duplicate_skips
    out.stale_skips = kr.stale_skips
    out.lower_bound_prunes = kr.lower_bound_prunes
    out.heuristic_exclusions = 0
    out.stock_deals = sum(1 for node in kr.nodes if node.action is not None and is_deal(node.action))
    out.elapsed_s = kr.elapsed_s
    out.cpu_s = time.process_time() - cpu_started
    out.peak_rss_mb = kr.peak_rss_mb
    out.stop_reason = kr.stop_reason
    out.lane_pops = dict(kr.lane_pops)
    path: List[Action] = []
    if kr.terminals:
        best = min(kr.terminals, key=lambda item: (item["g"], item["store"]))
        path = reconstruct_path(kr.nodes, best["node"])
        out.solution_g = int(best["g"])
    elif out.best_partial is not None:
        path = reconstruct_path(kr.nodes, best_node)
    out.actions = tuple(path)
    if path:
        trial = opening.clone()
        try:
            cost = int(replay_actions(trial, list(path)))
        except ValueError:
            out.replay_ok = False
        else:
            out.replay_g = cost
            solved = (
                trial.is_solved()
                and len(trial.foundations) == 8
                and not trial.stock
                and all(column.is_empty() for column in trial.columns)
            )
            out.solved = bool(kr.terminals) and solved and cost == out.solution_g
            out.replay_ok = out.solved or (
                not kr.terminals and cost == int(out.best_partial["g"])
            )
            if out.best_partial is not None and not kr.terminals:
                out.best_partial["actions"] = list(path)
                out.best_partial["replay_g"] = cost
    return out


def search_original_kernel(
    opening: SpiderState,
    *,
    time_limit_s: float,
    max_unique: int,
    rss_abort_mb: float,
    cost_ceiling: int = 300,
) -> dict:
    """The existing whole-game kernel. Legal actions stay complete.

    ``cost_ceiling`` is the original hard path cap, not an admissible bound.
    """

    cpu_started = time.process_time()
    result = search_whole_game(
        opening=opening,
        max_unique=int(max_unique),
        time_limit_s=float(time_limit_s),
        rss_abort_mb=float(rss_abort_mb),
        cost_ceiling=int(cost_ceiling),
    )
    cpu_s = time.process_time() - cpu_started
    actions = [format_action(action) for action in result.solution_actions] if result.solved else []
    return {
        "schema": SCHEMA,
        "variant": "original_kernel",
        "mode": "cold",
        "solved": bool(result.solved and result.replay_ok),
        "replay_ok": bool(result.replay_ok),
        "solution_g": result.solution_g,
        "replay_g": result.replay_g,
        "actions": actions,
        "max_foundations": int(result.max_foundations),
        "best_state": _public_snapshot(result.best_state),
        "min_face_down": result.min_face_down,
        "foundation_times": {
            str(key): _public_snapshot(value) for key, value in result.foundations_first.items()
        },
        "unique": int(result.unique),
        "expanded": int(result.expanded),
        "generated": int(result.generated),
        "duplicate_skips": int(result.duplicate_skips),
        "stale_skips": int(result.stale_skips),
        "heuristic_exclusions": 0,
        "legal_actions_dropped": 0,
        "stock_deals": sum(1 for action in result.solution_actions if is_deal(action)) if result.solved else None,
        "elapsed_s": round(float(result.elapsed_s), 3),
        "cpu_s": round(cpu_s, 3),
        "peak_rss_mb": None if result.peak_rss_mb is None else round(float(result.peak_rss_mb), 2),
        "stop_reason": result.stop_reason,
        "cost_ceiling": int(cost_ceiling),
        "ceiling_kind": "hard_path_cap",
        "lane_pops": dict(result.lane_pops),
        "cost_ceiling_note": (
            "Hard corrected-cost cap from the original anytime search. "
            "It is not g plus an admissible remainder."
        ),
        "imported_incumbent": False,
        "notes": (
            "This is search_whole_game. Every engine-legal action is generated. "
            "Lanes order only. stock_deals is the deal count of a solved path. "
            "An unsolved run does not return that path's deal count."
        ),
    }


def classify_objective_coverage(state: SpiderState, profile: Profile, *, g: int = 0) -> dict:
    """Compare authoritative legal moves with portfolio candidates.

    This is the objective generator, before the campaign gate. A move outside
    the strategic width is a heuristic cutoff. It is not safe dominance and
    it is not an admissible prune.
    """

    legal = list(all_legal_actions(state))
    ranked = build_candidates(build_context(state, int(g)), profile, blocked_ids=())
    scored: List[Action] = []
    for item in ranked:
        if item.actions:
            scored.append(item.actions[0])
    scored_set = set(scored)
    width = max(1, int(profile.strategic_width))
    within: List[Action] = []
    for item in ranked[:width]:
        if item.actions:
            within.append(item.actions[0])
    within_set = set(within)
    not_scored = [action for action in legal if action not in scored_set]
    outside_width = [action for action in legal if action in scored_set and action not in within_set]
    return {
        "legal_count": len(legal),
        "scored_count": len(scored_set & set(legal)),
        "width": width,
        "within_width": [format_action(action) for action in within],
        "not_scored": [format_action(action) for action in not_scored],
        "outside_width": [format_action(action) for action in outside_width],
        "selected": None if not ranked or not ranked[0].actions else format_action(ranked[0].actions[0]),
        "classes": {
            "not_generated_by_objective_system": [format_action(action) for action in not_scored],
            "heuristic_rank_cutoff": [format_action(action) for action in outside_width],
            "safe_dominance": [],
            "admissible_incumbent_prune": [],
            "resource_limited": [],
        },
        "note": (
            "build_candidates scores legal actions. The controller then keeps "
            "strategic_width of them and executes one objective. A campaign "
            "with no step leaves the state without playing the scored move. "
            "That gate is not in this classification. Safe dominance and "
            "admissible pruning happen later, in the frontier and proof_prune."
        ),
    }


def _public_snapshot(record: Optional[dict]) -> Optional[dict]:
    if not isinstance(record, dict):
        return None
    hidden = {"ordered_digest", "whole_game_identity", "post_stock_topology"}
    return {key: value for key, value in record.items() if key not in hidden}


def replay_cost(opening: SpiderState, actions: Sequence[Action]) -> Tuple[SpiderState, int]:
    """Replay ``actions`` on a clone. Returns the end state and corrected cost."""

    state = opening.clone()
    cost = 0
    for action in actions:
        cost += apply_action(state, action)
    return state, int(cost)


def position_coverage(state: SpiderState, profile: Profile, *, g: int, name: str) -> dict:
    """Legal successors versus the objective slice at one physical state."""

    classified = classify_objective_coverage(state, profile, g=g)
    legal = list(all_legal_actions(state))
    keys = set()
    for action in legal:
        child = state.clone()
        apply_action(child, action)
        keys.add(canonical_state_key(child))
    classified["name"] = name
    classified["g"] = int(g)
    classified["foundations"] = len(state.foundations)
    classified["face_down"] = face_down_count(state)
    classified["bonds"] = same_suit_bonds(state)
    classified["longest_run"] = longest_same_suit_run(state)
    classified["empty_columns"] = empty_count(state)
    classified["stock_cards"] = len(state.stock)
    classified["stock_rows"] = _rows(state)
    classified["deal_legal"] = any(is_deal(action) for action in legal)
    classified["distinct_successor_states"] = len(keys)
    classified["kernel_would_generate"] = len(legal)
    classified["objective_count_is_not_successor_count"] = True
    return classified


def matching_ancestries(
    opening: SpiderState,
    target_actions: Sequence[Action],
    branches: Sequence[dict],
) -> dict:
    """Find stored branch prefixes that reach the same physical state."""

    from spider.counterfactual.boundaries import parse_canonical

    target_state, target_g = replay_cost(opening, target_actions)
    target = canonical_state_key(target_state)
    hits = []
    for branch in branches:
        raw = branch.get("actions") or []
        actions: List[Action] = []
        for item in raw:
            if isinstance(item, str):
                actions.append(parse_canonical(item))
            else:
                actions.append(item)
        state = opening.clone()
        cost = 0
        matched = False
        for index, action in enumerate(actions, start=1):
            cost += apply_action(state, action)
            if canonical_state_key(state) == target:
                hits.append(
                    {
                        "g": int(cost),
                        "actions": index,
                        "label": branch.get("label"),
                        "branch_g": branch.get("g"),
                        "branch_status": branch.get("status"),
                    }
                )
                matched = True
                break
        if not matched:
            continue
    hits.sort(key=lambda item: (int(item["g"]), int(item["actions"])))
    cheapest = hits[0] if hits else None
    return {
        "target_actions": len(list(target_actions)),
        "target_g": int(target_g),
        "target_foundations": len(target_state.foundations),
        "target_face_down": face_down_count(target_state),
        "matches": len(hits),
        "cheapest": cheapest,
        "cheapest_dominates_target": bool(cheapest and int(cheapest["g"]) < int(target_g)),
        "sample": hits[:6],
    }
