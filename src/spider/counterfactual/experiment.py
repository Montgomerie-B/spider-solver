"""Replay roots and run bounded counterfactual continuations.

The search kernel is ``spider.search_kernel.run_search``. The local ceiling
is one corrected MW below the verified baseline. A timeout is unresolved.
An empty queue on the unmodified policy is exhaustion under that ceiling.
An empty queue on a restricted policy is exhaustion of the restriction only.

Immediate Deal is not treated as a successful candidate. The objective is a
solved board. Visited states are discarded. This module does not write a
campaign population, an incumbent, or a production ceiling.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Callable, Optional, Sequence

from spider.assembly_lower_bound import stock_empty_assembly_h
from spider.deal import load_deal
from spider.engine import SpiderState
from spider.forensics.structure import phase_label, tableau_structure
from spider.forensics.trajectory import physical_identity
from spider.metrics import (
    Action,
    format_action,
    parse_moves_file,
    replay_actions_detailed,
)
from spider.packed_state import pack_state, pack_whole_game_identity, unpack_state
from spider.research_actions import apply_action, face_down_count
from spider.search_kernel import SearchLimits, run_search
from spider.whole_game_anytime import lane_keys

from .classify import classify_stop
from .policies import (
    POLICIES,
    control_lane_key,
    focus_suit_boundaries,
    policy_actions,
    rank_discontinuities,
    same_suit_bonds,
    soft_lane_key,
)

BASELINE_MW = 185
BASELINE_ACTIONS = 189
REFERENCE_MW = 172
REFERENCE_ACTIONS = 174
SCHEMA_VERSION = "spider-counterfactual-continuations-0.106"
FREE_WHOLE_COLUMN_MOVES = ("move 8 3 1", "move 9 8 4", "move 6 9 6")


class CounterfactualError(Exception):
    """A root or a solution file failed validation. Do not search."""

    def __init__(self, message: str, code: int = 2) -> None:
        super().__init__(message)
        self.code = code


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _state_hash(state: SpiderState) -> str:
    return hashlib.sha256(pack_state(state)).hexdigest()


def _log(progress: Optional[Callable[[str], None]], message: str) -> None:
    if progress is not None:
        progress(message)


def validate_route(deal_path: Path, moves_path: Path, *, expected_mw: int, expected_actions: int) -> dict:
    if not deal_path.is_file():
        raise CounterfactualError(f"deal file not found: {deal_path}")
    if not moves_path.is_file():
        raise CounterfactualError(f"solution file not found: {moves_path}")
    actions = parse_moves_file(moves_path)
    state = SpiderState.from_cards(list(load_deal(deal_path)))
    counters = replay_actions_detailed(state, actions)
    result = {
        "moves_path": str(moves_path),
        "moves_sha256": _sha256(moves_path),
        "actions": len(actions),
        "solved": bool(state.is_solved()),
        "foundations": len(state.foundations),
        "stock_remaining": len(state.stock),
        "mobilityware_moves": int(counters["mobilityware_moves"]),
        "stock_deals": int(counters["stock_deals"]),
        "tableau_moves": int(counters["tableau_moves"]),
    }
    if result["actions"] != expected_actions or result["mobilityware_moves"] != expected_mw:
        raise CounterfactualError(
            f"{moves_path.name} replayed to {result['mobilityware_moves']} MW "
            f"in {result['actions']} actions; expected {expected_mw} MW and {expected_actions} actions"
        )
    if not result["solved"] or result["foundations"] != 8 or result["stock_remaining"] != 0:
        raise CounterfactualError(
            f"{moves_path.name} is not a complete solution: "
            f"solved={result['solved']} foundations={result['foundations']} stock={result['stock_remaining']}"
        )
    if result["stock_deals"] != 5:
        raise CounterfactualError(f"{moves_path.name} dealt {result['stock_deals']} times; expected 5")
    return result


def _snapshot(state: SpiderState, identity: Optional[dict] = None) -> dict:
    tableau = tableau_structure(state, with_readiness=True)
    columns = []
    for column in tableau["columns"]:
        columns.append(
            {
                "column": column["column"],
                "face_down": column["face_down"],
                "face_up": column["face_up"],
                "height": column["height"],
                "top_card": column["top_card"],
                "empty": column["empty"],
                "suit_boundaries": column["suit_boundaries"],
                "rank_discontinuities": column["rank_discontinuities"],
                "same_suit_bonds": column["same_suit_bonds"],
                "movable_block": column["movable_block"],
                "disorder": column["disorder"],
                "debt_indicators": column["debt_indicators"],
                "experimental_debt_score": column["experimental_debt_score"],
                "workspace_class": column["workspace_class"],
            }
        )
    return {
        "state_hash": _state_hash(state),
        "stock_rows_remaining": tableau["stock_rows_remaining"],
        "stock_cards": len(state.stock),
        "foundations": tableau["foundations_completed"],
        "face_down": tableau["face_down_remaining"],
        "empty_columns": tableau["empty_columns"],
        "empty_column_numbers": tableau["empty_column_numbers"],
        "same_suit_bonds": tableau["same_suit_bonds"],
        "experimental_debt_sum": tableau["experimental_debt_sum"],
        "experimental_debt_vector": [column["experimental_debt_score"] for column in columns],
        "experimental_debt_note": "diagnostic only; search does not optimise this score",
        "readiness_n_ready": tableau["readiness_n_ready"],
        "readiness_ready_suits": tableau["readiness_ready_suits"],
        "readiness_nearest_horizon": tableau["readiness_nearest_horizon"],
        "readiness_nearest_suits": tableau["readiness_nearest_suits"],
        "columns": columns,
        "layout": _layout(state, identity),
    }


def _layout(state: SpiderState, identity: Optional[dict]) -> list:
    rows = []
    for index, column in enumerate(state.columns):
        rows.append(
            {
                "column": index + 1,
                "face_down": [_label(card, identity) for card in column.face_down],
                "face_up": [_label(card, identity) for card in column.face_up],
            }
        )
    return rows


def _label(card, identity: Optional[dict]) -> str:
    if identity is not None and id(card) in identity:
        return identity[id(card)]["label"]
    return str(card)


def _confirm_prefix(deal_path: Path, prefix: Sequence[Action], digest: str, g: int) -> None:
    state = SpiderState.from_cards(list(load_deal(deal_path)))
    counters = replay_actions_detailed(state, list(prefix))
    if int(counters["mobilityware_moves"]) != g:
        raise CounterfactualError(
            f"prefix replay MW {counters['mobilityware_moves']} does not equal saved g {g}"
        )
    if pack_state(state).hex() != digest:
        raise CounterfactualError("prefix replay did not reach the saved root")


def _suffix_mw(digest: str, suffix: Sequence[Action]) -> int:
    state = unpack_state(bytes.fromhex(digest))
    counters = replay_actions_detailed(state, list(suffix))
    if not state.is_solved() or len(state.foundations) != 8 or len(state.stock) != 0:
        raise CounterfactualError("baseline suffix did not solve the saved root")
    return int(counters["mobilityware_moves"])


def reconstruct_roots(deal_path: Path, actions: Sequence[Action], *, focus_column: int) -> dict:
    """Build experiment roots from the baseline trace. Indexing is 1-based."""

    focus_index = focus_column - 1
    cards = list(load_deal(deal_path))
    identity = physical_identity(cards)
    before = SpiderState.from_cards(cards)
    g = 0
    root_a = None
    deals = 0
    root_b = None
    for index, action in enumerate(actions, start=1):
        if index == 25 and root_a is None:
            root_a = _root_record(
                name="A",
                title="before action 25",
                saved_when="before the next explicit action",
                state=before.clone(),
                identity=identity,
                action_index=index,
                g=g,
                next_action=action,
                prefix=list(actions[: index - 1]),
                suffix=list(actions[index - 1 :]),
                focus_index=focus_index,
                hypothesis=(
                    "An alternative arrangement from this state may avoid some column-4 "
                    "suit-boundary debt without giving up the opening's corrected-MW position."
                ),
            )
            if root_a["original_action"] != "move 6 4 1":
                raise CounterfactualError(
                    "action 25 is "
                    f"{root_a['original_action']!r}, not 'move 6 4 1'. "
                    "Refusing to search a different state.",
                    code=1,
                )
        cost = apply_action(before, action)
        g += cost
        if action == ("deal",):
            deals += 1
            if deals == 3 and root_b is None:
                root_b = _root_record(
                    name="B",
                    title="immediately after SD3",
                    saved_when="after this stock deal",
                    state=before.clone(),
                    identity=identity,
                    action_index=index,
                    g=g,
                    next_action=None,
                    prefix=list(actions[:index]),
                    suffix=list(actions[index:]),
                    focus_index=focus_index,
                    hypothesis=(
                        "From the post-SD3 state, different downstream decisions may turn "
                        "the corrected-MW lead into a cheaper finished solution."
                    ),
                )
                root_b["g_before_this_deal"] = g - cost
                root_b["this_deal_cost"] = cost
    if root_a is None or root_b is None:
        raise CounterfactualError("baseline trace has no action 25 or no third stock deal")
    if root_a["deals_completed"] != 0:
        raise CounterfactualError("action 25 is not before SD1 on this trace")
    if root_b["deals_completed"] != 3:
        raise CounterfactualError("post-SD3 root does not have three completed deals")
    for root in (root_a, root_b):
        _confirm_prefix(deal_path, root["prefix_actions_internal"], root["ordered_digest"], root["cumulative_g"])
        paid = _suffix_mw(root["ordered_digest"], root["suffix_actions_internal"])
        if root["cumulative_g"] + paid != BASELINE_MW:
            raise CounterfactualError(
                f"{root['name']} suffix cost {paid} plus g {root['cumulative_g']} is not {BASELINE_MW}"
            )
        root["suffix_remaining_mw"] = paid
    _attach_original_effect(root_a, focus_index)
    return {"A": root_a, "B": root_b}


def _root_record(
    *,
    name: str,
    title: str,
    saved_when: str,
    state: SpiderState,
    identity: dict,
    action_index: int,
    g: int,
    next_action: Optional[Action],
    prefix: Sequence[Action],
    suffix: Sequence[Action],
    focus_index: int,
    hypothesis: str,
) -> dict:
    store = pack_state(state)
    deals_completed = (50 - len(state.stock)) // 10
    rows = len(state.stock) // 10
    focus = tableau_structure(state, with_readiness=False)["columns"][focus_index]
    return {
        "name": name,
        "title": title,
        "saved_when": saved_when,
        "hypothesis": hypothesis,
        "action_index": action_index,
        "index_base": (
            "1-based explicit action. "
            "Root A is the state before this action. Root B is the state after this deal."
        ),
        "phase": phase_label(deals_completed, rows),
        "cumulative_g": g,
        "state_hash": hashlib.sha256(store).hexdigest(),
        "ordered_digest": store.hex(),
        "deals_completed": deals_completed,
        "snapshot": _snapshot(state, identity),
        "focus_column": focus_index + 1,
        "focus_suit_boundaries": focus["suit_boundaries"],
        "focus_rank_discontinuities": focus["rank_discontinuities"],
        "focus_disorder": focus["disorder"],
        "focus_experimental_debt": focus["experimental_debt_score"],
        "original_action": None if next_action is None else format_action(next_action),
        "prefix_count": len(prefix),
        "prefix_actions_internal": list(prefix),
        "suffix_actions": [format_action(action) for action in suffix],
        "suffix_actions_internal": list(suffix),
        "suffix_count": len(suffix),
        "suffix_head": [format_action(action) for action in suffix[:8]],
    }


def _attach_original_effect(root: dict, focus_index: int) -> None:
    state = unpack_state(bytes.fromhex(root["ordered_digest"]))
    action = root["suffix_actions_internal"][0]
    before_bounds = focus_suit_boundaries(state, focus_index)
    before_rank = rank_discontinuities(state.columns[focus_index].face_up)
    before_bonds = same_suit_bonds(state)
    before_fd = face_down_count(state)
    cost = apply_action(state, action)
    after_bounds = focus_suit_boundaries(state, focus_index)
    after_rank = rank_discontinuities(state.columns[focus_index].face_up)
    root["original_action_effect"] = {
        "canonical": format_action(action),
        "internal": [int(action[0]) + 1, int(action[1]) + 1, int(action[2])],
        "cost": cost,
        "suit_boundaries_before": before_bounds,
        "suit_boundaries_after": after_bounds,
        "rank_discontinuities_before": before_rank,
        "rank_discontinuities_after": after_rank,
        "disorder_before": before_bounds + before_rank,
        "disorder_after": after_bounds + after_rank,
        "bonds_delta": same_suit_bonds(state) - before_bonds,
        "face_down_delta": face_down_count(state) - before_fd,
    }


def reference_horizon(
    deal_path: Path,
    actions: Sequence[Action],
    deals_completed: int,
    *,
    focus_index: int,
) -> dict:
    cards = list(load_deal(deal_path))
    state = SpiderState.from_cards(cards)
    g = 0
    seen = 0
    for action in actions:
        g_before = g
        cost = apply_action(state, action)
        g += cost
        if action == ("deal",):
            seen += 1
            if seen == deals_completed:
                focus = tableau_structure(state, with_readiness=False)["columns"][focus_index]
                return {
                    "deals_completed": seen,
                    "g_before_deal": g_before,
                    "deal_cost": cost,
                    "cumulative_g": g,
                    "face_down": face_down_count(state),
                    "foundations": len(state.foundations),
                    "same_suit_bonds": same_suit_bonds(state),
                    "focus_disorder": focus["disorder"],
                    "focus_suit_boundaries": focus["suit_boundaries"],
                    "focus_experimental_debt": focus["experimental_debt_score"],
                }
    raise CounterfactualError(f"reference trace never completed deal {deals_completed}")


def one_ply(root: dict, *, focus_index: int, kind: str, limit: int = 8) -> dict:
    state = unpack_state(bytes.fromhex(root["ordered_digest"]))
    store = bytes.fromhex(root["ordered_digest"])
    forbidden = root["suffix_actions_internal"][0] if root["name"] == "A" else None
    legal = policy_actions(
        "control",
        state,
        focus_index=focus_index,
        root_stock_len=len(state.stock),
        root_store=store,
        forbidden=forbidden,
    )
    allowed = policy_actions(
        kind,
        state,
        focus_index=focus_index,
        root_stock_len=len(state.stock),
        root_store=store,
        forbidden=forbidden,
    )
    rows = [_child_row(state, action, focus_index, int(root["cumulative_g"])) for action in allowed]
    rows.sort(key=lambda row: (tuple(row["soft_key"]), row["canonical"]))
    original = root["original_action"]
    for rank, row in enumerate(rows, start=1):
        row["rank"] = rank
    hidden = [format_action(action) for action in legal if action not in allowed]
    return {
        "engine_legal": len(legal),
        "policy_allowed": len(allowed),
        "hidden_count": len(hidden),
        "hidden_sample": hidden[:12],
        "original_allowed": original is None or original in {row["canonical"] for row in rows},
        "original_rank": next((row["rank"] for row in rows if row["canonical"] == original), None),
        "ranked": rows[:limit],
        "note": (
            "Ranks use the C2 key on the child: cumulative corrected MW, then focus suit "
            "boundaries, then focus rank discontinuities, then more same-suit bonds. "
            "The experimental debt score is not in the key. One-ply rank is not a causal verdict."
        ),
    }


def _child_row(state: SpiderState, action: Action, focus_index: int, account_g: int) -> dict:
    before_bounds = focus_suit_boundaries(state, focus_index)
    before_bonds = same_suit_bonds(state)
    before_fd = face_down_count(state)
    trial = state.clone()
    cost = apply_action(trial, action)
    after_bounds = focus_suit_boundaries(trial, focus_index)
    key = soft_lane_key(trial, account_g + cost, focus_index)
    return {
        "canonical": format_action(action),
        "cost": cost,
        "suit_boundaries_before": before_bounds,
        "suit_boundaries_after": after_bounds,
        "suit_boundary_delta": after_bounds - before_bounds,
        "bonds_delta": same_suit_bonds(trial) - before_bonds,
        "face_down_delta": face_down_count(trial) - before_fd,
        "soft_key": list(key),
        "touches_focus": action != ("deal",) and (action[0] == focus_index or action[1] == focus_index),
    }


def rank_tableau_moves(root: dict, *, focus_index: int, kind: str, rank_mode: str) -> dict:
    """Policy-legal tableau moves, deduped by exact packed state.

    Deal is omitted here. The root worker still has Deal. A deal-now child
    is not counted as progress.
    """

    state = unpack_state(bytes.fromhex(root["ordered_digest"]))
    store = bytes.fromhex(root["ordered_digest"])
    forbidden = root["suffix_actions_internal"][0] if root["name"] == "A" else None
    allowed = policy_actions(
        kind,
        state,
        focus_index=focus_index,
        root_stock_len=len(state.stock),
        root_store=store,
        forbidden=forbidden,
    )
    deal_legal = ("deal",) in allowed
    rows = []
    for action in allowed:
        if action == ("deal",):
            continue
        row = _child_row(state, action, focus_index, int(root["cumulative_g"]))
        trial = state.clone()
        apply_action(trial, action)
        child_g = int(root["cumulative_g"]) + int(row["cost"])
        digest = pack_state(trial).hex()
        if rank_mode == "soft":
            rank_key = list(soft_lane_key(trial, child_g, focus_index))
        elif rank_mode == "construction":
            rank_key = list(lane_keys(trial, child_g)["construction"])
        else:
            raise CounterfactualError(f"unknown rank mode: {rank_mode}")
        row["rank_key"] = rank_key
        row["ordered_digest"] = digest
        row["child_g"] = child_g
        row["child_hash"] = hashlib.sha256(bytes.fromhex(digest)).hexdigest()
        row["action"] = action
        rows.append(row)
    rows.sort(key=lambda row: (tuple(row["rank_key"]), row["canonical"]))
    seen = set()
    kept = []
    for row in rows:
        if row["ordered_digest"] in seen:
            continue
        seen.add(row["ordered_digest"])
        kept.append(row)
    return {
        "enumerated_tableau": len(rows),
        "unique_children": len(kept),
        "deal_legal": deal_legal,
        "rows": kept,
    }


class _Probe:
    def __init__(self, focus_index: int) -> None:
        self.focus_index = focus_index
        self.max_foundations = 0
        self.g_at_max_foundations: Optional[int] = None
        self.min_focus_boundaries: Optional[int] = None

    def __call__(self, _kr, state: SpiderState, g: int, _node: int) -> None:
        foundations = len(state.foundations)
        if foundations > self.max_foundations or (
            foundations == self.max_foundations
            and (self.g_at_max_foundations is None or g < self.g_at_max_foundations)
        ):
            self.max_foundations = foundations
            self.g_at_max_foundations = int(g)
        boundaries = focus_suit_boundaries(state, self.focus_index)
        if self.min_focus_boundaries is None or boundaries < self.min_focus_boundaries:
            self.min_focus_boundaries = boundaries


def run_policy_search(
    root: dict,
    policy: dict,
    *,
    deal_path: Path,
    ceiling: int,
    time_limit_s: float,
    max_unique: int,
    focus_index: int,
) -> dict:
    """One bounded worker run from the experiment root. No candidate cut."""

    result = _one_pass(
        search_g=int(root["cumulative_g"]),
        search_digest=root["ordered_digest"],
        policy=policy,
        ceiling=ceiling,
        time_limit_s=time_limit_s,
        max_unique=max_unique,
        focus_index=focus_index,
        policy_root_store=bytes.fromhex(root["ordered_digest"]),
        root_stock_len=len(unpack_state(bytes.fromhex(root["ordered_digest"])).stock),
        forbidden=root["suffix_actions_internal"][0] if root["name"] == "A" else None,
        origin_g=int(root["cumulative_g"]),
        deal_path=deal_path,
        opening_prefix=list(root["prefix_actions_internal"]),
        forced_actions=[],
        experiment_name=root["name"],
    )
    result["passes"] = [
        {
            "pass": 1,
            "max_unique": max_unique,
            "time_limit_s": time_limit_s,
            "status": result["status"],
            "stop_reason": result["stop_reason"],
            "expanded": result["expanded"],
            "elapsed_s": result["elapsed_s"],
            "terminal_g": result.get("terminal_g"),
        }
    ]
    result["role"] = "root_worker"
    return result


def run_candidate_screen(
    root: dict,
    policy: dict,
    *,
    deal_path: Path,
    ceiling: int,
    focus_index: int,
    width: int,
    passes: int,
    time_limit_s: float,
    max_unique: int,
    progress: Optional[Callable[[str], None]] = None,
) -> dict:
    rank_mode = "soft" if policy["kind"] == "soft" else "construction"
    ranked = rank_tableau_moves(root, focus_index=focus_index, kind=policy["kind"], rank_mode=rank_mode)
    root_store = bytes.fromhex(root["ordered_digest"])
    root_stock_len = len(unpack_state(root_store).stock)
    forbidden = root["suffix_actions_internal"][0] if root["name"] == "A" else None
    batches = []
    offset = 0
    solved = False
    planned = max(1, passes if root["name"] == "B" else 1)
    for pass_index in range(planned):
        batch = ranked["rows"][offset : offset + width]
        if not batch:
            break
        results = []
        for row in batch:
            _log(
                progress,
                f"experiment {root['name']} {policy['name']} candidate {offset + len(results) + 1} {row['canonical']}",
            )
            search = _one_pass(
                search_g=int(row["child_g"]),
                search_digest=row["ordered_digest"],
                policy=policy,
                ceiling=ceiling,
                time_limit_s=time_limit_s,
                max_unique=max_unique,
                focus_index=focus_index,
                policy_root_store=root_store,
                root_stock_len=root_stock_len,
                forbidden=forbidden,
                origin_g=int(root["cumulative_g"]),
                deal_path=deal_path,
                opening_prefix=list(root["prefix_actions_internal"]) + [row["action"]],
                forced_actions=[row["action"]],
                experiment_name=root["name"],
            )
            search["role"] = "candidate"
            published = {
                key: value
                for key, value in row.items()
                if key not in ("ordered_digest", "action")
            }
            published["screen_rank"] = offset + len(results) + 1
            published["search"] = search
            results.append(published)
            if search["status"] == "SOLVED_VALID" and search.get("improves_on_baseline"):
                solved = True
        batches.append({"pass": pass_index + 1, "results": results})
        offset += width
        if solved or root["name"] != "B":
            break
    note = (
        "Tableau moves only. Exact child states are deduped. "
        "Deal stays in the root worker and is not a retained candidate. "
        "A cleaner child is not a cheaper solution."
    )
    if ranked["enumerated_tableau"] == 0:
        note = (
            "The policy left no tableau move at this root. Deal stayed available to the root worker. "
            "An empty tableau screen is a restriction result, not a verdict on the hidden moves."
        )
    return {
        "rank_mode": rank_mode,
        "enumerated_tableau": ranked["enumerated_tableau"],
        "unique_children": ranked["unique_children"],
        "deal_legal_under_policy": ranked["deal_legal"],
        "retained": sum(len(batch["results"]) for batch in batches),
        "batches": batches,
        "note": note,
    }


def _one_pass(
    *,
    search_g: int,
    search_digest: str,
    policy: dict,
    ceiling: int,
    time_limit_s: float,
    max_unique: int,
    focus_index: int,
    policy_root_store: bytes,
    root_stock_len: int,
    forbidden: Optional[Action],
    origin_g: int,
    deal_path: Path,
    opening_prefix: Sequence[Action],
    forced_actions: Sequence[Action],
    experiment_name: str,
    max_depth: Optional[int] = None,
    rss_abort_mb: float = 2.5 * 1024.0,
    watch=None,
    policy_blocked: bool = False,
) -> dict:
    kind = policy["kind"]

    def actions_fn(current: SpiderState):
        return policy_actions(
            kind,
            current,
            focus_index=focus_index,
            root_stock_len=root_stock_len,
            root_store=policy_root_store,
            forbidden=forbidden,
        )

    def lane_key(current: SpiderState, g: int):
        if kind == "soft":
            return soft_lane_key(current, g, focus_index)
        return control_lane_key(current, g)

    probe = _Probe(focus_index)

    def on_progress(kr, state, g, node):
        probe(kr, state, g, node)
        if watch is not None:
            watch(kr, state, g, node)

    kernel = run_search(
        [{"g": int(search_g), "ordered_digest": search_digest}],
        limits=SearchLimits(
            max_unique=int(max_unique),
            time_limit_s=float(time_limit_s),
            rss_abort_mb=float(rss_abort_mb),
            cost_ceiling=int(ceiling),
            max_depth=None if max_depth is None else int(max_depth),
        ),
        identity_fn=pack_whole_game_identity,
        store_fn=pack_state,
        unpack_fn=unpack_state,
        lane_names=("cost",),
        lane_key_fns=[lane_key],
        is_terminal=lambda st: st.is_solved(),
        actions_fn=actions_fn,
        lower_bound_fn=stock_empty_assembly_h,
        stop_on_first_terminal=True,
        on_progress=on_progress,
    )
    if watch is not None:
        watch.finish(kernel, unpack_state(bytes.fromhex(search_digest)))
    kernel_path: list = []
    replay = None
    terminal_g = None
    if kernel.terminals:
        best = min(kernel.terminals, key=lambda item: (int(item["g"]), item["ident"]))
        kernel_path = list(kernel.reconstruct(int(best["node"])))
        terminal_g = int(best["g"])
        replay = _verify_solution(
            deal_path,
            opening_prefix,
            kernel_path,
            search_digest,
            search_g,
        )
    reported = (list(forced_actions) + kernel_path) if kernel.terminals else []
    status = classify_stop(kernel.stop_reason, replay, policy_blocked=policy_blocked)
    improves = bool(
        status == "SOLVED_VALID" and replay is not None and int(replay["total_mw"]) <= int(ceiling)
    )
    preserves = None
    if experiment_name == "A" and reported:
        preserves = _is_subsequence(FREE_WHOLE_COLUMN_MOVES, [format_action(action) for action in reported])
    return {
        "policy": policy["name"],
        "kind": kind,
        "ceiling": ceiling,
        "status": status,
        "stop_reason": kernel.stop_reason,
        "expanded": kernel.expanded,
        "generated": kernel.generated,
        "unique": kernel.unique,
        "elapsed_s": round(kernel.elapsed_s, 3),
        "lower_bound_prunes": kernel.lower_bound_prunes,
        "peak_rss_mb": kernel.peak_rss_mb,
        "depth_skips": kernel.depth_skips,
        "effort": {
            "elapsed_s": round(kernel.elapsed_s, 3),
            "expanded": kernel.expanded,
            "generated": kernel.generated,
            "unique": kernel.unique,
            "peak_rss_mb": kernel.peak_rss_mb,
            "time_limit_s": float(time_limit_s),
            "max_unique": int(max_unique),
            "max_depth": max_depth,
            "rss_abort_mb": float(rss_abort_mb),
        },
        "improves_on_baseline": improves,
        "watch": None if watch is None else watch.summary(),
        "terminal_g": terminal_g,
        "continuation_mw": None if terminal_g is None else terminal_g - int(origin_g),
        "improvement_vs_baseline": None if terminal_g is None else BASELINE_MW - int(terminal_g),
        "continuation": [format_action(action) for action in reported],
        "replay": replay,
        "preserves_recorded_free_whole_column_moves": preserves,
        "probe": {
            "max_foundations": probe.max_foundations,
            "g_at_max_foundations": probe.g_at_max_foundations,
            "min_focus_suit_boundaries_seen": probe.min_focus_boundaries,
            "note": "Budget observations. Not a finished solution and not a causal total.",
        },
    }


def _verify_solution(
    deal_path: Path,
    opening_prefix: Sequence[Action],
    continuation: Sequence[Action],
    search_digest: str,
    search_g: int,
) -> dict:
    """Replay the continuation from the packed search root and from the deal file."""

    try:
        packed = unpack_state(bytes.fromhex(search_digest))
        packed_counters = replay_actions_detailed(packed, list(continuation))
    except Exception as exc:
        return {"ok": False, "error": f"packed replay failed: {exc}"}
    packed_total = int(search_g) + int(packed_counters["mobilityware_moves"])
    packed_ok = bool(packed.is_solved()) and len(packed.foundations) == 8 and len(packed.stock) == 0
    try:
        prefix_state = SpiderState.from_cards(list(load_deal(deal_path)))
        prefix_counters = replay_actions_detailed(prefix_state, list(opening_prefix))
        fresh = SpiderState.from_cards(list(load_deal(deal_path)))
        full_counters = replay_actions_detailed(fresh, list(opening_prefix) + list(continuation))
    except Exception as exc:
        return {
            "ok": False,
            "error": f"deal replay failed: {exc}",
            "packed_total_mw": packed_total,
        }
    full_total = int(full_counters["mobilityware_moves"])
    prefix_ok = (
        int(prefix_counters["mobilityware_moves"]) == int(search_g)
        and pack_state(prefix_state).hex() == search_digest
    )
    full_ok = bool(fresh.is_solved()) and len(fresh.foundations) == 8 and len(fresh.stock) == 0
    ok = packed_ok and prefix_ok and full_ok and full_total == packed_total
    error = None
    if not ok:
        error = "independent deal replay did not agree with the packed continuation"
    return {
        "ok": ok,
        "packed_solved": packed_ok,
        "prefix_reaches_root": prefix_ok,
        "deal_solved": full_ok,
        "continuation_mw": int(packed_counters["mobilityware_moves"]),
        "total_mw": full_total,
        "packed_total_mw": packed_total,
        "foundations": len(fresh.foundations),
        "stock_remaining": len(fresh.stock),
        "error": error,
    }


def _status(stop_reason: str, replay: Optional[dict], ceiling: int) -> str:
    """Compatibility wrapper. Categories are the v0.106 names."""

    del ceiling
    return classify_stop(stop_reason, replay)


def _is_subsequence(needles: Sequence[str], haystack: Sequence[str]) -> bool:
    position = 0
    for item in haystack:
        if position < len(needles) and item == needles[position]:
            position += 1
    return position == len(needles)


def _public_root(root: dict) -> dict:
    published = dict(root)
    published.pop("suffix_actions_internal", None)
    published.pop("prefix_actions_internal", None)
    published.pop("ordered_digest", None)
    return published


def run_experiments(
    deal_path: Path,
    baseline_path: Path,
    reference_path: Path,
    *,
    focus_column: int = 4,
    time_limit_s: float = 8.0,
    max_unique: int = 5_000,
    widen_passes: int = 2,
    candidate_width: int = 3,
    candidate_time_s: float = 5.0,
    candidate_unique: int = 2_500,
    ply_limit: int = 8,
    progress: Optional[Callable[[str], None]] = None,
) -> dict:
    deal_path = Path(deal_path)
    baseline_path = Path(baseline_path)
    reference_path = Path(reference_path)
    baseline = validate_route(
        deal_path, baseline_path, expected_mw=BASELINE_MW, expected_actions=BASELINE_ACTIONS
    )
    reference = validate_route(
        deal_path, reference_path, expected_mw=REFERENCE_MW, expected_actions=REFERENCE_ACTIONS
    )
    actions = parse_moves_file(baseline_path)
    reference_actions = parse_moves_file(reference_path)
    roots = reconstruct_roots(deal_path, actions, focus_column=focus_column)
    focus_index = focus_column - 1
    human_post_sd3 = reference_horizon(deal_path, reference_actions, 3, focus_index=focus_index)
    ceiling = BASELINE_MW - 1
    experiments = []
    for name in ("B", "A"):
        root = roots[name]
        policies = [policy for policy in POLICIES if name in policy["experiments"]]
        ply = {}
        searches = []
        screens = []
        for policy in policies:
            _log(progress, f"experiment {name} {policy['name']} one-ply")
            ply[policy["name"]] = one_ply(
                root, focus_index=focus_index, kind=policy["kind"], limit=ply_limit
            )
            _log(progress, f"experiment {name} {policy['name']} root worker")
            searches.append(
                run_policy_search(
                    root,
                    policy,
                    deal_path=deal_path,
                    ceiling=ceiling,
                    time_limit_s=time_limit_s,
                    max_unique=max_unique,
                    focus_index=focus_index,
                )
            )
            screen = run_candidate_screen(
                root,
                policy,
                deal_path=deal_path,
                ceiling=ceiling,
                focus_index=focus_index,
                width=candidate_width,
                passes=widen_passes,
                time_limit_s=candidate_time_s,
                max_unique=candidate_unique,
                progress=progress,
            )
            screen["policy"] = policy["name"]
            screens.append(screen)
        horizon = None
        if name == "B":
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
                    "The reference route is not an ancestor of this state."
                ),
            }
        experiments.append(
            {
                "name": name,
                "priority": "higher" if name == "B" else "secondary",
                "root": _public_root(root),
                "one_ply": ply,
                "searches": searches,
                "candidate_screens": screens,
                "stock_horizon": horizon,
            }
        )
    document = {
        "schema": SCHEMA_VERSION,
        "spec_note": (
            "The v0.106 request ended at the instruction to use the known 185 solution "
            "as a local experimental bound. This run covers that text: baseline validation, "
            "two roots, policies C0 C1 C2, the optional single-action suppression, and a "
            "bounded search. No later acceptance section was supplied."
        ),
        "deal_path": str(deal_path),
        "deal_sha256": _sha256(deal_path),
        "baseline": baseline,
        "reference": reference,
        "local_ceiling": ceiling,
        "ceiling_rule": (
            f"Search prunes any child with corrected MW above {ceiling}. "
            f"The verified baseline is {BASELINE_MW}. The ceiling is a local experimental bound, "
            "not the production ceiling. The original 185 suffix is retained on each root and "
            "is not returned as a search result."
        ),
        "search": {
            "kernel": "spider.search_kernel.run_search",
            "root_worker": (
                "Same kernel, identity, store, lower bound, ceiling, time limit, and unique cap "
                "for every policy. C0 uses every legal action, including Deal. "
                "This is the control that separates the policy from extra search."
            ),
            "candidate_screen": (
                "After the root worker, keep a small deduped set of tableau children and search "
                "each with the same policy. Experiment B may take a second slice only after the "
                "first slice has finished. Experiment A keeps one slice."
            ),
            "actions": "engine enumerate_legal_actions, then the policy",
            "identity": "pack_whole_game_identity",
            "store": "pack_state",
            "lower_bound": "stock_empty_assembly_h, which is 0 while stock remains",
            "lane": "single best-g lane; C2 appends structural tie-break keys after g",
            "candidate_rank": (
                "C0, C1, and A-suppress use the existing whole-game construction lane. "
                "C2 uses its soft key. Neither rank uses the experimental debt score."
            ),
            "time_limit_s": time_limit_s,
            "max_unique": max_unique,
            "candidate_width": candidate_width,
            "candidate_time_s": candidate_time_s,
            "candidate_unique": candidate_unique,
            "widen_passes_experiment_b": widen_passes,
            "stop": "first solved terminal under the ceiling, otherwise the budget",
            "not_used": (
                "campaign worker, incumbent registry, production ceiling, "
                "run_stockempty_consequence, search_whole_game"
            ),
            "stock_empty_worker_reason": (
                "Both roots still have stock. run_stockempty_consequence enumerates tableau "
                "moves only, so it cannot finish either continuation. search_whole_game uses "
                "seven lanes and does not stop at the first terminal, so it is not an equivalent "
                "control. C0 is the same kernel configuration as C1 and C2 with the policy removed."
            ),
            "population": "Visited states are discarded. No unresolved branch list is written.",
        },
        "policies": [
            {"name": policy["name"], "kind": policy["kind"], "summary": policy["summary"]}
            for policy in POLICIES
        ],
        "experiments": experiments,
        "limitations": [
            "A structurally cleaner column is supporting evidence only.",
            "The first solved terminal under the ceiling is one verified line, not a proof of the minimum.",
            "An unresolved budget is not evidence that the 185 decisions are optimal.",
            "C1 exhaustion shows only that the restriction contained no cheaper solution.",
            "The experimental debt score is recorded and is not an optimisation target.",
            "Free-move preservation is a textual subsequence of three canonical move lines.",
        ],
        "interpretation": [],
    }
    document["interpretation"] = interpret(document["experiments"])
    return document


def interpret(experiments: Sequence[dict]) -> list:
    lines = []
    cheaper = []
    for experiment in experiments:
        for search in _iter_searches(experiment):
            if search["status"] == "SOLVED_VALID" and search.get("improves_on_baseline"):
                cheaper.append((experiment["name"], search))
    if not cheaper:
        lines.append(
            "No policy produced a complete continuation whose independent replay is cheaper than 185."
        )
        lines.append(
            "An unresolved budget is not evidence that the original 185 decisions are optimal."
        )
    else:
        for name, search in cheaper:
            role = search.get("role", "search")
            lines.append(
                f"Experiment {name} policy {search['policy']} ({role}) replayed from the deal to "
                f"corrected MW {search['terminal_g']} "
                f"({search['improvement_vs_baseline']} below 185). "
                "This is the first terminal the bounded search generated under the ceiling."
            )
    for experiment in experiments:
        for search in experiment["searches"]:
            if search["status"] == "EXHAUSTED" and search["policy"] == "C0":
                lines.append(
                    f"Experiment {experiment['name']} exhausted the unmodified legal tree under the ceiling. "
                    "No cheaper solution exists from that root under that contract."
                )
            elif search["status"] == "EXHAUSTED" and search["policy"] == "C1":
                lines.append(
                    f"Experiment {experiment['name']} exhausted the C1 restriction under the ceiling. "
                    "That shows no cheaper solution inside the restriction. "
                    "It does not show that the hidden moves were required."
                )
        for screen in experiment.get("candidate_screens", []):
            for batch in screen["batches"]:
                for row in batch["results"]:
                    search = row["search"]
                    if search["status"] == "EXHAUSTED":
                        lines.append(
                            f"Experiment {experiment['name']} policy {search['policy']} exhausted the branch "
                            f"after {row['canonical']} under the ceiling."
                        )
    lines.append(
        "A cleaner column at an intermediate state is supporting evidence only. "
        "The claim of improvement requires the replayed solution."
    )
    return lines


def _iter_searches(experiment: dict):
    for search in experiment.get("searches", []):
        yield search
    for screen in experiment.get("candidate_screens", []):
        for batch in screen.get("batches", []):
            for row in batch.get("results", []):
                yield row["search"]
    for row in experiment.get("deep_searches", []):
        if "search" in row:
            yield row["search"]
