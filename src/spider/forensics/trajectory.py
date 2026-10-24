"""Replay a canonical solution into snapshots, events, and card lifecycles.

Physical card identity is the index of the card in the original 104-card
deal order. Duplicate rank/suit cards stay distinct. Engine ``move`` and
``deal`` apply the actions. Undo stacks and Play Lab sessions are not read.
"""

from __future__ import annotations

from collections import Counter
from typing import Dict, List, Optional, Sequence

from spider.cards import Card, rank_str
from spider.engine import SpiderState
from spider.metrics import Action, format_action
from spider.research_actions import face_down_count, pretty_card

from .structure import column_structure, order_change, phase_label, tableau_structure


class ForensicIntegrityError(RuntimeError):
    """A replay invariant failed. Analysis stops rather than interpreting it."""


def physical_identity(cards: Sequence[Card]) -> Dict[int, dict]:
    """Map ``id(card)`` to a stable deal-order identity.

    The map is valid for the card objects in ``cards``. ``SpiderState.clone``
    shares those objects, so one replay from this opening keeps the ids.
    A second ``load_deal`` produces new objects; compare ``physical_index``
    and ``label``, not Python ``id``.
    """

    seen: Counter = Counter()
    out: Dict[int, dict] = {}
    for index, card in enumerate(cards):
        key = (card.suit, int(card.rank))
        seen[key] += 1
        copy_n = seen[key]
        suffix = {1: "A", 2: "B"}.get(copy_n, str(copy_n))
        out[id(card)] = {
            "physical_index": index,
            "label": f"{rank_str(card.rank)}{card.suit.upper()}#{suffix}",
            "notation": pretty_card(card),
            "suit": card.suit,
            "rank": int(card.rank),
            "duplicate_index": copy_n,
        }
    return out


def _original_locations(state: SpiderState, identity: Dict[int, dict]) -> None:
    """Fill original zone fields. Deal order already supplied the index."""

    for column_index, column in enumerate(state.columns):
        for depth, card in enumerate(column.face_down):
            identity[id(card)]["original"] = {
                "zone": "face_down",
                "column": column_index + 1,
                "depth": depth,
                "deal_round": None,
            }
        for depth, card in enumerate(column.face_up):
            identity[id(card)]["original"] = {
                "zone": "face_up",
                "column": column_index + 1,
                "depth": depth,
                "deal_round": None,
            }
    stock = state.stock
    width = 10
    for stock_index, card in enumerate(stock):
        from_end = len(stock) - 1 - stock_index
        deal_round = from_end // width + 1
        identity[id(card)]["original"] = {
            "zone": "stock",
            "column": (stock_index % width) + 1,
            "depth": stock_index,
            "deal_round": deal_round,
        }


def _new_lifecycle(info: dict) -> dict:
    original = info["original"]
    exposed = 0 if original["zone"] == "face_up" else None
    return {
        "physical_index": info["physical_index"],
        "label": info["label"],
        "notation": info["notation"],
        "suit": info["suit"],
        "rank": info["rank"],
        "duplicate_index": info["duplicate_index"],
        "original": original,
        "first_exposed_action": exposed,
        "foundation_action": None,
        "handle_count": 0,
        "positive_cost_handles": 0,
        "zero_cost_handles": 0,
        "rehandles": 0,
        "positive_cost_rehandles": 0,
        "transfers": [],
        "placements": [],
    }


def _face_down_ids(state: SpiderState) -> set:
    return {id(card) for column in state.columns for card in column.face_down}


def _foundation_ids(state: SpiderState) -> set:
    return {id(card) for sequence in state.foundations for card in sequence}


def _exclusive_class(event: dict) -> str:
    """Priority partition of one action's MobilityWare cost.

    A move can deserve several tags. The exclusive class exists so class
    costs sum to the route total. It is an accounting bucket, not a cause.
    """

    if event["action_type"] == "deal":
        return "STOCK_DEAL"
    if event["cost"] == 0:
        return "ZERO_COST_WHOLE_COLUMN"
    if event["removed_foundation"]:
        return "FOUNDATION_TRIGGER"
    if event["revealed_labels"]:
        return "REVEAL"
    if event["same_suit_attach"]:
        return "SAME_SUIT_MERGE"
    if event["dest_was_empty"]:
        return "EMPTY_PLACEMENT"
    if event["mixed_suit_contact"]:
        return "MIXED_SUIT_PLACEMENT"
    return "OTHER_POSITIVE"


def _tags(event: dict) -> List[str]:
    tags = []
    if event["action_type"] == "deal":
        tags.append("STOCK_DEAL")
        if event["dealt_onto_awkward"]:
            tags.append("STOCK_ON_AWKWARD")
        return tags
    if event["cost"] == 0:
        tags.append("ZERO_COST_WHOLE_COLUMN")
    if event["removed_foundation"]:
        tags.append("FOUNDATION_TRIGGER")
    if event["revealed_labels"]:
        tags.append("REVEAL")
    if event["same_suit_attach"]:
        tags.append("SAME_SUIT_ATTACH")
    if event["dest_was_empty"]:
        tags.append("ONTO_EMPTY")
    if event["mixed_suit_contact"]:
        tags.append("MIXED_SUIT_CONTACT")
    if event["source_became_empty"] or event["columns_emptied"]:
        tags.append("EMPTY_CREATED")
    if event["layer_unpack"]:
        tags.append("LAYER_UNPACK")
    if event["rehandle_move"]:
        tags.append("REHANDLE")
    if not tags:
        tags.append("OTHER")
    return tags


def _snapshot(
    state: SpiderState,
    *,
    action_index: int,
    action_type: str,
    canonical: Optional[str],
    incremental: int,
    cumulative_g: int,
    stock_deals: int,
    state_hash: str,
    symmetry_hash: Optional[str],
    previous_columns: Optional[List[dict]],
    path_columns: List[dict],
) -> dict:
    tableau = tableau_structure(state)
    columns = []
    for column, path in zip(tableau["columns"], path_columns):
        prior = None if previous_columns is None else previous_columns[column["column"] - 1]
        enriched = dict(column)
        enriched["order_change"] = order_change(prior, column)
        enriched["path_dependent"] = dict(path)
        columns.append(enriched)
    tableau = dict(tableau)
    tableau["columns"] = columns
    return {
        "action_index": action_index,
        "action_type": action_type,
        "canonical_action": canonical,
        "incremental_mw": incremental,
        "cumulative_g": cumulative_g,
        "stock_deals_completed": stock_deals,
        "stock_rows_remaining": tableau["stock_rows_remaining"],
        "foundations_completed": tableau["foundations_completed"],
        "face_down_remaining": tableau["face_down_remaining"],
        "empty_columns": tableau["empty_columns"],
        "empty_column_numbers": tableau["empty_column_numbers"],
        "phase": phase_label(stock_deals, tableau["stock_rows_remaining"]),
        "horizon_roles": [],
        "state_hash": state_hash,
        "post_stock_symmetry_hash": symmetry_hash,
        "solved": state.is_solved(),
        "columns": columns,
        "tableau": {key: value for key, value in tableau.items() if key != "columns"},
    }


def _empty_path(n_columns: int) -> List[dict]:
    return [
        {
            "stock_landings_while_awkward": 0,
            "unpack_moves": 0,
            "cards_handled_2plus_present": 0,
        }
        for _ in range(n_columns)
    ]


def _cards_handled_here(state: SpiderState, lives: Dict[int, dict], column_index: int) -> int:
    column = state.columns[column_index]
    count = 0
    for card in list(column.face_down) + list(column.face_up):
        if lives[id(card)]["handle_count"] >= 2:
            count += 1
    return count


def replay_trajectory(
    opening: SpiderState,
    cards: Sequence[Card],
    actions: Sequence[Action],
    *,
    label: str,
    focus_column: Optional[int] = None,
    require_solved: bool = True,
) -> dict:
    """Replay ``actions`` from ``opening`` and return JSON-ready evidence.

    ``opening`` is cloned. ``cards`` must be the same objects ``opening``
    was built from, in deal order.
    """

    from spider.packed_state import pack_post_stock_symmetry_state, pack_state
    import hashlib

    def _hash(blob: bytes) -> str:
        return hashlib.sha256(blob).hexdigest()

    if focus_column is not None and not 1 <= int(focus_column) <= len(opening.columns):
        raise ForensicIntegrityError(f"focus column {focus_column} is outside 1..{len(opening.columns)}")

    identity = physical_identity(cards)
    if len(identity) != len(cards):
        raise ForensicIntegrityError("physical identity collided; card objects are not unique")
    _original_locations(opening, identity)
    lives = {card_id: _new_lifecycle(info) for card_id, info in identity.items()}

    state = opening.clone()
    snapshots: List[dict] = []
    events: List[dict] = []
    path = _empty_path(len(state.columns))
    cumulative = 0
    deals = 0
    positive_rehandle_events = 0
    zero_cost_card_moves = 0
    handling_events = 0

    def state_hashes():
        ordered = _hash(pack_state(state))
        symmetry = None
        if not state.stock:
            symmetry = _hash(pack_post_stock_symmetry_state(state))
        return ordered, symmetry

    ordered_hash, symmetry_hash = state_hashes()
    for column_index in range(len(state.columns)):
        path[column_index]["cards_handled_2plus_present"] = _cards_handled_here(state, lives, column_index)
    snapshots.append(
        _snapshot(
            state,
            action_index=0,
            action_type="opening",
            canonical=None,
            incremental=0,
            cumulative_g=0,
            stock_deals=0,
            state_hash=ordered_hash,
            symmetry_hash=symmetry_hash,
            previous_columns=None,
            path_columns=path,
        )
    )

    for action_number, action in enumerate(actions, start=1):
        before_columns = snapshots[-1]["columns"]
        bonds_before = snapshots[-1]["tableau"]["same_suit_bonds"]
        face_down_before = face_down_count(state)
        empty_before = snapshots[-1]["empty_columns"]
        debt_before = snapshots[-1]["tableau"]["experimental_debt_sum"]
        fd_ids = _face_down_ids(state)
        found_ids = _foundation_ids(state)
        deals_before = deals

        revealed_labels: List[str] = []
        foundation_labels: List[str] = []
        dealt_landings: List[dict] = []
        run_labels: List[str] = []
        run_ids: List[int] = []
        src = dst = size = None
        dest_was_empty = False
        dest_top_label = None
        dest_top_notation = None
        same_suit_attach = False
        mixed_suit_contact = False
        source_face_up_before = 0
        source_face_down_before = 0
        source_layers_before = 0
        source_suit_before = 0
        source_rank_before = 0
        source_debt_before = 0
        dest_debt_before = 0
        layer_unpack = False
        dealt_onto_awkward = False

        if action == ("deal",):
            awkward = []
            for index, column in enumerate(state.columns):
                metrics = before_columns[index]
                awkward.append(metrics["disorder"] > 0 or metrics["component_layers"] > 0)
            chunk = list(state.stock[-10:])
            cost = state.deal()
            deals += 1
            for index, card in enumerate(chunk):
                previous = before_columns[index]
                previous_top = previous["top_card"]
                rank_continues = False
                same_suit = False
                if previous_top and not previous["empty"]:
                    # The dealt card sits on the previous exposed card.
                    rank_continues = previous["top_rank"] == card.rank + 1
                    same_suit = previous["top_suit"] == card.suit and rank_continues
                landing = {
                    "column": index + 1,
                    "label": identity[id(card)]["label"],
                    "notation": pretty_card(card),
                    "previous_top": previous_top,
                    "previous_empty": previous["empty"],
                    "rank_continues": rank_continues,
                    "same_suit": same_suit,
                    "column_was_awkward": awkward[index],
                }
                dealt_landings.append(landing)
                if awkward[index] and not previous["empty"]:
                    path[index]["stock_landings_while_awkward"] += 1
                    dealt_onto_awkward = True
                life = lives[id(card)]
                if life["first_exposed_action"] is None:
                    life["first_exposed_action"] = action_number
                life["placements"].append(
                    {
                        "kind": "stock_deal",
                        "action": action_number,
                        "column": index + 1,
                        "cost": cost,
                        "left_action": None,
                    }
                )
            canonical = format_action(action)
            action_type = "deal"
        else:
            src, dst, size = action
            source = state.columns[src]
            dest = state.columns[dst]
            source_face_up_before = len(source.face_up)
            source_face_down_before = len(source.face_down)
            source_metrics = before_columns[src]
            dest_metrics = before_columns[dst]
            source_layers_before = source_metrics["component_layers"]
            source_suit_before = source_metrics["suit_boundaries"]
            source_rank_before = source_metrics["rank_discontinuities"]
            source_debt_before = source_metrics["experimental_debt_score"]
            dest_debt_before = dest_metrics["experimental_debt_score"]
            dest_was_empty = dest.is_empty()
            top = dest.top()
            if top is not None:
                dest_top_label = identity[id(top)]["label"]
                dest_top_notation = pretty_card(top)
            run = list(source.face_up[-size:])
            run_ids = [id(card) for card in run]
            run_labels = [identity[card_id]["label"] for card_id in run_ids]
            if top is not None and top.rank == run[0].rank + 1:
                if top.suit == run[0].suit:
                    same_suit_attach = True
                else:
                    mixed_suit_contact = True
            layer_unpack = source_layers_before >= 1 and size < source_face_up_before
            prior_handles = [lives[card_id]["handle_count"] for card_id in run_ids]
            rehandle_move_preview = all(count >= 1 for count in prior_handles)
            cost = state.move(src, dst, size)
            action_type = "move"
            canonical = format_action(action)
            for card_id, already in zip(run_ids, prior_handles):
                life = lives[card_id]
                life["handle_count"] += 1
                handling_events += 1
                if cost == 0:
                    life["zero_cost_handles"] += 1
                    zero_cost_card_moves += 1
                else:
                    life["positive_cost_handles"] += 1
                if already >= 1:
                    life["rehandles"] += 1
                    if cost > 0:
                        life["positive_cost_rehandles"] += 1
                        positive_rehandle_events += 1
                life["transfers"].append(
                    {
                        "action_index": action_number,
                        "src": src + 1,
                        "dst": dst + 1,
                        "k": size,
                        "cost": cost,
                        "zero_cost": cost == 0,
                        "run_length": size,
                        "anchor": card_id == run_ids[0],
                        "rehandle": already >= 1,
                    }
                )
                _close_placement(life, action_number, dst + 1)
                life["placements"].append(
                    {
                        "kind": "tableau",
                        "action": action_number,
                        "column": dst + 1,
                        "cost": cost,
                        "left_action": None,
                    }
                )
            if layer_unpack:
                path[src]["unpack_moves"] += 1
            rehandle_move = bool(rehandle_move_preview and cost > 0 and not same_suit_attach)
        if action == ("deal",):
            rehandle_move = False

        new_fd = _face_down_ids(state)
        for card_id in fd_ids - new_fd:
            life = lives[card_id]
            if life["first_exposed_action"] is None:
                life["first_exposed_action"] = action_number
            revealed_labels.append(life["label"])
        new_found = _foundation_ids(state)
        for card_id in new_found - found_ids:
            life = lives[card_id]
            life["foundation_action"] = action_number
            _close_placement(life, action_number, None)
            foundation_labels.append(life["label"])
        event = {
            "action_index": action_number,
            "action_type": action_type,
            "canonical": canonical,
            "src": None if src is None else src,
            "dst": None if dst is None else dst,
            "src_1": None if src is None else src + 1,
            "dst_1": None if dst is None else dst + 1,
            "k": size,
            "cost": cost,
            "cumulative_g": cumulative + cost,
            "revealed_labels": revealed_labels,
            "foundation_labels": foundation_labels,
            "removed_foundation": bool(foundation_labels),
            "foundations_after": len(state.foundations),
            "dest_was_empty": dest_was_empty,
            "source_face_up_before": source_face_up_before,
            "source_face_down_before": source_face_down_before,
            "dest_top_before_label": dest_top_label,
            "dest_top_before_notation": dest_top_notation,
            "run_labels": run_labels,
            "anchor_label": run_labels[0] if run_labels else None,
            "same_suit_attach": same_suit_attach,
            "mixed_suit_contact": mixed_suit_contact,
            "zero_cost_whole_column": action_type == "move" and cost == 0,
            "layer_unpack": layer_unpack,
            "rehandle_move": rehandle_move,
            "source_component_layers_before": source_layers_before,
            "source_suit_boundaries_before": source_suit_before,
            "source_rank_discontinuities_before": source_rank_before,
            "source_debt_before": source_debt_before,
            "dest_debt_before": dest_debt_before,
            "bonds_before": bonds_before,
            "face_down_before": face_down_before,
            "empty_before": empty_before,
            "debt_sum_before": debt_before,
            "stock_deals_before": deals_before,
            "stock_deals_after": deals,
            "dealt_landings": dealt_landings,
            "dealt_onto_awkward": dealt_onto_awkward,
            "focus_debt_before": _focus_score(before_columns, focus_column),
        }
        cumulative += cost
        for column_index in range(len(state.columns)):
            path[column_index]["cards_handled_2plus_present"] = _cards_handled_here(
                state, lives, column_index
            )
        ordered_hash, symmetry_hash = state_hashes()
        # path is mutated in place; snapshot must copy the dicts. _snapshot copies path fields.
        snap = _snapshot(
            state,
            action_index=action_number,
            action_type=action_type,
            canonical=canonical,
            incremental=cost,
            cumulative_g=cumulative,
            stock_deals=deals,
            state_hash=ordered_hash,
            symmetry_hash=symmetry_hash,
            previous_columns=before_columns,
            path_columns=path,
        )
        snapshots.append(snap)
        event["bonds_after"] = snap["tableau"]["same_suit_bonds"]
        event["face_down_after"] = snap["face_down_remaining"]
        event["empty_after"] = snap["empty_columns"]
        event["debt_sum_after"] = snap["tableau"]["experimental_debt_sum"]
        event["focus_debt_after"] = _focus_score(snap["columns"], focus_column)
        event["focus_disorder_before"] = _focus_disorder(before_columns, focus_column)
        event["focus_disorder_after"] = _focus_disorder(snap["columns"], focus_column)
        event["source_became_empty"] = bool(
            src is not None and before_columns[src]["empty"] is False and snap["columns"][src]["empty"]
        )
        previous_empty = {column["column"] for column in before_columns if column["empty"]}
        current_empty = set(snap["empty_column_numbers"])
        event["columns_emptied"] = sorted(current_empty - previous_empty)
        event["columns_filled"] = sorted(previous_empty - current_empty)
        event["dest_debt_after"] = None if dst is None else snap["columns"][dst]["experimental_debt_score"]
        event["source_debt_after"] = None if src is None else snap["columns"][src]["experimental_debt_score"]
        event["exclusive_class"] = _exclusive_class(event)
        event["tags"] = _tags(event)
        events.append(event)

    _assign_horizons(snapshots, events)
    if require_solved:
        final = snapshots[-1]
        if not final["solved"]:
            raise ForensicIntegrityError(
                f"{label} is not solved (foundations={final['foundations_completed']}, "
                f"stock_rows={final['stock_rows_remaining']})"
            )
        if final["foundations_completed"] != 8 or final["stock_rows_remaining"] != 0:
            raise ForensicIntegrityError(
                f"{label} solved-flag mismatch foundations={final['foundations_completed']} "
                f"stock_rows={final['stock_rows_remaining']}"
            )
    if snapshots[-1]["cumulative_g"] != cumulative:
        raise ForensicIntegrityError("cumulative MW drifted from the last snapshot")
    class_cost = _class_costs(events)
    if sum(class_cost.values()) != cumulative:
        raise ForensicIntegrityError(
            f"exclusive class costs {sum(class_cost.values())} != cumulative {cumulative}"
        )
    for snapshot in snapshots:
        column_face_down = sum(column["face_down"] for column in snapshot["columns"])
        if column_face_down != snapshot["face_down_remaining"]:
            raise ForensicIntegrityError(
                f"face-down mismatch at action {snapshot['action_index']}"
            )

    lifecycles = sorted(lives.values(), key=lambda item: item["physical_index"])
    # Placements that are still open have no left_action. That is evidence.
    return {
        "label": label,
        "focus_column": focus_column,
        "n_actions": len(actions),
        "mobilityware_moves": cumulative,
        "solved": snapshots[-1]["solved"],
        "foundations_completed": snapshots[-1]["foundations_completed"],
        "stock_rows_remaining": snapshots[-1]["stock_rows_remaining"],
        "snapshots": snapshots,
        "events": events,
        "card_lifecycles": lifecycles,
        "card_aggregates": _card_aggregates(lifecycles, handling_events, positive_rehandle_events, zero_cost_card_moves),
        "cost_classes": class_cost,
        "series": _series(snapshots, events, focus_column),
        "horizons": _horizon_records(snapshots, events, lifecycles),
    }


def _close_placement(life: dict, action: int, new_column: Optional[int]) -> None:
    for placement in reversed(life["placements"]):
        if placement["left_action"] is None:
            placement["left_action"] = action
            placement["left_to_column"] = new_column
            return


def _focus_score(columns: Sequence[dict], focus_column: Optional[int]) -> Optional[int]:
    if focus_column is None:
        return None
    return int(columns[focus_column - 1]["experimental_debt_score"])


def _focus_disorder(columns: Sequence[dict], focus_column: Optional[int]) -> Optional[int]:
    if focus_column is None:
        return None
    return int(columns[focus_column - 1]["disorder"])


def _assign_horizons(snapshots: List[dict], events: List[dict]) -> None:
    snapshots[0]["horizon_roles"].append("opening")
    for event, before, after in zip(events, snapshots, snapshots[1:]):
        if event["action_type"] != "deal":
            continue
        deal_n = event["stock_deals_after"]
        _add_role(before, f"pre-SD{deal_n}")
        _add_role(after, f"post-SD{deal_n}")
        if after["stock_rows_remaining"] == 0:
            _add_role(after, "stock-empty-endgame")
    if snapshots[-1]["solved"]:
        _add_role(snapshots[-1], "solved")


def _add_role(snapshot: dict, role: str) -> None:
    if role not in snapshot["horizon_roles"]:
        snapshot["horizon_roles"].append(role)


def _class_costs(events: Sequence[dict]) -> Dict[str, int]:
    costs: Dict[str, int] = {}
    for event in events:
        costs[event["exclusive_class"]] = costs.get(event["exclusive_class"], 0) + int(event["cost"])
    return dict(sorted(costs.items()))


def _card_aggregates(lives: Sequence[dict], handling_events: int, positive_rehandle_events: int, zero_cost_card_moves: int) -> dict:
    handled = [life for life in lives if life["handle_count"] > 0]
    temporary = []
    for life in lives:
        for placement in life["placements"]:
            if placement["kind"] != "tableau":
                continue
            left = placement["left_action"]
            if left is None or life["foundation_action"] == left:
                continue
            temporary.append(
                {
                    "label": life["label"],
                    "column": placement["column"],
                    "placed_action": placement["action"],
                    "left_action": left,
                    "lifetime_actions": left - placement["action"],
                    "cost": placement["cost"],
                }
            )
    temporary.sort(key=lambda item: (-item["lifetime_actions"], item["placed_action"], item["label"]))
    return {
        "total_card_handling_events": handling_events,
        "unique_cards_explicitly_handled": len(handled),
        "cards_moved_2plus": sum(1 for life in lives if life["handle_count"] >= 2),
        "cards_moved_3plus": sum(1 for life in lives if life["handle_count"] >= 3),
        "cards_moved_4plus": sum(1 for life in lives if life["handle_count"] >= 4),
        "positive_cost_rehandle_card_events": positive_rehandle_events,
        "zero_cost_card_moves": zero_cost_card_moves,
        "max_handles_on_one_card": max((life["handle_count"] for life in lives), default=0),
        "most_handled": [
            {"label": life["label"], "handle_count": life["handle_count"], "positive_cost_rehandles": life["positive_cost_rehandles"]}
            for life in sorted(lives, key=lambda item: (-item["handle_count"], item["physical_index"]))[:8]
            if life["handle_count"] > 0
        ],
        "longest_lived_temporary_placements": temporary[:8],
        "definition": {
            "handling_event": "one physical card participating in one explicit tableau transfer",
            "rehandle": "a tableau transfer after that card has already been tableau-transferred once",
            "stock_deal_placement": "recorded on the card but not counted as a handle",
            "counts_are_not_causes": True,
        },
    }


def _series(snapshots: Sequence[dict], events: Sequence[dict], focus_column: Optional[int]) -> dict:
    card_events = [0]
    running_cards = 0
    for event in events:
        if "REHANDLE" in event["tags"]:
            running_cards += len(event["run_labels"])
        card_events.append(running_cards)
    return {
        "action_index": [snapshot["action_index"] for snapshot in snapshots],
        "cumulative_g": [snapshot["cumulative_g"] for snapshot in snapshots],
        "face_down_remaining": [snapshot["face_down_remaining"] for snapshot in snapshots],
        "same_suit_bonds": [snapshot["tableau"]["same_suit_bonds"] for snapshot in snapshots],
        "run_compression": [snapshot["tableau"]["run_compression"] for snapshot in snapshots],
        "experimental_debt_sum": [snapshot["tableau"]["experimental_debt_sum"] for snapshot in snapshots],
        "rehandle_tagged_card_events": card_events,
        "focus_column_experimental_debt": [
            None if focus_column is None else snapshot["columns"][focus_column - 1]["experimental_debt_score"]
            for snapshot in snapshots
        ],
        "focus_column_disorder": [
            None if focus_column is None else snapshot["columns"][focus_column - 1]["disorder"]
            for snapshot in snapshots
        ],
        "empty_columns": [snapshot["empty_columns"] for snapshot in snapshots],
    }


def _horizon_records(snapshots: Sequence[dict], events: Sequence[dict], lives: Sequence[dict]) -> List[dict]:
    records = []
    seen = set()
    for snapshot in snapshots:
        for role in snapshot["horizon_roles"]:
            if role in seen:
                continue
            seen.add(role)
            records.append(_horizon_from_snapshot(snapshot, events, lives, role))
    order = {"opening": -1, "solved": 10_000, "stock-empty-endgame": 9_000}
    records.sort(key=lambda item: (order.get(item["role"], _role_sort(item["role"])), item["action_index"]))
    return records


def _role_sort(role: str) -> int:
    if role.startswith("pre-SD"):
        return int(role[6:]) * 2
    if role.startswith("post-SD"):
        return int(role[7:]) * 2 + 1
    return 5_000


def _horizon_from_snapshot(snapshot: dict, events: Sequence[dict], lives: Sequence[dict], role: str) -> dict:
    index = snapshot["action_index"]
    handled_2 = sum(1 for life in lives if _handles_by(life, index) >= 2)
    handled_3 = sum(1 for life in lives if _handles_by(life, index) >= 3)
    positive_rehandles = 0
    for life in lives:
        for transfer in life["transfers"]:
            if transfer["action_index"] <= index and transfer["rehandle"] and transfer["cost"] > 0:
                positive_rehandles += 1
    return {
        "role": role,
        "action_index": index,
        "canonical_action": snapshot["canonical_action"],
        "phase": snapshot["phase"],
        "cumulative_g": snapshot["cumulative_g"],
        "foundations_completed": snapshot["foundations_completed"],
        "face_down_remaining": snapshot["face_down_remaining"],
        "empty_columns": snapshot["empty_columns"],
        "empty_column_numbers": list(snapshot["empty_column_numbers"]),
        "same_suit_bonds": snapshot["tableau"]["same_suit_bonds"],
        "run_compression": snapshot["tableau"]["run_compression"],
        "exposed_movable_cards": snapshot["tableau"]["exposed_movable_cards"],
        "legal_tableau_moves": snapshot["tableau"]["legal_tableau_moves"],
        "legal_same_suit_attaches": snapshot["tableau"]["legal_same_suit_attaches"],
        "legal_reveal_moves": snapshot["tableau"]["legal_reveal_moves"],
        "legal_reveal_columns": snapshot["tableau"]["legal_reveal_columns"],
        "mixed_suit_parking_columns": snapshot["tableau"]["mixed_suit_parking_columns"],
        "experimental_debt_sum": snapshot["tableau"]["experimental_debt_sum"],
        "experimental_debt_argmax_column": snapshot["tableau"]["experimental_debt_argmax_column"],
        "readiness_n_ready": snapshot["tableau"]["readiness_n_ready"],
        "readiness_nearest_horizon": snapshot["tableau"]["readiness_nearest_horizon"],
        "cards_moved_2plus_to_date": handled_2,
        "cards_moved_3plus_to_date": handled_3,
        "positive_cost_rehandle_card_events_to_date": positive_rehandles,
        "column_experimental_debt": [column["experimental_debt_score"] for column in snapshot["columns"]],
        "column_disorder": [column["disorder"] for column in snapshot["columns"]],
        "column_suit_boundaries": [column["suit_boundaries"] for column in snapshot["columns"]],
        "column_rank_discontinuities": [column["rank_discontinuities"] for column in snapshot["columns"]],
        "column_buried_face_up": [column["buried_face_up"] for column in snapshot["columns"]],
        "column_face_down": [column["face_down"] for column in snapshot["columns"]],
        "column_workspace_class": [column["workspace_class"] for column in snapshot["columns"]],
        "state_hash": snapshot["state_hash"],
        "post_stock_symmetry_hash": snapshot["post_stock_symmetry_hash"],
    }


def _handles_by(life: dict, action_index: int) -> int:
    return sum(1 for transfer in life["transfers"] if transfer["action_index"] <= action_index)
