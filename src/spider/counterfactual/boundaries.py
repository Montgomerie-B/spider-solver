"""Stock-boundary measurements and in-search watches.

Cheap signals are collected on every generated state. Full column metrics
are computed only for the few states retained as checkpoints.
"""

from __future__ import annotations

from typing import Optional, Sequence

from spider.engine import SpiderState
from spider.forensics.structure import tableau_structure
from spider.metrics import Action, format_action
from spider.research_actions import apply_action, face_down_count

from .policies import focus_suit_boundaries, same_suit_bonds
from .suffixes import cheapest_hit


def rehandle_card_events(state: SpiderState, actions: Sequence[Action]) -> int:
    """Positive-cost tableau card-events for a card that already moved once.

    Counted from ``state`` along ``actions``. Deal does not mark a card moved.
    """

    seen: dict = {}
    trial = state.clone()
    events = 0
    for action in actions:
        if action == ("deal",):
            apply_action(trial, action)
            continue
        src, _dst, k = action
        moving = list(trial.columns[src].face_up[-k:])
        cost = apply_action(trial, action)
        for card in moving:
            prior = seen.get(id(card), 0)
            if prior >= 1 and cost > 0:
                events += 1
            seen[id(card)] = prior + 1
    return events


def measure_state(state: SpiderState, *, g: int, root_g: int, focus_index: int) -> dict:
    tableau = tableau_structure(state, with_readiness=False)
    debt = [int(column["experimental_debt_score"]) for column in tableau["columns"]]
    focus = tableau["columns"][focus_index]
    return {
        "cumulative_g": int(g),
        "g_since_root": int(g) - int(root_g),
        "face_down": int(tableau["face_down_remaining"]),
        "foundations": int(tableau["foundations_completed"]),
        "same_suit_bonds": int(tableau["same_suit_bonds"]),
        "accessible_movable_runs": int(tableau["exposed_movable_blocks"]),
        "exposed_movable_cards": int(tableau["exposed_movable_cards"]),
        "empty_columns": int(tableau["empty_columns"]),
        "empty_column_numbers": list(tableau["empty_column_numbers"]),
        "focus_disorder": int(focus["disorder"]),
        "focus_suit_boundaries": int(focus["suit_boundaries"]),
        "focus_debt": int(focus["experimental_debt_score"]),
        "debt_vector": debt,
        "debt_sum": int(sum(debt)),
        "deal_legal": bool(state.can_deal()),
        "stock_rows": int(tableau["stock_rows_remaining"]),
        "stock_cards": len(state.stock),
        "unrestricted_deal": True,
    }


def debt_transfer(before: Sequence[int], after: Sequence[int], focus_index: int) -> dict:
    focus_delta = int(after[focus_index]) - int(before[focus_index])
    increased = []
    for index, (old, new) in enumerate(zip(before, after)):
        if index == focus_index:
            continue
        if int(new) > int(old):
            increased.append({"column": index + 1, "delta": int(new) - int(old)})
    watched = []
    for column in (7, 8):
        index = column - 1
        if index < len(after):
            watched.append(
                {
                    "column": column,
                    "before": int(before[index]),
                    "after": int(after[index]),
                    "delta": int(after[index]) - int(before[index]),
                }
            )
    moved = focus_delta < 0 and any(item["delta"] > 0 for item in increased)
    return {
        "focus_debt_delta": focus_delta,
        "columns_that_increased": increased,
        "columns_7_and_8": watched,
        "focus_fell_while_another_column_rose": moved,
        "note": (
            "Observed debt-vector change from the root to this state. "
            "A rise in another column is not by itself a terminal-cost result."
        ),
    }


def original_next_boundary(state: SpiderState, suffix: Sequence[Action], *, root_g: int, focus_index: int) -> dict:
    """Replay the known suffix until the stock shrinks by one row."""

    root_stock = len(state.stock)
    root_debt = measure_state(state, g=root_g, root_g=root_g, focus_index=focus_index)["debt_vector"]
    trial = state.clone()
    g = int(root_g)
    taken: list = []
    for action in suffix:
        g += apply_action(trial, action)
        taken.append(action)
        if len(trial.stock) <= root_stock - 10:
            metrics = measure_state(trial, g=g, root_g=root_g, focus_index=focus_index)
            metrics["actions"] = [format_action(item) for item in taken]
            metrics["action_count"] = len(taken)
            metrics["rehandle_card_events"] = rehandle_card_events(state, taken)
            metrics["debt_transfer_from_root"] = debt_transfer(root_debt, metrics["debt_vector"], focus_index)
            metrics["kind"] = "original_suffix_next_stock_boundary"
            return metrics
    return {
        "kind": "original_suffix_never_dealt",
        "action_count": len(suffix),
        "cumulative_g": g,
    }


class SearchWatch:
    """Record suffix hits and the next stock boundary without steering moves."""

    def __init__(
        self,
        *,
        root_stock_len: int,
        origin_g: int,
        focus_index: int,
        baseline_index: Optional[dict] = None,
        reference_index: Optional[dict] = None,
    ) -> None:
        self.root_stock_len = int(root_stock_len)
        self.origin_g = int(origin_g)
        self.focus_index = int(focus_index)
        self.baseline_index = baseline_index or {}
        self.reference_index = reference_index or {}
        self.baseline_hit = None
        self.reference_hit = None
        self.earliest = None
        self.best = None
        self.max_bonds = 0
        self.stock_empty = None
        self.public_checkpoints = []

    def __call__(self, kr, state: SpiderState, g: int, node: int) -> None:
        store = kr.nodes[node].store
        self._consider_hit(self.baseline_index, store, g, node, baseline=True)
        self._consider_hit(self.reference_index, store, g, node, baseline=False)
        bonds = same_suit_bonds(state)
        if bonds > self.max_bonds:
            self.max_bonds = bonds
        if len(state.stock) == 0 and not state.is_solved():
            if self.stock_empty is None or int(g) < int(self.stock_empty["g"]):
                self.stock_empty = {"g": int(g), "node": int(node), "store": store}
        if len(state.stock) != self.root_stock_len - 10:
            return
        foundations = len(state.foundations)
        face_down = face_down_count(state)
        bounds = focus_suit_boundaries(state, self.focus_index)
        score = (-foundations, face_down, bounds, -bonds, int(g))
        if self.earliest is None or int(g) < self.earliest["g"]:
            self.earliest = {"g": int(g), "node": int(node)}
        if self.best is None or score < self.best["score"]:
            self.best = {"score": score, "g": int(g), "node": int(node)}

    def _consider_hit(self, index: dict, store: bytes, g: int, node: int, *, baseline: bool) -> None:
        record = cheapest_hit(index, store, int(g))
        if record is None:
            return
        slot = self.baseline_hit if baseline else self.reference_hit
        if slot is not None and int(g) >= int(slot["g"]):
            return
        saved = {
            "g": int(g),
            "node": int(node),
            "catalog_g": int(record["g"]),
            "suffix": list(record["suffix"]),
            "store": store,
            "source": "baseline-185" if baseline else "reference-172",
            "used_to_choose_candidates": False,
        }
        if baseline:
            self.baseline_hit = saved
        else:
            self.reference_hit = saved

    def finish(self, kernel, root_state: SpiderState) -> None:
        root_debt = measure_state(
            root_state, g=self.origin_g, root_g=self.origin_g, focus_index=self.focus_index
        )["debt_vector"]
        self.public_checkpoints = []
        for label, slot in (("earliest_stock_boundary", self.earliest), ("best_scored_stock_boundary", self.best)):
            if slot is None:
                continue
            path = list(kernel.reconstruct(int(slot["node"])))
            self.public_checkpoints.append(
                self._boundary_checkpoint(label, path, root_state, root_debt)
            )
        for hit in (self.baseline_hit, self.reference_hit):
            if hit is None:
                continue
            path = list(kernel.reconstruct(int(hit["node"])))
            hit["path"] = path
            hit["path_canonical"] = [format_action(action) for action in path]
            hit["saving_vs_catalog_g"] = int(hit["catalog_g"]) - int(hit["g"])
        if self.stock_empty is not None:
            path = list(kernel.reconstruct(int(self.stock_empty["node"])))
            self.stock_empty["path"] = path
            self.stock_empty["path_canonical"] = [format_action(action) for action in path]

    def _boundary_checkpoint(self, label: str, path: Sequence[Action], root_state: SpiderState, root_debt: Sequence[int]) -> dict:
        trial = root_state.clone()
        g = self.origin_g
        for action in path:
            g += apply_action(trial, action)
        metrics = measure_state(trial, g=g, root_g=self.origin_g, focus_index=self.focus_index)
        tableau_moves = sum(1 for action in path if action != ("deal",))
        metrics.update(
            {
                "label": label,
                "actions": [format_action(action) for action in path],
                "action_count": len(path),
                "tableau_moves_on_path": tableau_moves,
                "immediate_deal": tableau_moves == 0 and any(action == ("deal",) for action in path),
                "rehandle_card_events": rehandle_card_events(root_state, path),
                "debt_transfer_from_root": debt_transfer(root_debt, metrics["debt_vector"], self.focus_index),
            }
        )
        return metrics

    def summary(self) -> dict:
        def hit_view(hit):
            if hit is None:
                return None
            return {
                "source": hit["source"],
                "g": hit["g"],
                "catalog_g": hit["catalog_g"],
                "saving_vs_catalog_g": hit.get("saving_vs_catalog_g"),
                "suffix_length": len(hit["suffix"]),
                "suffix": [format_action(action) for action in hit["suffix"]],
                "path": hit.get("path_canonical", []),
                "store_hex": hit["store"].hex(),
                "used_to_choose_candidates": False,
            }

        empty = None
        if self.stock_empty is not None:
            empty = {
                "g": int(self.stock_empty["g"]),
                "path": list(self.stock_empty.get("path_canonical", [])),
                "store_hex": self.stock_empty["store"].hex(),
            }
        return {
            "max_bonds_seen": self.max_bonds,
            "baseline_suffix_hit": hit_view(self.baseline_hit),
            "reference_suffix_hit": hit_view(self.reference_hit),
            "stock_boundaries": self.public_checkpoints,
            "stock_empty_unsolved": empty,
        }


def structurally_promising(boundary: Optional[dict], original: Optional[dict]) -> bool:
    """The spec's conjunction at a prepared next deal.

    Lower column disorder is not enough. A shorter deal that also has fewer
    same-suit bonds, or more cards still face-down, is not structural readiness.
    A true result still has unresolved terminal value until a solution is replayed.
    """

    if not boundary or not original or boundary.get("immediate_deal"):
        return False
    needed = ("focus_disorder", "same_suit_bonds", "rehandle_card_events", "face_down")
    if any(key not in boundary or key not in original for key in needed):
        return False
    return (
        int(boundary["focus_disorder"]) < int(original["focus_disorder"])
        and int(boundary["same_suit_bonds"]) > int(original["same_suit_bonds"])
        and int(boundary["rehandle_card_events"]) < int(original["rehandle_card_events"])
        and int(boundary["face_down"]) <= int(original["face_down"])
    )


def disorder_without_readiness(boundary: Optional[dict], original: Optional[dict]) -> bool:
    """Lower column-4 disorder without a gain in same-suit bonds."""

    if not boundary or not original or boundary.get("immediate_deal"):
        return False
    if "focus_disorder" not in boundary or "focus_disorder" not in original:
        return False
    if "same_suit_bonds" not in boundary or "same_suit_bonds" not in original:
        return False
    return (
        int(boundary["focus_disorder"]) < int(original["focus_disorder"])
        and int(boundary["same_suit_bonds"]) <= int(original["same_suit_bonds"])
    )


def parse_canonical(text: str):
    """Inverse of ``format_action`` for one recorded line."""

    if text == "deal":
        return ("deal",)
    parts = text.split()
    if len(parts) != 4 or parts[0] != "move":
        raise ValueError(f"bad action: {text}")
    return (int(parts[1]) - 1, int(parts[2]) - 1, int(parts[3]))


def checkpoint_from_actions(state: SpiderState, actions: Sequence[Action], *, label: str, root_g: int, focus_index: int) -> dict:
    """Measure one concrete path from an experiment root.

    ``actions`` are physical moves. A column permutation is not replayed.
    """

    root_debt = measure_state(state, g=root_g, root_g=root_g, focus_index=focus_index)["debt_vector"]
    trial = state.clone()
    g = int(root_g)
    for action in actions:
        g += apply_action(trial, action)
    metrics = measure_state(trial, g=g, root_g=root_g, focus_index=focus_index)
    tableau_moves = sum(1 for action in actions if action != ("deal",))
    metrics.update(
        {
            "label": label,
            "actions": [format_action(action) for action in actions],
            "action_count": len(actions),
            "tableau_moves_on_path": tableau_moves,
            "immediate_deal": tableau_moves == 0 and any(action == ("deal",) for action in actions),
            "rehandle_card_events": rehandle_card_events(state, actions),
            "debt_transfer_from_root": debt_transfer(root_debt, metrics["debt_vector"], focus_index),
        }
    )
    return metrics
