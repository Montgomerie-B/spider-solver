"""Divergence, horizon gaps, and forward/backward attribution.

Conclusions are graded HIGH, MEDIUM, or LOW. A grade is a statement about
how directly the recorded evidence ties cards and columns together. It is
not a proof that a move added a specific number of later MobilityWare points.
"""

from __future__ import annotations

from typing import Dict, Iterable, List, Optional, Sequence

from spider.deal import load_deal
from spider.engine import SpiderState
from spider.metrics import Action, format_action
from spider.research_actions import apply_action

from .structure import tableau_structure

SEGMENT_ROLES = (
    ("opening", "pre-SD1", "opening tableau, before SD1"),
    ("pre-SD1", "post-SD1", "SD1 itself"),
    ("post-SD1", "pre-SD2", "tableau between SD1 and SD2"),
    ("pre-SD2", "post-SD2", "SD2 itself"),
    ("post-SD2", "pre-SD3", "tableau between SD2 and SD3"),
    ("pre-SD3", "post-SD3", "SD3 itself"),
    ("post-SD3", "pre-SD4", "tableau between SD3 and SD4"),
    ("pre-SD4", "post-SD4", "SD4 itself"),
    ("post-SD4", "pre-SD5", "tableau between SD4 and SD5"),
    ("pre-SD5", "post-SD5", "SD5 itself"),
    ("post-SD5", "solved", "stock-empty endgame"),
)


def _by_role(trajectory: dict) -> Dict[str, dict]:
    return {row["role"]: row for row in trajectory["horizons"]}


def phase_gaps(route_a: dict, route_b: dict) -> List[dict]:
    """Partition the MW gap by stock-boundary segment.

    ``gap_contribution`` is the extra MW route B spent in the segment
    relative to route A. Segments that exist in only one route are omitted.
    Deal segments are usually zero because both routes pay 1 for the deal.
    """

    horizons_a = _by_role(route_a)
    horizons_b = _by_role(route_b)
    rows = []
    for start_role, end_role, title in SEGMENT_ROLES:
        if start_role not in horizons_a or end_role not in horizons_a:
            continue
        if start_role not in horizons_b or end_role not in horizons_b:
            continue
        start_a = horizons_a[start_role]
        end_a = horizons_a[end_role]
        start_b = horizons_b[start_role]
        end_b = horizons_b[end_role]
        spent_a = end_a["cumulative_g"] - start_a["cumulative_g"]
        spent_b = end_b["cumulative_g"] - start_b["cumulative_g"]
        rows.append(
            {
                "segment": f"{start_role} -> {end_role}",
                "title": title,
                "g_spent_a": spent_a,
                "g_spent_b": spent_b,
                "gap_contribution_b_minus_a": spent_b - spent_a,
                "action_index_a": [start_a["action_index"], end_a["action_index"]],
                "action_index_b": [start_b["action_index"], end_b["action_index"]],
                "debt_sum_end_a": end_a["experimental_debt_sum"],
                "debt_sum_end_b": end_b["experimental_debt_sum"],
                "disorder_sum_end_a": sum(end_a["column_disorder"]),
                "disorder_sum_end_b": sum(end_b["column_disorder"]),
                "rehandles_end_a": end_a["positive_cost_rehandle_card_events_to_date"],
                "rehandles_end_b": end_b["positive_cost_rehandle_card_events_to_date"],
                "face_down_end_a": end_a["face_down_remaining"],
                "face_down_end_b": end_b["face_down_remaining"],
                "bonds_end_a": end_a["same_suit_bonds"],
                "bonds_end_b": end_b["same_suit_bonds"],
                "empty_end_a": end_a["empty_columns"],
                "empty_end_b": end_b["empty_columns"],
                "g_end_a": end_a["cumulative_g"],
                "g_end_b": end_b["cumulative_g"],
                "lead_b_minus_a": end_b["cumulative_g"] - end_a["cumulative_g"],
            }
        )
    return rows


def divergence(route_a: dict, route_b: dict) -> dict:
    """Exact identity first. Post-stock column symmetry is reported separately."""

    events_a = route_a["events"]
    events_b = route_b["events"]
    prefix = 0
    while (
        prefix < len(events_a)
        and prefix < len(events_b)
        and events_a[prefix]["canonical"] == events_b[prefix]["canonical"]
    ):
        prefix += 1
    first_a: Dict[str, dict] = {}
    for snapshot in route_a["snapshots"]:
        first_a.setdefault(snapshot["state_hash"], snapshot)
    shared = []
    seen = set()
    for snapshot in route_b["snapshots"]:
        digest = snapshot["state_hash"]
        if digest in seen or digest not in first_a:
            continue
        seen.add(digest)
        other = first_a[digest]
        shared.append(
            {
                "state_hash": digest,
                "action_index_a": other["action_index"],
                "g_a": other["cumulative_g"],
                "phase_a": other["phase"],
                "action_index_b": snapshot["action_index"],
                "g_b": snapshot["cumulative_g"],
                "phase_b": snapshot["phase"],
            }
        )
    reconvergences = []
    terminals = []
    for row in shared:
        if row["action_index_a"] <= prefix or row["action_index_b"] <= prefix:
            continue
        solved_a = bool(route_a["snapshots"][row["action_index_a"]].get("solved"))
        solved_b = bool(route_b["snapshots"][row["action_index_b"]].get("solved"))
        if solved_a and solved_b:
            terminals.append(row)
        else:
            reconvergences.append(row)
    symmetry = _symmetry_only(route_a, route_b)
    branch_a = events_a[prefix]["canonical"] if prefix < len(events_a) else None
    branch_b = events_b[prefix]["canonical"] if prefix < len(events_b) else None
    terminal_note = ""
    if terminals:
        terminal_note = (
            " Both routes share the solved terminal state. "
            "That state is the empty completed tableau of this deal. It is not a strategic reconvergence."
        )
    if prefix == len(events_a) == len(events_b) and events_a:
        ancestry = "identical_action_sequence"
        ancestry_reason = "The action sequences are identical." + terminal_note
    elif prefix == 0 and not reconvergences:
        ancestry = "different_early_ancestry"
        ancestry_reason = (
            "The routes take different first actions and no later exact non-terminal state is shared. "
            "This is different early ancestry, not a more expensive continuation of one line."
            + terminal_note
        )
    elif prefix == 0 and reconvergences:
        ancestry = "early_split_then_exact_reconvergence"
        ancestry_reason = (
            "The first actions differ, and at least one later exact non-terminal state is shared. "
            "The routes are not the same opening continued at two costs."
            + terminal_note
        )
    elif reconvergences:
        ancestry = "shared_prefix_then_reconverged"
        ancestry_reason = (
            f"The first {prefix} actions match. After the split, the routes share "
            f"{len(reconvergences)} later exact non-terminal state(s)."
            + terminal_note
        )
    elif prefix > 0 and terminals:
        ancestry = "shared_prefix_then_different_early_ancestry"
        ancestry_reason = (
            f"The first {prefix} action(s) match. The next actions differ "
            f"(`{branch_a}` versus `{branch_b}`). "
            "After that split the routes share no exact tableau until the solved terminal. "
            "The solved empty board is the same for every complete solution of this deal and is not a strategic reconvergence. "
            "This is different early ancestry after a short shared prefix, not one line continued at two costs."
        )
    else:
        ancestry = "shared_prefix_then_diverged"
        ancestry_reason = (
            f"The first {prefix} actions match. After that split, this pair does not exactly reconverge "
            "on a non-terminal state."
            + terminal_note
        )
    return {
        "common_prefix_actions": prefix,
        "branch_state_hash": route_a["snapshots"][prefix]["state_hash"],
        "branch_g": route_a["snapshots"][prefix]["cumulative_g"],
        "first_action_a": branch_a,
        "first_action_b": branch_b,
        "shared_exact_state_count": len(shared),
        "shared_exact_states": shared,
        "reconvergences": reconvergences,
        "shared_terminal_solved_states": terminals,
        "post_stock_symmetry_only": symmetry,
        "ancestry": ancestry,
        "ancestry_reason": ancestry_reason,
        "identity": "sha256 of pack_state (ordered columns). Zobrist is not used.",
        "symmetry_rule": (
            "pack_post_stock_symmetry_state is reported only when both states have empty stock "
            "and their ordered hashes differ. It is not used while stock remains."
        ),
    }


def _symmetry_only(route_a: dict, route_b: dict) -> dict:
    index_a: Dict[str, dict] = {}
    for snapshot in route_a["snapshots"]:
        digest = snapshot.get("post_stock_symmetry_hash")
        if digest:
            index_a.setdefault(digest, snapshot)
    examples = []
    matched = 0
    for snapshot in route_b["snapshots"]:
        digest = snapshot.get("post_stock_symmetry_hash")
        if not digest or digest not in index_a:
            continue
        other = index_a[digest]
        if other["state_hash"] == snapshot["state_hash"]:
            continue
        matched += 1
        if len(examples) < 12:
            examples.append(
                {
                    "symmetry_hash": digest,
                    "action_index_a": other["action_index"],
                    "action_index_b": snapshot["action_index"],
                    "g_a": other["cumulative_g"],
                    "g_b": snapshot["cumulative_g"],
                    "ordered_hash_a": other["state_hash"],
                    "ordered_hash_b": snapshot["state_hash"],
                }
            )
    return {
        "pairs_with_same_symmetry_and_different_ordered_state": matched,
        "examples": examples,
    }


def backward_attributions(trajectory: dict, parks: Sequence[dict]) -> List[dict]:
    """Trace repair-shaped moves back to earlier placements of the same cards."""

    groups = _repair_groups(trajectory["events"])
    attributions = []
    for index, group in enumerate(groups, start=1):
        cards = []
        for event in group:
            for label in event["run_labels"]:
                if label not in cards:
                    cards.append(label)
        columns = []
        for event in group:
            if event["src_1"] and event["src_1"] not in columns:
                columns.append(event["src_1"])
        cost = sum(int(event["cost"]) for event in group)
        start = group[0]["action_index"]
        end = group[-1]["action_index"]
        linked = []
        for park in parks:
            if park["contact"] == "same_suit":
                continue
            if park["anchor"] not in cards and not set(park["cards"]).intersection(cards):
                continue
            if park["parking_column"] not in columns:
                continue
            if park["created_action"] >= start:
                continue
            removed = park["removed_action"]
            if removed is not None and removed < start:
                continue
            linked.append(park)
        linked.sort(key=lambda park: ({"HIGH": 0, "MEDIUM": 1, "LOW": 2}[park["confidence"]], park["created_action"]))
        stock_notes = _stock_contributors(trajectory["events"], cards, columns, start)
        if not linked and cost < 2 and not stock_notes:
            continue
        if linked and linked[0]["confidence"] == "HIGH" and linked[0]["anchor"] in cards:
            confidence = "HIGH"
            causal = linked[0]
            reason = (
                f"{causal['anchor']} was placed by {causal['created_canonical']} "
                f"at action {causal['created_action']} ({causal['contact']}) and is in this repair. "
                f"Park confidence was HIGH because: {causal['reason']}"
            )
            causal_action = causal["created_action"]
            causal_canonical = causal["created_canonical"]
            causal_kind = causal["contact"]
        elif linked:
            confidence = "MEDIUM" if linked[0]["confidence"] in ("HIGH", "MEDIUM") else "LOW"
            causal = linked[0]
            reason = (
                "The repaired cards overlap an earlier non-building placement, "
                f"but the link is not a single HIGH-confidence anchor removal. {causal['reason']}"
            )
            causal_action = causal["created_action"]
            causal_canonical = causal["created_canonical"]
            causal_kind = causal["contact"]
        elif stock_notes:
            confidence = "MEDIUM"
            note = stock_notes[0]
            reason = (
                "A repaired card was dealt onto this column. The deal is mandatory; "
                "the choice is the tableau left for it to land on. "
                f"Last tableau touch before that deal: {note['last_touch'] or 'none recorded'}."
            )
            causal_action = note["deal_action"]
            causal_canonical = note["deal_canonical"]
            causal_kind = "stock_landing"
        else:
            confidence = "LOW"
            reason = (
                "These moves unpack a disordered column, but no earlier placement of these "
                "physical cards was tied to that column. Column correlation only."
            )
            causal_action = None
            causal_canonical = None
            causal_kind = "column_correlation"
        intermediate = [
            event["action_index"]
            for event in trajectory["events"]
            if causal_action is not None and causal_action < event["action_index"] < start
            and (
                event["dst_1"] in columns
                or event["src_1"] in columns
                or event["action_type"] == "deal"
            )
        ]
        attributions.append(
            {
                "id": f"R{index}",
                "confidence": confidence,
                "reason": reason,
                "columns": columns,
                "cards": cards,
                "repair_actions": [event["action_index"] for event in group],
                "repair_canonical": [event["canonical"] for event in group],
                "repair_cost": cost,
                "repair_start_g": group[0]["cumulative_g"] - group[0]["cost"],
                "causal_action": causal_action,
                "causal_canonical": causal_canonical,
                "causal_kind": causal_kind,
                "linked_park_ids": [park["id"] for park in linked],
                "stock_contributors": stock_notes,
                "intermediate_actions": intermediate[:30],
                "not_a_proven_future_move_total": True,
            }
        )
    rank = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    attributions.sort(key=lambda item: (rank[item["confidence"]], -item["repair_cost"], item["repair_actions"][0]))
    return attributions


def _repair_groups(events: Sequence[dict]) -> List[List[dict]]:
    groups: List[List[dict]] = []
    current: List[dict] = []

    def is_repair(event: dict) -> bool:
        return event["action_type"] == "move" and event["cost"] > 0 and (
            event["layer_unpack"] or event["rehandle_move"]
        )

    for event in events:
        if not is_repair(event):
            if current:
                groups.append(current)
                current = []
            continue
        if not current or event["src_1"] in {item["src_1"] for item in current}:
            current.append(event)
        else:
            groups.append(current)
            current = [event]
    if current:
        groups.append(current)
    return groups


def _stock_contributors(events: Sequence[dict], cards: Sequence[str], columns: Sequence[int], repair_start: int) -> List[dict]:
    notes = []
    last_touch: Dict[int, Optional[str]] = {column: None for column in columns}
    for event in events:
        if event["action_index"] >= repair_start:
            break
        if event["action_type"] == "move" and event["dst_1"] in last_touch:
            last_touch[event["dst_1"]] = event["canonical"]
        if event["action_type"] != "deal":
            continue
        for landing in event["dealt_landings"]:
            if landing["column"] in columns and landing["label"] in cards:
                notes.append(
                    {
                        "deal_action": event["action_index"],
                        "deal_canonical": event["canonical"],
                        "column": landing["column"],
                        "label": landing["label"],
                        "column_was_awkward": landing["column_was_awkward"],
                        "rank_continues": landing["rank_continues"],
                        "last_touch": last_touch.get(landing["column"]),
                    }
                )
    return notes


def column_focus(trajectory: dict, column: int) -> dict:
    """Timeline of one column's state-only debt. ``column`` is 1-based."""

    changes = []
    for event in trajectory["events"]:
        before_d = event["focus_disorder_before"]
        after_d = event["focus_disorder_after"]
        before_s = event["focus_debt_before"]
        after_s = event["focus_debt_after"]
        if before_d is None:
            continue
        if before_d == after_d and before_s == after_s:
            continue
        changes.append(
            {
                "action_index": event["action_index"],
                "canonical": event["canonical"],
                "phase": trajectory["snapshots"][event["action_index"]]["phase"],
                "cumulative_g": event["cumulative_g"],
                "cost": event["cost"],
                "exclusive_class": event["exclusive_class"],
                "tags": list(event["tags"]),
                "disorder_before": before_d,
                "disorder_after": after_d,
                "debt_before": before_s,
                "debt_after": after_s,
                "touched_as_dest": event["dst_1"] == column,
                "touched_as_src": event["src_1"] == column,
                "revealed": list(event["revealed_labels"]),
                "bonds_delta": event["bonds_after"] - event["bonds_before"],
                "face_down_delta": event["face_down_after"] - event["face_down_before"],
                "run_labels": list(event["run_labels"]),
                "dealt_label": _dealt_label(event, column),
            }
        )
    increases = [
        row
        for row in changes
        if row["disorder_after"] > row["disorder_before"] or row["debt_after"] >= row["debt_before"] + 2
    ]
    snapshot = trajectory["snapshots"][-1]["columns"][column - 1]
    return {
        "column": column,
        "definition": (
            "disorder = suit boundaries + rank discontinuities in the face-up cards. "
            "experimental_debt_score is the documented linear combination and is not a move forecast."
        ),
        "final_disorder": snapshot["disorder"],
        "final_experimental_debt": snapshot["experimental_debt_score"],
        "final_indicators": snapshot["debt_indicators"],
        "changes": changes,
        "increases": increases,
        "first_increase": increases[0] if increases else None,
    }


def _dealt_label(event: dict, column: int) -> Optional[str]:
    for landing in event.get("dealt_landings") or []:
        if landing["column"] == column:
            return landing["label"]
    return None


def compare_focus(route_a: dict, route_b: dict, column: int, attributions: Sequence[dict]) -> dict:
    focus_b = column_focus(route_b, column)
    horizons = []
    worse = None
    map_a = _by_role(route_a)
    map_b = _by_role(route_b)
    for role in _ordered_roles(map_a, map_b):
        if role not in map_a or role not in map_b:
            continue
        left = map_a[role]
        right = map_b[role]
        disorder_a = left["column_disorder"][column - 1]
        disorder_b = right["column_disorder"][column - 1]
        debt_a = left["column_experimental_debt"][column - 1]
        debt_b = right["column_experimental_debt"][column - 1]
        row = {
            "role": role,
            "g_a": left["cumulative_g"],
            "g_b": right["cumulative_g"],
            "bonds_a": left["same_suit_bonds"],
            "bonds_b": right["same_suit_bonds"],
            "disorder_a": disorder_a,
            "disorder_b": disorder_b,
            "debt_a": debt_a,
            "debt_b": debt_b,
            "buried_face_up_a": left["column_buried_face_up"][column - 1],
            "buried_face_up_b": right["column_buried_face_up"][column - 1],
            "suit_boundaries_a": left["column_suit_boundaries"][column - 1],
            "suit_boundaries_b": right["column_suit_boundaries"][column - 1],
            "rank_discontinuities_a": left["column_rank_discontinuities"][column - 1],
            "rank_discontinuities_b": right["column_rank_discontinuities"][column - 1],
            "face_down_a": left["column_face_down"][column - 1],
            "face_down_b": right["column_face_down"][column - 1],
            "debt_sum_a": left["experimental_debt_sum"],
            "debt_sum_b": right["experimental_debt_sum"],
            "argmax_a": left["experimental_debt_argmax_column"],
            "argmax_b": right["experimental_debt_argmax_column"],
        }
        horizons.append(row)
        if worse is None and disorder_b >= disorder_a + 2 and debt_b > debt_a:
            worse = row
    touching = [
        item
        for item in attributions
        if column in item["columns"] and item["confidence"] in ("HIGH", "MEDIUM")
    ]
    same_shape = _same_liability(horizons)
    concentration = []
    for role in ("pre-SD1", "pre-SD2", "pre-SD4", "post-SD5", "stock-empty-endgame"):
        horizon = map_b.get(role)
        if horizon is None:
            continue
        vector = list(horizon["column_experimental_debt"])
        total = sum(vector)
        focus_debt = vector[column - 1]
        concentration.append(
            {
                "role": role,
                "focus_debt": focus_debt,
                "debt_sum": total,
                "share_of_experimental_score": None if total == 0 else round(focus_debt / total, 3),
                "vector": vector,
                "argmax_column": horizon["experimental_debt_argmax_column"],
            }
        )
    return {
        "column": column,
        "timeline_b": focus_b,
        "timeline_a_first_increase": (column_focus(route_a, column)["first_increase"]),
        "horizons": horizons,
        "first_materially_worse_horizon": worse,
        "debt_concentration_b": concentration,
        "repair_attributions": touching,
        "reference_also_carries_this_column": same_shape,
        "not_the_sole_cause": (
            "A focus column can be the worst column without holding most of the experimental debt, "
            "and a share of that score is not a share of the finished MW gap."
        ),
    }


def _ordered_roles(map_a: Dict[str, dict], map_b: Dict[str, dict]) -> List[str]:
    preferred = ["opening", "pre-SD1", "post-SD1", "pre-SD2", "post-SD2", "pre-SD3", "post-SD3", "pre-SD4", "post-SD4", "pre-SD5", "post-SD5", "stock-empty-endgame", "solved"]
    extra = [role for role in list(map_a) + list(map_b) if role not in preferred]
    return preferred + extra


def _same_liability(horizons: Sequence[dict]) -> dict:
    """Does the reference column stay cleaner, or does its debt merely move?"""

    if not horizons:
        return {"verdict": "unknown", "reason": "no shared horizons"}
    solved = horizons[-1]
    mid = [row for row in horizons if row["role"] not in ("opening", "solved")]
    b_worse_rows = [row["role"] for row in mid if row["disorder_b"] > row["disorder_a"]]
    a_worse_rows = [row["role"] for row in mid if row["disorder_a"] > row["disorder_b"]]
    sum_b_higher = [row["role"] for row in mid if row["debt_sum_b"] > row["debt_sum_a"]]
    if b_worse_rows and not a_worse_rows and sum_b_higher:
        verdict = "reference_avoids_this_columns_disorder"
        reason = (
            "At the compared horizons the focus column is more disordered on B, "
            "and B's experimental debt sum is also higher on at least one of those horizons. "
            "That is consistent with B carrying the liability rather than only moving it, "
            "but other columns can still hold different costs."
        )
    elif b_worse_rows and a_worse_rows:
        verdict = "both_routes_disorder_this_column_at_different_times"
        reason = "Each route has horizons where its focus column is the more disordered one."
    elif b_worse_rows and not sum_b_higher:
        verdict = "focus_column_worse_on_b_but_total_debt_is_not"
        reason = (
            "B's focus column is more disordered at some horizons while B's debt sum is not higher there. "
            "The liability may be concentrated rather than global, or the composite may be missing the cost."
        )
    else:
        verdict = "focus_column_is_not_the_distinguishing_liability"
        reason = "The focus column does not stay materially more disordered on B across the shared horizons."
    return {
        "verdict": verdict,
        "reason": reason,
        "horizons_b_more_disordered": b_worse_rows,
        "horizons_a_more_disordered": a_worse_rows,
        "horizons_b_higher_debt_sum": sum_b_higher,
        "solved_disorder_a": solved["disorder_a"],
        "solved_disorder_b": solved["disorder_b"],
    }


def counterfactual_seeds(
    deal_path,
    actions: Sequence[Action],
    trajectory: dict,
    attributions: Sequence[dict],
    *,
    focus_column: Optional[int],
    limit: int,
) -> List[dict]:
    """Immediate legal alternatives at selected earlier actions. No search."""

    selected = sorted(_select_seed_actions(trajectory, attributions, focus_column, limit))
    if not selected:
        return []
    cards = list(load_deal(deal_path))
    state = SpiderState.from_cards(cards)
    cursor = 0
    seeds = []
    for action_index in selected:
        while cursor < action_index - 1:
            apply_action(state, actions[cursor])
            cursor += 1
        seeds.append(_seed_at(state, actions[action_index - 1], action_index, trajectory, focus_column))
    return seeds


def _select_seed_actions(trajectory: dict, attributions: Sequence[dict], focus_column: Optional[int], limit: int) -> List[int]:
    ranked: List[tuple] = []
    if focus_column is not None:
        for event in trajectory["events"]:
            before = event.get("focus_disorder_before")
            after = event.get("focus_disorder_after")
            if before is None or after is None or after <= before:
                continue
            revealed = event.get("revealed_labels") or []
            if not revealed and event.get("action_type") != "deal":
                ranked.append((0, event["action_index"], "focus-column disorder increased and nothing was revealed"))
            else:
                ranked.append((1, event["action_index"], "focus-column disorder increased"))
    for item in attributions:
        if item["confidence"] == "HIGH" and item["causal_action"]:
            ranked.append((2, item["causal_action"], "HIGH backward attribution"))
        elif item["confidence"] == "MEDIUM" and item["causal_action"]:
            ranked.append((3, item["causal_action"], "MEDIUM backward attribution"))
    ranked.sort(key=lambda item: (item[0], item[1], item[2]))
    chosen = []
    seen = set()
    reasons: Dict[int, str] = {}
    for _priority, action_index, reason in ranked:
        if action_index in seen:
            reasons[action_index] = reasons[action_index] + "; " + reason
            continue
        seen.add(action_index)
        reasons[action_index] = reason
        chosen.append(action_index)
        if len(chosen) >= limit:
            break
    trajectory["_seed_reasons"] = reasons
    return chosen


def _seed_at(state: SpiderState, actual: Action, action_index: int, trajectory: dict, focus_column: Optional[int]) -> dict:
    from spider.packed_state import pack_state
    import hashlib

    legal = state.enumerate_legal_actions()
    scored = []
    for action in legal:
        trial = state.clone()
        try:
            cost = apply_action(trial, action)
        except ValueError:
            continue
        metrics = tableau_structure(trial, with_readiness=False)
        focus_debt = None if focus_column is None else metrics["columns"][focus_column - 1]["experimental_debt_score"]
        focus_disorder = None if focus_column is None else metrics["columns"][focus_column - 1]["disorder"]
        scored.append(
            {
                "canonical": format_action(action),
                "cost": cost,
                "focus_disorder": focus_disorder,
                "focus_debt": focus_debt,
                "debt_sum": metrics["experimental_debt_sum"],
                "bonds": metrics["same_suit_bonds"],
                "face_down": metrics["face_down_remaining"],
                "empty_columns": metrics["empty_columns"],
                "is_actual": format_action(action) == format_action(actual),
            }
        )
    scored.sort(
        key=lambda row: (
            row["focus_disorder"] if row["focus_disorder"] is not None else 0,
            row["focus_debt"] if row["focus_debt"] is not None else 0,
            row["debt_sum"],
            -row["bonds"],
            row["face_down"],
            row["cost"],
            row["canonical"],
        )
    )
    for rank, row in enumerate(scored, start=1):
        row["immediate_rank"] = rank
    actual_row = next(row for row in scored if row["is_actual"])
    alternatives = [row for row in scored if not row["is_actual"]][:8]
    event = trajectory["events"][action_index - 1]
    half = max(1, (len(scored) + 1) // 2)
    return {
        "action_index": action_index,
        "why": trajectory.get("_seed_reasons", {}).get(action_index, "selected"),
        "state_hash_before": hashlib.sha256(pack_state(state)).hexdigest(),
        "n_legal": len(scored),
        "actual": actual_row,
        "actual_immediate_rank": actual_row["immediate_rank"],
        "locally_ordinary_on_immediate_sort": actual_row["immediate_rank"] <= half,
        "bought": {
            "cost": event["cost"],
            "exclusive_class": event["exclusive_class"],
            "tags": list(event["tags"]),
            "revealed": list(event["revealed_labels"]),
            "bonds_delta": event["bonds_after"] - event["bonds_before"],
            "face_down_delta": event["face_down_after"] - event["face_down_before"],
            "zero_cost_whole_column": event["zero_cost_whole_column"],
        },
        "alternatives_better_on_immediate_sort": alternatives,
        "sort": "lower focus disorder, lower focus experimental debt, lower debt sum, higher same-suit bonds, lower face-down, lower cost",
        "limit": "immediate child only; not a solved continuation and not a claim that the alternative saves a stated number of moves",
    }


def build_findings(
    route_a: dict,
    route_b: dict,
    *,
    label_a: str,
    label_b: str,
    role_a: str,
    role_b: str,
    focus_column: Optional[int],
    attributions_b: Sequence[dict],
    seeds_b: Sequence[dict],
) -> dict:
    gaps = phase_gaps(route_a, route_b)
    split = divergence(route_a, route_b)
    gap_total = route_b["mobilityware_moves"] - route_a["mobilityware_moves"]
    accounted = sum(row["gap_contribution_b_minus_a"] for row in gaps)
    classes = _class_gap(route_a, route_b)
    opening = _opening(route_a, route_b, label_a, label_b)
    hypothesis = _hypothesis(opening, gaps, gap_total)
    character = _gap_character(gaps, gap_total, route_a, route_b, focus_column)
    focus = None if focus_column is None else compare_focus(route_a, route_b, focus_column, attributions_b)
    preserve, suppress = _behaviours(route_a, route_b, label_a, label_b, opening, gaps, classes, focus)
    useful, noisy = _metric_notes(gaps, focus, route_a, route_b)
    experiment = _next_experiment(focus, seeds_b, attributions_b, hypothesis)
    teaches = _teaches(route_a, route_b, label_a, label_b, opening, gaps, preserve)
    return {
        "label_a": label_a,
        "label_b": label_b,
        "role_a": role_a,
        "role_b": role_b,
        "g_a": route_a["mobilityware_moves"],
        "g_b": route_b["mobilityware_moves"],
        "g_gap_b_minus_a": gap_total,
        "phase_gap_accounted": accounted,
        "phase_gap_matches_total": accounted == gap_total,
        "phase_gaps": gaps,
        "exclusive_cost_class_gap": classes,
        "divergence": {
            "ancestry": split["ancestry"],
            "ancestry_reason": split["ancestry_reason"],
            "common_prefix_actions": split["common_prefix_actions"],
            "shared_exact_state_count": split["shared_exact_state_count"],
            "reconvergence_count": len(split["reconvergences"]),
            "shared_terminal_solved_count": len(split["shared_terminal_solved_states"]),
            "post_stock_symmetry_only_pairs": split["post_stock_symmetry_only"][
                "pairs_with_same_symmetry_and_different_ordered_state"
            ],
            "first_action_a": split["first_action_a"],
            "first_action_b": split["first_action_b"],
        },
        "opening": opening,
        "hypothesis_better_opening_worse_continuation": hypothesis,
        "gap_character": character,
        "focus_column": focus,
        "machine_behaviour_to_preserve": preserve,
        "machine_behaviour_to_suppress": suppress,
        "metrics_useful": useful,
        "metrics_noisy": noisy,
        "backward_high": [item for item in attributions_b if item["confidence"] == "HIGH"][:12],
        "backward_medium": [item for item in attributions_b if item["confidence"] == "MEDIUM"][:12],
        "counterfactual_seed_count": len(seeds_b),
        "next_experiment": experiment,
        "what_b_makes_expensive_later": _later_cost(gaps, focus, attributions_b, label_b),
        "what_a_does_materially_better": _reference_better(opening, gaps, classes, focus, label_a, label_b),
        "what_b_teaches": teaches,
    }


def _class_gap(route_a: dict, route_b: dict) -> List[dict]:
    keys = sorted(set(route_a["cost_classes"]) | set(route_b["cost_classes"]))
    rows = []
    for key in keys:
        cost_a = int(route_a["cost_classes"].get(key, 0))
        cost_b = int(route_b["cost_classes"].get(key, 0))
        rows.append({"class": key, "cost_a": cost_a, "cost_b": cost_b, "gap_b_minus_a": cost_b - cost_a})
    return rows


def _opening(route_a: dict, route_b: dict, label_a: str, label_b: str) -> dict:
    horizon_a = _by_role(route_a).get("pre-SD1")
    horizon_b = _by_role(route_b).get("pre-SD1")
    if horizon_a is None or horizon_b is None:
        return {"available": False, "reason": "one route has no pre-SD1 horizon"}
    events_a = [event for event in route_a["events"] if event["action_index"] <= horizon_a["action_index"]]
    events_b = [event for event in route_b["events"] if event["action_index"] <= horizon_b["action_index"]]

    def kinds(events: Iterable[dict]) -> dict:
        zero = [event for event in events if event["zero_cost_whole_column"]]
        return {
            "actions": len(list(events)) if not isinstance(events, list) else len(events),
            "positive_cost_moves": sum(1 for event in events if event["action_type"] == "move" and event["cost"] > 0),
            "zero_cost_whole_column_moves": len(zero),
            "zero_cost_details": [
                {
                    "action_index": event["action_index"],
                    "canonical": event["canonical"],
                    "run_labels": list(event["run_labels"]),
                    "revealed": list(event["revealed_labels"]),
                    "bonds_delta": event["bonds_after"] - event["bonds_before"],
                    "face_down_delta": event["face_down_after"] - event["face_down_before"],
                    "source_became_empty": event["source_became_empty"],
                    "cumulative_g": event["cumulative_g"],
                }
                for event in zero
            ],
            "reveals": sum(len(event["revealed_labels"]) for event in events),
        }

    stats_a = kinds(events_a)
    stats_b = kinds(events_b)
    return {
        "available": True,
        "label_a": label_a,
        "label_b": label_b,
        "g_a": horizon_a["cumulative_g"],
        "g_b": horizon_b["cumulative_g"],
        "g_gap_b_minus_a": horizon_b["cumulative_g"] - horizon_a["cumulative_g"],
        "action_index_a": horizon_a["action_index"],
        "action_index_b": horizon_b["action_index"],
        "face_down_a": horizon_a["face_down_remaining"],
        "face_down_b": horizon_b["face_down_remaining"],
        "bonds_a": horizon_a["same_suit_bonds"],
        "bonds_b": horizon_b["same_suit_bonds"],
        "compression_a": horizon_a["run_compression"],
        "compression_b": horizon_b["run_compression"],
        "empty_a": horizon_a["empty_columns"],
        "empty_b": horizon_b["empty_columns"],
        "debt_sum_a": horizon_a["experimental_debt_sum"],
        "debt_sum_b": horizon_b["experimental_debt_sum"],
        "foundations_a": horizon_a["foundations_completed"],
        "foundations_b": horizon_b["foundations_completed"],
        "rehandles_a": horizon_a["positive_cost_rehandle_card_events_to_date"],
        "rehandles_b": horizon_b["positive_cost_rehandle_card_events_to_date"],
        "stats_a": stats_a,
        "stats_b": stats_b,
        "b_opening_cheaper": horizon_b["cumulative_g"] < horizon_a["cumulative_g"],
    }


def _hypothesis(opening: dict, gaps: Sequence[dict], gap_total: int) -> dict:
    if not opening.get("available"):
        return {"supported": False, "confidence": "LOW", "reason": "pre-SD1 horizons are missing, so the opening half of the hypothesis cannot be tested"}
    opening_save = -opening["g_gap_b_minus_a"]
    later = [row for row in gaps if row["segment"] not in ("opening -> pre-SD1",) and "itself" not in row["title"]]
    later_gap = sum(row["gap_contribution_b_minus_a"] for row in later)
    losing = [row for row in later if row["gap_contribution_b_minus_a"] > 0]
    saving = [row for row in later if row["gap_contribution_b_minus_a"] < 0]
    excavation = ""
    if opening["face_down_b"] > opening["face_down_a"] or opening["bonds_b"] < opening["bonds_a"]:
        excavation = (
            f" At pre-SD1, B still has {opening['face_down_b']} face-down cards and {opening['bonds_b']} same-suit bonds; "
            f"A has {opening['face_down_a']} face-down cards and {opening['bonds_a']} bonds. "
            "Part of the opening save is doing less excavation."
        )
    path = _lead_path(gaps)
    if opening["b_opening_cheaper"] and gap_total > 0 and losing and saving:
        reason = (
            f"Before SD1, B is cheaper by {opening_save} MW ({opening['g_b']} versus {opening['g_a']}). "
            f"The finished gap is {gap_total}. "
            "The continuation is mixed: later segments include both savings and extra cost. "
            f"{path}{excavation} "
            "The cheaper-opening half is a corrected-MW fact, at confidence HIGH for the cost itself. "
            "The worse-continuation half is not uniform. "
            "This comparison does not show that the opening caused the later extra cost. Confidence for that causal reading is MEDIUM at most, and the reading is not established."
        )
        return {
            "supported": False,
            "opening_cost_cheaper": True,
            "continuation": "mixed",
            "confidence": "MEDIUM",
            "opening_save_b": opening_save,
            "later_non_deal_gap_b_minus_a": later_gap,
            "reason": reason,
        }
    if opening["b_opening_cheaper"] and gap_total > 0 and losing and not saving:
        reason = (
            f"Before SD1, B is cheaper by {opening_save} MW ({opening['g_b']} versus {opening['g_a']}). "
            f"Every later non-deal segment costs B at least as much, and the later extra sums to {later_gap}. "
            f"The finished gap is {gap_total}. {path}{excavation} "
            "The opening is cheaper and the recorded continuation is more expensive. "
            "That still does not prove the opening caused the later cost."
        )
        return {
            "supported": True,
            "opening_cost_cheaper": True,
            "continuation": "more_expensive",
            "confidence": "MEDIUM",
            "opening_save_b": opening_save,
            "later_non_deal_gap_b_minus_a": later_gap,
            "reason": reason,
        }
    if opening["b_opening_cheaper"] and gap_total > 0:
        reason = (
            f"B is cheaper before SD1 by {opening_save}, and the finished gap is {gap_total}, "
            f"but the later non-deal gap sum is {later_gap}. {path}{excavation} "
            "The continuation is not uniformly the source of the loss."
        )
        return {
            "supported": False,
            "opening_cost_cheaper": True,
            "continuation": "not_uniform",
            "confidence": "LOW",
            "opening_save_b": opening_save,
            "later_non_deal_gap_b_minus_a": later_gap,
            "reason": reason,
        }
    reason = (
        f"B's pre-SD1 cost is {opening['g_b']} and A's is {opening['g_a']}. "
        "The better-opening half of the hypothesis is not supported on corrected MW cost."
    )
    return {
        "supported": False,
        "opening_cost_cheaper": bool(opening["b_opening_cheaper"]),
        "continuation": "opening_not_cheaper",
        "confidence": "MEDIUM" if not opening["b_opening_cheaper"] else "LOW",
        "opening_save_b": opening_save,
        "later_non_deal_gap_b_minus_a": later_gap,
        "reason": reason,
    }


def _lead_path(gaps: Sequence[dict]) -> str:
    """Signed lead at the segment ends that change the story. No percentages."""

    by_segment = {row["segment"]: row for row in gaps}
    wanted = (
        "opening -> pre-SD1",
        "post-SD2 -> pre-SD3",
        "post-SD3 -> pre-SD4",
        "post-SD4 -> pre-SD5",
        "pre-SD5 -> post-SD5",
        "post-SD5 -> solved",
    )
    sentences = []
    for segment in wanted:
        row = by_segment.get(segment)
        if row is None or "g_end_b" not in row:
            continue
        end_role = segment.split(" -> ")[1]
        lead = row["lead_b_minus_a"]
        if lead < 0:
            standing = f"B is ahead by {-lead}"
        elif lead > 0:
            standing = f"B is behind by {lead}"
        else:
            standing = "the routes are level"
        if row["gap_contribution_b_minus_a"] == 0:
            if end_role != "post-SD5":
                continue
            sentence = f"At {end_role}, {standing} (g {row['g_end_b']} versus {row['g_end_a']})."
        else:
            sentence = (
                f"During {row['title']}, B spends {row['g_spent_b']} and A spends {row['g_spent_a']} "
                f"(B minus A {row['gap_contribution_b_minus_a']:+d}). "
                f"At {end_role}, {standing} (g {row['g_end_b']} versus {row['g_end_a']})."
            )
        if end_role in ("pre-SD1", "pre-SD4", "post-SD5"):
            sentence += (
                f" Bonds are {row['bonds_end_b']} versus {row['bonds_end_a']}. "
                f"Experimental debt sums are {row['debt_sum_end_b']} versus {row['debt_sum_end_a']}."
            )
        sentences.append(sentence)
    return " ".join(sentences)


def _gap_character(gaps, gap_total, route_a, route_b, focus_column) -> dict:
    if gap_total == 0:
        return {"character": "no_finished_gap", "reason": "The routes have the same corrected MW cost."}
    positive = [row for row in gaps if row["gap_contribution_b_minus_a"] > 0]
    if not positive:
        return {"character": "accounting_incomplete", "reason": "No segment shows B spending more, but the totals differ."}
    largest = max(positive, key=lambda row: row["gap_contribution_b_minus_a"])
    negative = [row for row in gaps if row["gap_contribution_b_minus_a"] < 0]
    rehandle_gap = (
        route_b["card_aggregates"]["positive_cost_rehandle_card_events"]
        - route_a["card_aggregates"]["positive_cost_rehandle_card_events"]
    )
    signed = ", ".join(
        f"{row['title']} {row['gap_contribution_b_minus_a']:+d}"
        for row in gaps
        if row["gap_contribution_b_minus_a"] != 0
    )
    offsetting = bool(positive and negative)
    if offsetting:
        character = "offsetting_segments"
        share = None
    elif gap_total and largest["gap_contribution_b_minus_a"] / gap_total >= 0.7:
        character = "concentrated_in_one_segment"
        share = round(largest["gap_contribution_b_minus_a"] / gap_total, 3)
    else:
        character = "combination"
        share = round(largest["gap_contribution_b_minus_a"] / gap_total, 3) if gap_total else None
    if offsetting:
        reason = (
            f"The finished gap is {gap_total} MW. Signed non-zero segment differences (B minus A): {signed}. "
            "Those differences sum to the finished gap. "
            "A positive segment can be larger than the finished gap because other segments are negative. "
            "That is offsetting accounting. Do not convert one segment into a share of the finished gap. "
            f"Positive-cost rehandle card-events differ by {rehandle_gap} (B minus A). "
            "Segment costs partition the gap. Rehandles, parks, and column debt overlap with it and are not a second partition."
        )
    else:
        reason = (
            f"The finished gap is {gap_total} MW. Signed non-zero segment differences (B minus A): {signed}. "
            f"The largest extra segment is {largest['title']} at {largest['gap_contribution_b_minus_a']} MW. "
            f"Positive-cost rehandle card-events differ by {rehandle_gap} (B minus A). "
            "Segment costs partition the gap. Rehandles, parks, and column debt overlap with it and are not a second partition."
        )
    return {
        "character": character,
        "largest_losing_segment": largest["segment"],
        "largest_losing_title": largest["title"],
        "largest_contribution": largest["gap_contribution_b_minus_a"],
        "largest_share_of_finished_gap": share,
        "segments_offset": offsetting,
        "positive_cost_rehandle_card_event_gap_b_minus_a": rehandle_gap,
        "reason": reason,
    }


def _behaviours(route_a, route_b, label_a, label_b, opening, gaps, classes, focus) -> tuple:
    preserve = []
    suppress = []
    if opening.get("available") and opening["b_opening_cheaper"]:
        preserve.append(
            {
                "claim": "cheaper pre-SD1 line",
                "confidence": "HIGH",
                "evidence": (
                    f"Corrected MW at pre-SD1 is {opening['g_b']} for {label_b} and {opening['g_a']} for {label_a}."
                ),
            }
        )
    if opening.get("available"):
        zero_b = opening["stats_b"]["zero_cost_whole_column_moves"]
        zero_a = opening["stats_a"]["zero_cost_whole_column_moves"]
        if zero_b > zero_a:
            details = opening["stats_b"]["zero_cost_details"]
            revealed = sum(len(item["revealed"]) for item in details)
            described = "; ".join(
                f"action {item['action_index']} `{item['canonical']}` relocates "
                f"{' '.join(item['run_labels']) or 'the whole column'}"
                f"{' and leaves the source empty' if item['source_became_empty'] else ''}"
                for item in details
            )
            if revealed == 0:
                reveal_sentence = (
                    " Together they reveal nothing and add no same-suit bonds. "
                    "They are free rearrangement of already-built runs and empty-column choreography before the deal."
                )
            else:
                reveal_sentence = f" Together they reveal {revealed} card(s)."
            preserve.append(
                {
                    "claim": "more zero-cost whole-column transfers before SD1",
                    "confidence": "HIGH",
                    "evidence": (
                        f"{label_b} plays {zero_b} zero-cost whole-column moves before SD1; "
                        f"{label_a} plays {zero_a}. {described}.{reveal_sentence} "
                        "Each such move costs 0 only because it relocates an entire column onto an empty column."
                    ),
                }
            )
        if opening["stats_b"]["positive_cost_moves"] < opening["stats_a"]["positive_cost_moves"]:
            preserve.append(
                {
                    "claim": "fewer positive-cost tableau moves before SD1",
                    "confidence": "HIGH",
                    "evidence": (
                        f"{opening['stats_b']['positive_cost_moves']} positive-cost moves on {label_b} "
                        f"versus {opening['stats_a']['positive_cost_moves']} on {label_a}."
                    ),
                }
            )
        if opening["bonds_b"] > opening["bonds_a"] and opening["g_b"] <= opening["g_a"]:
            preserve.append(
                {
                    "claim": "stronger same-suit compression before SD1 at no extra MW",
                    "confidence": "MEDIUM",
                    "evidence": f"pre-SD1 same-suit bonds {opening['bonds_b']} versus {opening['bonds_a']} at g {opening['g_b']} versus {opening['g_a']}.",
                }
            )
        if opening["face_down_b"] < opening["face_down_a"] and opening["g_b"] <= opening["g_a"]:
            preserve.append(
                {
                    "claim": "more face-down cards exposed before SD1 at no extra MW",
                    "confidence": "MEDIUM",
                    "evidence": f"face-down remaining {opening['face_down_b']} versus {opening['face_down_a']}.",
                }
            )
    for row in classes:
        if row["class"] == "ZERO_COST_WHOLE_COLUMN" and row["gap_b_minus_a"] < 0:
            # cost gap negative means B spent less in this class. Zero-cost class costs are 0.
            pass
        if row["gap_b_minus_a"] >= 4 and row["class"] in ("MIXED_SUIT_PLACEMENT", "OTHER_POSITIVE", "REVEAL", "EMPTY_PLACEMENT"):
            suppress.append(
                {
                    "claim": f"higher exclusive-class spend in {row['class']}",
                    "confidence": "MEDIUM",
                    "evidence": (
                        f"{label_b} spends {row['cost_b']} MW in {row['class']}; {label_a} spends {row['cost_a']}. "
                        "This is an accounting bucket. Moves in the bucket can also reveal or build."
                    ),
                }
            )
    re_gap = (
        route_b["card_aggregates"]["positive_cost_rehandle_card_events"]
        - route_a["card_aggregates"]["positive_cost_rehandle_card_events"]
    )
    if re_gap >= 8:
        suppress.append(
            {
                "claim": "more positive-cost rehandling of physical cards",
                "confidence": "MEDIUM",
                "evidence": (
                    f"{label_b} records {route_b['card_aggregates']['positive_cost_rehandle_card_events']} "
                    f"positive-cost rehandle card-events; {label_a} records "
                    f"{route_a['card_aggregates']['positive_cost_rehandle_card_events']}. "
                    "A card-event is not a move, and the difference is not a count of wasted moves."
                ),
            }
        )
    if focus and focus["reference_also_carries_this_column"]["horizons_b_more_disordered"]:
        suppress.append(
            {
                "claim": f"column {focus['column']} accumulates more face-up disorder than the reference at one or more stock horizons",
                "confidence": "MEDIUM",
                "evidence": (
                    "Horizons where B's focus column has higher disorder: "
                    + ", ".join(focus["reference_also_carries_this_column"]["horizons_b_more_disordered"])
                    + ". "
                    + focus["reference_also_carries_this_column"]["reason"]
                ),
            }
        )
    losing = [row for row in gaps if row["gap_contribution_b_minus_a"] >= 3]
    for row in losing:
        if "endgame" in row["title"] or "between" in row["title"]:
            suppress.append(
                {
                    "claim": f"extra MW in {row['title']}",
                    "confidence": "HIGH",
                    "evidence": (
                        f"{label_b} spends {row['g_spent_b']} and {label_a} spends {row['g_spent_a']} "
                        f"in {row['segment']} (difference {row['gap_contribution_b_minus_a']}). "
                        "This locates the cost. It does not by itself name the card that caused it."
                    ),
                }
            )
    if not preserve:
        preserve.append(
            {
                "claim": "no measured pre-SD1 economy or zero-cost advantage",
                "confidence": "LOW",
                "evidence": "The compared horizons do not show B ahead on pre-SD1 cost, zero-cost moves, bonds, or face-down.",
            }
        )
    return preserve, suppress


def _metric_notes(gaps, focus, route_a=None, route_b=None) -> tuple:
    useful = [
        {
            "metric": "corrected MW by stock-boundary segment",
            "why": "The segment differences sum to the finished gap, so they locate where moves are spent without aligning move text.",
        },
        {
            "metric": "physical-card handle and rehandle counts",
            "why": "Duplicate rank/suit cards make notation identity wrong. Deal-order ids show which card is actually shuttled.",
        },
        {
            "metric": "column suit boundaries and rank discontinuities",
            "why": "They describe mixed stacking and blockers directly. They move when a column is made harder to unwind.",
        },
    ]
    noisy = []
    if gaps:
        empties_disagree = [
            row["segment"]
            for row in gaps
            if row["gap_contribution_b_minus_a"] > 0 and row["empty_end_b"] > row["empty_end_a"]
        ]
        if empties_disagree:
            noisy.append(
                {
                    "metric": "empty-column count",
                    "why": (
                        "B has more empty columns at the end of a segment where B also spent more MW: "
                        + ", ".join(empties_disagree)
                        + ". More empties are not a quality signal on this pair."
                    ),
                }
            )
        debt_disagrees = [
            row["segment"]
            for row in gaps
            if row["gap_contribution_b_minus_a"] > 0 and row["debt_sum_end_b"] < row["debt_sum_end_a"]
        ]
        if debt_disagrees:
            noisy.append(
                {
                    "metric": "experimental debt sum",
                    "why": (
                        "The composite is lower for the more expensive route at the end of: "
                        + ", ".join(debt_disagrees)
                        + ". Keep the component vector. Do not rank lines by the composite alone."
                    ),
                }
            )
    if not noisy:
        noisy.append(
            {
                "metric": "experimental debt sum",
                "why": "It is a labelled linear combination. This pair did not produce a direct contradiction, and that is not a calibration.",
            }
        )
    if focus is None:
        useful.append(
            {
                "metric": "per-column debt vector at stock horizons",
                "why": "Comparing ten columns at a horizon shows concentration that a tableau sum hides.",
            }
        )
    else:
        useful.append(
            {
                "metric": "per-column experimental debt vector",
                "why": (
                    "The focus column's score can be the worst column and still be a minority of the tableau sum. "
                    "The vector shows the other columns. A share of the score is not a share of the MW gap."
                ),
            }
        )
    if route_a is not None and route_b is not None:
        high_a = route_a["park_summary"]["high"]
        high_b = route_b["park_summary"]["high"]
        if high_a >= 10 and high_b >= 10:
            noisy.append(
                {
                    "metric": "HIGH park count",
                    "why": (
                        f"Both routes record many HIGH parks (A {high_a}, B {high_b}). "
                        "The grade marks a temporary placement that was later moved, with the recorded evidence. "
                        "A single HIGH park is not a rare proof that the move created the finished gap."
                    ),
                }
            )
        noisy.append(
            {
                "metric": "one-ply immediate sort of legal alternatives",
                "why": (
                    "The sort prefers lower focus disorder and lower face-down before it can represent what a reveal bought. "
                    "A reveal can rank poorly because the exposed card raises disorder. That rank is not evidence the reveal was a mistake."
                ),
            }
        )
    return useful, noisy


def _later_cost(gaps, focus, attributions, label_b) -> List[dict]:
    points = []
    for row in gaps:
        if row["gap_contribution_b_minus_a"] > 0 and "itself" not in row["title"]:
            points.append(
                {
                    "confidence": "HIGH" if row["gap_contribution_b_minus_a"] >= 3 else "MEDIUM",
                    "statement": (
                        f"{label_b} spends {row['gap_contribution_b_minus_a']} more MW than the reference during {row['title']}."
                    ),
                }
            )
    for item in attributions:
        if item["confidence"] not in ("HIGH", "MEDIUM"):
            continue
        if len(points) >= 8:
            break
        points.append(
            {
                "confidence": item["confidence"],
                "statement": (
                    f"Repair {item['id']} costs {item['repair_cost']} MW on columns {item['columns']} "
                    f"and is tied, at {item['confidence']} confidence, to "
                    f"{item['causal_canonical'] or 'no single earlier action'} ({item['causal_kind']})."
                ),
            }
        )
    if focus and focus["first_materially_worse_horizon"]:
        row = focus["first_materially_worse_horizon"]
        points.append(
            {
                "confidence": "MEDIUM",
                "statement": (
                    f"Column {focus['column']} is first materially more disordered than the reference at {row['role']} "
                    f"(disorder {row['disorder_b']} versus {row['disorder_a']})."
                ),
            }
        )
    return points


def _reference_better(opening, gaps, classes, focus, label_a, label_b) -> List[str]:
    lines = []
    if opening.get("available") and opening["g_a"] > opening["g_b"]:
        lines.append(
            f"{label_a} spends more before SD1 ({opening['g_a']} versus {opening['g_b']}), so it is not the cheaper opening."
        )
    elif opening.get("available"):
        lines.append(
            f"{label_a} reaches pre-SD1 at MW {opening['g_a']}, against {opening['g_b']} for {label_b}."
        )
    for row in gaps:
        if row["gap_contribution_b_minus_a"] > 0 and "itself" not in row["title"]:
            lines.append(
                f"{label_a} spends {row['gap_contribution_b_minus_a']} fewer MW during {row['title']} "
                f"({row['g_spent_a']} versus {row['g_spent_b']} for {label_b})."
            )
    for row in classes:
        if row["gap_b_minus_a"] >= 3:
            lines.append(
                f"{label_a} spends {row['gap_b_minus_a']} fewer MW in the exclusive class {row['class']} "
                f"({row['cost_a']} versus {row['cost_b']}). This is an accounting bucket."
            )
    paid = []
    for row in gaps:
        if row["gap_contribution_b_minus_a"] < 0 and "itself" not in row["title"]:
            paid.append(
                f"{row['title']} ({row['g_spent_a']} versus {row['g_spent_b']})"
            )
    for row in classes:
        if row["gap_b_minus_a"] <= -3:
            paid.append(f"{row['class']} ({row['cost_a']} versus {row['cost_b']})")
    if paid:
        lines.append(
            f"Costs {label_a} pays that {label_b} does not match: " + "; ".join(paid) + "."
        )
    if focus:
        stock = next((row for row in focus["horizons"] if row["role"] == "post-SD5"), None)
        if stock and stock["bonds_a"] > stock["bonds_b"]:
            lines.append(
                f"At post-SD5, {label_a} holds {stock['bonds_a']} same-suit bonds against {stock['bonds_b']} for {label_b}, "
                f"with experimental debt sum {stock['debt_sum_a']} against {stock['debt_sum_b']}."
            )
    if focus:
        cleaner = focus["reference_also_carries_this_column"]["horizons_b_more_disordered"]
        if cleaner:
            lines.append(
                f"At {', '.join(cleaner)}, {label_a} keeps column {focus['column']} less disordered than {label_b}."
            )
    return lines


def _teaches(route_a, route_b, label_a, label_b, opening, gaps, preserve) -> List[dict]:
    lessons: List[dict] = []
    if opening.get("available") and opening["b_opening_cheaper"] and (
        opening["face_down_b"] > opening["face_down_a"] or opening["bonds_b"] < opening["bonds_a"]
    ):
        lessons.append(
            {
                "claim": "part of the opening save is less excavation",
                "confidence": "HIGH",
                "evidence": (
                    f"{label_b} reaches pre-SD1 at g {opening['g_b']} with {opening['face_down_b']} face-down cards, "
                    f"{opening['bonds_b']} same-suit bonds, and {opening['rehandles_b']} positive-cost rehandle card-events. "
                    f"{label_a} is at g {opening['g_a']} with {opening['face_down_a']} face-down cards, "
                    f"{opening['bonds_a']} bonds, and {opening['rehandles_a']} rehandle card-events. "
                    "The cheaper line has exposed fewer cards."
                ),
            }
        )
    lessons.extend(preserve)
    post = next((row for row in gaps if row["segment"] == "pre-SD5 -> post-SD5"), None)
    if post and post.get("lead_b_minus_a", 0) < 0 and post["bonds_end_b"] < post["bonds_end_a"]:
        lessons.append(
            {
                "claim": "being ahead on g at stock-empty can hide a worse tableau",
                "confidence": "HIGH",
                "evidence": (
                    f"At post-SD5, {label_b} is at g {post['g_end_b']} and {label_a} is at {post['g_end_a']} "
                    f"(B minus A {post['lead_b_minus_a']:+d}), with bonds {post['bonds_end_b']} versus {post['bonds_end_a']} "
                    f"and experimental debt sum {post['debt_sum_end_b']} versus {post['debt_sum_end_a']}. "
                    f"A policy that watches only g still prefers {label_b} here. "
                    "The stock-empty endgame is where that lead is spent."
                ),
            }
        )
    return lessons


def _next_experiment(focus, seeds, attributions, hypothesis) -> dict:
    high = next((item for item in attributions if item["confidence"] == "HIGH" and item["causal_action"]), None)
    seed = seeds[0] if seeds else None
    first = None if not focus else focus["timeline_b"]["first_increase"]
    post = None
    if focus:
        post = next((row for row in focus["horizons"] if row["role"] == "post-SD3"), None)
    if first is not None:
        revealed = first["revealed"] or []
        recommendation = (
            f"From the machine state immediately before action {first['action_index']} (`{first['canonical']}`), "
            f"the first recorded increase in focus-column {focus['column']} disorder "
            f"({first['disorder_before']} to {first['disorder_after']}, class {first['exclusive_class']}, "
            f"revealed {' '.join(revealed) if revealed else 'nothing'}). "
            "Run a bounded continuation that is forbidden from increasing that column's suit boundaries "
            "until the next stock boundary. "
        )
        if post is not None:
            recommendation += (
                f"Separately, start from the post-SD3 state: column {focus['column']} disorder is "
                f"{post['disorder_b']} on B versus {post['disorder_a']} on A, cumulative g is {post['g_b']} versus {post['g_a']}, "
                f"and experimental debt on the column is {post['debt_b']} versus {post['debt_a']}. "
                "Apply the same suit-boundary constraint until the next stock boundary. "
            )
        recommendation += (
            "Compare corrected MW, same-suit bonds, and the debt vector at the next stock boundary with the original continuation. "
            "Do not launch a campaign or a whole-game search. "
            "Do not imitate the reference from the first action. "
            "The one-ply seeds are screens. A poor immediate rank on a reveal is not evidence that the reveal was a mistake, "
            "because the sort can punish the disorder of the card that was just exposed."
        )
    elif seed:
        recommendation = (
            f"The earliest recorded seed is action {seed['action_index']} (`{seed['actual']['canonical']}`). "
            "Replay only the immediate alternatives already listed. Do not launch a campaign."
        )
    else:
        recommendation = (
            "No focus-column increase or card-level seed was isolated. "
            "Instrument the segment with the largest extra MW and record column disorder immediately before each stock deal."
        )
    return {
        "recommendation": recommendation,
        "hypothesis_status": hypothesis["reason"],
        "seed_action": None if first is None else first["action_index"],
        "high_attribution": None if high is None else high["id"],
    }
