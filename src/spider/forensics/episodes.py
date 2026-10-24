"""Park and workspace episodes derived from a replay.

Both classifications are heuristics. Every episode keeps the evidence used
to grade it. Confidence is HIGH, MEDIUM, or LOW. LOW means the placement
is ambiguous and is not asserted to be a park or a useful workspace.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence


def _deals_between(events: Sequence[dict], start: int, end: int) -> int:
    return sum(
        1
        for event in events
        if event["action_type"] == "deal" and start < event["action_index"] <= end
    )


def _column_metrics_at(snapshots: Sequence[dict], action_index: int, column: int) -> dict:
    return snapshots[action_index]["columns"][column - 1]


def build_parks(trajectory: dict) -> List[dict]:
    """Classify temporary placements. Same-suit builds are kept only as LOW."""

    events = trajectory["events"]
    snapshots = trajectory["snapshots"]
    open_parks: Dict[str, dict] = {}
    parks: List[dict] = []
    next_id = 1

    def close_anchor(label: str, event: dict, how: str) -> None:
        park = open_parks.pop(label, None)
        if park is None:
            return
        park["removed_action"] = event["action_index"]
        park["removed_canonical"] = event["canonical"]
        park["g_removed"] = event["cumulative_g"]
        park["removal_cost"] = event["cost"] if label in event["run_labels"] else 0
        park["removal_how"] = how
        park["lifetime_actions"] = event["action_index"] - park["created_action"]
        park["stock_deals_crossed"] = _deals_between(events, park["created_action"], event["action_index"])
        _finish_park(park, snapshots, events)
        parks.append(park)

    for event in events:
        # Close parks whose anchor leaves its column or completes in place.
        moving = set(event["run_labels"])
        founded = set(event["foundation_labels"])
        for label in list(open_parks):
            park = open_parks[label]
            if label in moving and event["src_1"] == park["parking_column"]:
                how = "moved_to_foundation" if label in founded else "moved_away"
                close_anchor(label, event, how)
            elif label in founded and label not in moving:
                close_anchor(label, event, "absorbed_in_place")
        if event["action_type"] != "move" or not event["anchor_label"]:
            continue
        # A same-suit attach is recorded so a later disassembly is visible,
        # but it starts at LOW and is not described as a park.
        contact = _contact(event)
        anchor = event["anchor_label"]
        # If this move just closed a park and opened another with the same
        # anchor, the close already happened above.
        before = _column_metrics_at(snapshots, event["action_index"] - 1, event["dst_1"])
        after = _column_metrics_at(snapshots, event["action_index"], event["dst_1"])
        park = {
            "id": f"P{next_id}",
            "cards": list(event["run_labels"]),
            "anchor": anchor,
            "run_length": event["k"],
            "source_column": event["src_1"],
            "parking_column": event["dst_1"],
            "created_action": event["action_index"],
            "created_canonical": event["canonical"],
            "g_created": event["cumulative_g"],
            "cost_to_create": event["cost"],
            "contact": contact,
            "dest_was_empty": event["dest_was_empty"],
            "zero_cost_whole_column": event["zero_cost_whole_column"],
            "same_suit_attach": event["same_suit_attach"],
            "king_headed": _anchor_is_king(event),
            "exposed_labels": list(event["revealed_labels"]),
            "source_became_empty": event["source_became_empty"],
            "bonds_delta_on_create": event["bonds_after"] - event["bonds_before"],
            "face_down_delta_on_create": event["face_down_after"] - event["face_down_before"],
            "parking_disorder_before": before["disorder"],
            "parking_disorder_after_create": after["disorder"],
            "removed_action": None,
            "removed_canonical": None,
            "g_removed": None,
            "removal_cost": None,
            "removal_how": None,
            "lifetime_actions": None,
            "stock_deals_crossed": 0,
            "later_obstruction": None,
            "confidence": None,
            "reason": None,
        }
        next_id += 1
        if anchor in open_parks:
            # Should have been closed if it moved. If not, keep the older one
            # and do not overwrite evidence silently.
            park["confidence"] = "LOW"
            park["reason"] = "anchor already had an open placement that this move did not lift"
            _finish_park(park, snapshots, events)
            parks.append(park)
        else:
            open_parks[anchor] = park

    for park in open_parks.values():
        park["removal_how"] = "never_removed"
        park["lifetime_actions"] = trajectory["n_actions"] - park["created_action"]
        park["stock_deals_crossed"] = _deals_between(
            events, park["created_action"], trajectory["n_actions"]
        )
        _finish_park(park, snapshots, events)
        parks.append(park)
    parks.sort(key=lambda item: (item["created_action"], item["id"]))
    return parks


def _contact(event: dict) -> str:
    if event["dest_was_empty"]:
        return "empty"
    if event["same_suit_attach"]:
        return "same_suit"
    if event["mixed_suit_contact"]:
        return "mixed_suit"
    return "other"


def _anchor_is_king(event: dict) -> bool:
    if not event["run_labels"]:
        return False
    # Labels look like KH#A. Rank letter sits before the suit letter.
    notation = event["run_labels"][0].split("#", 1)[0]
    return notation[:-1].upper() == "K"


def _finish_park(park: dict, snapshots: Sequence[dict], events: Sequence[dict]) -> None:
    end = park["removed_action"] if park["removed_action"] is not None else len(snapshots) - 1
    start = park["created_action"]
    disorder_rose = False
    stock_landed = False
    column = park["parking_column"]
    for event in events:
        if not start < event["action_index"] <= end:
            continue
        if event["action_type"] == "deal":
            for landing in event["dealt_landings"]:
                if landing["column"] == column:
                    stock_landed = True
                    if not landing["rank_continues"] or landing["column_was_awkward"]:
                        disorder_rose = True
        after = _column_metrics_at(snapshots, event["action_index"], column)
        before = _column_metrics_at(snapshots, event["action_index"] - 1, column)
        if after["disorder"] > before["disorder"]:
            disorder_rose = True
    park["later_obstruction"] = bool(disorder_rose or stock_landed)
    park["stock_landed_on_park"] = stock_landed
    park["disorder_rose_while_open"] = disorder_rose
    if park.get("confidence") is None:
        confidence, reason = _park_confidence(park)
        park["confidence"] = confidence
        park["reason"] = reason


def _park_confidence(park: dict) -> tuple:
    """Return (confidence, reason). Reasons describe evidence, not proof."""

    if park["same_suit_attach"] or park["contact"] == "same_suit":
        if park["removal_how"] in (None, "never_removed"):
            return "LOW", "same-suit attachment was not later disassembled"
        return "LOW", "same-suit attachment was later disassembled; this is ambiguous and is not asserted as a park"
    if park["zero_cost_whole_column"] and park["contact"] == "empty":
        if park["removal_how"] in (None, "never_removed", "moved_to_foundation", "absorbed_in_place"):
            return "LOW", "zero-cost whole-column relocation onto an empty column; treated as structural transfer unless it is later unpacked"
        return "LOW", "zero-cost whole-column relocation was later moved again; it may be preparation rather than a park"
    if park["removal_how"] in (None, "never_removed"):
        return "LOW", "placement was not subsequently removed, so it is not evidence of a temporary park"
    if park["removal_how"] in ("absorbed_in_place", "moved_to_foundation"):
        return "LOW", "placement was completed into a foundation rather than unpacked"
    lifetime = park["lifetime_actions"] or 0
    crossed = park["stock_deals_crossed"] or 0
    obstructed = bool(park["later_obstruction"])
    if park["contact"] == "mixed_suit" and (crossed >= 1 or lifetime >= 4 or obstructed):
        return (
            "HIGH",
            "mixed-suit placement was later removed after it crossed a stock deal, lasted at least four actions, or sat on a column whose disorder rose",
        )
    if park["contact"] == "empty" and not park["king_headed"] and (crossed >= 1 or lifetime >= 3 or obstructed):
        return (
            "HIGH",
            "non-king material occupied an empty column and was later removed after a stock deal, a delay, or added obstruction",
        )
    if park["contact"] == "empty" and park["king_headed"]:
        return "MEDIUM", "a king was placed on an empty column and later moved; this can be receiver construction or a park"
    if lifetime <= 2 and crossed == 0:
        return "MEDIUM", "short-lived mismatched or empty placement was moved again before the next stock deal; the objective is ambiguous"
    return "MEDIUM", "temporary non-building placement was later moved; more than one Spider objective is consistent with it"


def park_summary(parks: Sequence[dict]) -> dict:
    def count(confidence: str, removed_only: bool = False) -> int:
        return sum(
            1
            for park in parks
            if park["confidence"] == confidence
            and (park["removed_action"] is not None or not removed_only)
            and park["contact"] != "same_suit"
        )

    removed = [park for park in parks if park["removed_action"] is not None and park["contact"] != "same_suit"]
    return {
        "candidates": len(parks),
        "removed_non_same_suit": len(removed),
        "high": count("HIGH"),
        "medium": count("MEDIUM"),
        "low_non_same_suit": count("LOW"),
        "high_removed": sum(1 for park in removed if park["confidence"] == "HIGH"),
        "medium_removed": sum(1 for park in removed if park["confidence"] == "MEDIUM"),
        "zero_cost_whole_column_relocations": sum(1 for park in parks if park["zero_cost_whole_column"]),
        "mixed_suit_removed": sum(1 for park in removed if park["contact"] == "mixed_suit"),
        "empty_occupations_removed": sum(1 for park in removed if park["contact"] == "empty"),
        "note": "Same-suit attaches are stored as LOW disassembly evidence and excluded from these counts.",
    }


def build_workspace(trajectory: dict) -> List[dict]:
    """One episode per continuous interval in which a column is empty."""

    snapshots = trajectory["snapshots"]
    events = trajectory["events"]
    episodes: List[dict] = []
    active: Dict[int, dict] = {}
    next_id = 1

    initial_empty = snapshots[0]["empty_column_numbers"]
    for column in initial_empty:
        active[column] = _start_workspace(
            next_id, column, snapshots[0], acquisition_cost=0, created_by="opening", event=None
        )
        next_id += 1

    for event in events:
        for column in event["columns_emptied"]:
            if column in active:
                continue
            active[column] = _start_workspace(
                next_id,
                column,
                snapshots[event["action_index"]],
                acquisition_cost=event["cost"] if event["src_1"] == column else event["cost"],
                created_by=event["canonical"],
                event=event,
            )
            next_id += 1
        for column in event["columns_filled"]:
            episode = active.pop(column, None)
            if episode is None:
                continue
            _close_workspace(episode, event, snapshots, events)
            episodes.append(episode)

    for episode in active.values():
        episode["filled_action"] = None
        episode["consumed_by"] = None
        episode["consumed_by_stock_deal"] = False
        episode["held_until_end"] = True
        episode["actions_held"] = trajectory["n_actions"] - episode["created_action"]
        episode["stock_deals_crossed_while_empty"] = _deals_between(
            events, episode["created_action"], trajectory["n_actions"]
        )
        episode["reveals_on_use"] = []
        episode["placed_labels"] = []
        episode["immediate_benefit"] = False
        episode["bonds_delta_on_use"] = None
        episode["face_down_delta_on_use"] = None
        episode["immediate_unwind_cost"] = None
        episode["use_cost"] = None
        episodes.append(episode)

    episodes.sort(key=lambda item: (item["created_action"], item["column"], item["id"]))
    _mark_recoveries(episodes)
    return episodes


def _start_workspace(episode_id: int, column: int, snapshot: dict, acquisition_cost: int, created_by: str, event: Optional[dict]) -> dict:
    return {
        "id": f"W{episode_id}",
        "column": column,
        "created_action": snapshot["action_index"],
        "created_g": snapshot["cumulative_g"],
        "created_by": created_by,
        "acquisition_cost": acquisition_cost,
        "phase_created": snapshot["phase"],
        "reveals_on_create": [] if event is None else list(event["revealed_labels"]),
        "filled_action": None,
        "filled_g": None,
        "consumed_by": None,
        "consumed_by_stock_deal": False,
        "held_until_end": False,
        "actions_held": None,
        "stock_deals_crossed_while_empty": 0,
        "placed_labels": [],
        "reveals_on_use": [],
        "king_placed": False,
        "immediate_benefit": False,
        "bonds_delta_on_use": None,
        "face_down_delta_on_use": None,
        "use_cost": None,
        "immediate_unwind_cost": None,
        "recovered": False,
        "recovered_action": None,
        "actions_until_recovery": None,
        "service_components": {},
    }


def _close_workspace(episode: dict, event: dict, snapshots: Sequence[dict], events: Sequence[dict]) -> None:
    episode["filled_action"] = event["action_index"]
    episode["filled_g"] = event["cumulative_g"]
    episode["consumed_by"] = event["canonical"]
    episode["consumed_by_stock_deal"] = event["action_type"] == "deal"
    episode["actions_held"] = event["action_index"] - episode["created_action"]
    episode["stock_deals_crossed_while_empty"] = _deals_between(
        events, episode["created_action"], event["action_index"]
    )
    episode["use_cost"] = event["cost"]
    if event["action_type"] == "deal":
        placed = [
            landing["label"]
            for landing in event["dealt_landings"]
            if landing["column"] == episode["column"]
        ]
        episode["placed_labels"] = placed
        episode["reveals_on_use"] = []
        episode["immediate_benefit"] = False
        episode["bonds_delta_on_use"] = event["bonds_after"] - event["bonds_before"]
        episode["face_down_delta_on_use"] = event["face_down_after"] - event["face_down_before"]
    else:
        episode["placed_labels"] = list(event["run_labels"]) if event["dst_1"] == episode["column"] else []
        episode["reveals_on_use"] = list(event["revealed_labels"])
        episode["king_placed"] = _anchor_is_king(event) and event["dst_1"] == episode["column"]
        episode["bonds_delta_on_use"] = event["bonds_after"] - event["bonds_before"]
        episode["face_down_delta_on_use"] = event["face_down_after"] - event["face_down_before"]
        episode["immediate_benefit"] = bool(
            event["revealed_labels"] or event["source_became_empty"] or episode["bonds_delta_on_use"] > 0
        )
    episode["immediate_unwind_cost"] = _unwind_cost(events, episode)
    episode["service_components"] = {
        "acquisition_cost": episode["acquisition_cost"],
        "actions_held": episode["actions_held"],
        "cards_revealed_on_use": len(episode["reveals_on_use"]),
        "face_down_delta_on_use": episode["face_down_delta_on_use"],
        "bonds_delta_on_use": episode["bonds_delta_on_use"],
        "consumed_by_stock_deal": episode["consumed_by_stock_deal"],
        "immediate_unwind_cost": episode["immediate_unwind_cost"],
        "use_cost": episode["use_cost"],
        "immediate_benefit": episode["immediate_benefit"],
    }


def _unwind_cost(events: Sequence[dict], episode: dict) -> Optional[int]:
    """Cost of the first later move that lifts a placed card off this column.

    This is the direct removal cost only. Later shuttling is not added,
    because that would invent a causal total.
    """

    placed = set(episode["placed_labels"])
    if not placed or episode["filled_action"] is None:
        return None
    for event in events:
        if event["action_index"] <= episode["filled_action"]:
            continue
        if event["action_type"] != "move":
            continue
        if event["src_1"] == episode["column"] and placed.intersection(event["run_labels"]):
            return int(event["cost"])
    return None


def _mark_recoveries(episodes: List[dict]) -> None:
    by_column: Dict[int, List[dict]] = {}
    for episode in episodes:
        by_column.setdefault(episode["column"], []).append(episode)
    for group in by_column.values():
        group.sort(key=lambda item: item["created_action"])
        for current, nxt in zip(group, group[1:]):
            if current["filled_action"] is None:
                continue
            current["recovered"] = True
            current["recovered_action"] = nxt["created_action"]
            current["actions_until_recovery"] = nxt["created_action"] - current["filled_action"]
            current["service_components"]["recovered"] = True
            current["service_components"]["actions_until_recovery"] = current["actions_until_recovery"]


def workspace_summary(episodes: Sequence[dict]) -> dict:
    consumed = [episode for episode in episodes if episode["filled_action"] is not None]
    return {
        "episodes": len(episodes),
        "acquired_by_play": sum(1 for episode in episodes if episode["created_by"] != "opening"),
        "acquisition_cost_sum": sum(int(episode["acquisition_cost"]) for episode in episodes),
        "consumed": len(consumed),
        "consumed_by_stock_deal": sum(1 for episode in consumed if episode["consumed_by_stock_deal"]),
        "consumed_with_reveal": sum(1 for episode in consumed if episode["reveals_on_use"]),
        "consumed_with_immediate_benefit": sum(1 for episode in consumed if episode["immediate_benefit"]),
        "recovered": sum(1 for episode in episodes if episode["recovered"]),
        "held_until_end": sum(1 for episode in episodes if episode["held_until_end"]),
        "positive_unwind_episodes": sum(
            1 for episode in consumed if (episode["immediate_unwind_cost"] or 0) > 0
        ),
        "components_are_separate": True,
        "note": (
            "No single workspace-efficiency scalar is computed. "
            "Under unrestricted deal an empty column cannot survive a stock deal, "
            "so stock_deals_crossed_while_empty is expected to stay 0 and "
            "consumed_by_stock_deal records empties the deal itself spent."
        ),
    }
