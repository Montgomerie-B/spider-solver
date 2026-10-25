"""Bounded strategic frontier for the human-strategy controller.

A node is one authoritative line: a cloned game state, its corrected
MobilityWare ancestry, and the campaign lock that produced it. The frontier
orders lines with a heuristic. It prunes a physical state only when a
strictly cheaper corrected ancestry already covers that state's strategic
choices.

Dominance rule
--------------
The key is ``canonical_state_key``. For one key the frontier stores the
cheapest corrected g, and the snapshot that reached it.

* A later visit with a higher g does not become its own line. Its campaign
  label is added to the cheaper snapshot's choice union. If that label was
  not already queued or expanded, a line is queued on the cheaper ancestry
  with that label held. The more expensive ancestry is not played.
* A later visit with an equal g and a different label or a different forced
  candidate is a second strategic context. Both stay, up to the frontier cap.
  The controller, not this queue, refuses to replay an action that another
  line already played from the same physical state. The labels stay. A
  different legal action is a different history.
* A later visit with a lower g replaces the stored snapshot. Queued nodes at
  the old g are dropped and their labels are re-queued on the new snapshot.
* Heuristic rank never discards a line by itself. When the queue is full, a
  node may be left unexpanded. That is capacity, not exhaustion, and it is
  counted in ``dropped_full``.
* Admissible cost is part of the exploration order only. The only mathematical
  prune remains the incumbent bound inside the controller. A line the
  controller refuses before ``consider`` is an incumbent prune, not
  ``dropped_full``. ``dropped_full`` is a heuristic exclusion.

Bond counts are not compared raw across different foundation counts. The
ordering and the reported-outcome rank add twelve per removed foundation,
which is the number of same-suit bonds a king-to-ace run removes with it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Set, Tuple

from spider.engine import SpiderState
from spider.research_actions import face_down_count
from spider.state_identity import canonical_state_key

from .evaluation import admissible_remaining, same_suit_bonds


def foundation_aware_bonds(state: SpiderState) -> int:
    """Same-suit bonds plus the bonds carried away by each removed foundation."""

    return same_suit_bonds(state) + 12 * len(state.foundations)


def _long_run_bias(state: SpiderState) -> int:
    """Tie-break only. A length-12 run does not outrank foundations or face-down."""

    for column in state.columns:
        up = column.face_up
        if len(up) < 12:
            continue
        start = len(up) - 1
        suit = up[start].suit
        while start > 0 and up[start - 1].suit == suit and up[start - 1].rank == up[start].rank + 1:
            start -= 1
        if len(up) - start >= 12:
            return -1
    return 0


# One removed foundation is worth this many still-buried cards when two
# lines are ordered. It is large enough that the g=19 spade board stays
# ahead of the opening, and small enough that a second foundation buried
# under a full tableau does not automatically beat a prepared one-foundation
# line. It is not a prune and it is not added to the MobilityWare cost.
FOUNDATION_FACE_DOWN_WEIGHT = 20


def line_priority(state: SpiderState, g: int, label: str = "") -> tuple:
    """Exploration order. Lower is tried sooner. Not an admissible bound.

    The first key is face-down cards still on the tableau, minus a bounded
    credit for each foundation already removed. A finished suit stays ahead
    of the untouched opening. A second suit does not outrank a line that has
    buried far fewer cards. ``g + admissible`` is the next key: it is the
    whole-game lower bound and it only orders. The admissible term never
    prunes. The last key prefers an exposed 12-card run only on a full tie.
    """

    admissible = admissible_remaining(state)
    foundations = len(state.foundations)
    progress = face_down_count(state) - FOUNDATION_FACE_DOWN_WEIGHT * foundations
    return (
        progress,
        int(g) + int(admissible),
        -foundation_aware_bonds(state),
        -foundations,
        -len(state.stock),
        label or "",
        _long_run_bias(state),
    )


def outcome_rank(state: SpiderState, g: int, *, solved: bool = False) -> tuple:
    """Which finished line to report. Lower is better.

    A solved board wins. Otherwise more foundations win, then fewer
    face-down cards, then corrected g. Raw g is the last key so a cheap
    early foundation does not automatically beat a line that excavated more
    at the same foundation count, and a zero-foundation line does not beat
    a removal merely by having a smaller g.
    """

    return (
        0 if solved or state.is_solved() else 1,
        -len(state.foundations),
        face_down_count(state),
        int(g),
    )


def better_outcome(current: tuple, challenger: tuple) -> tuple:
    """Return the better of two ``outcome_rank`` tuples."""

    return challenger if challenger < current else current


@dataclass
class StrategicNode:
    """One saved line. ``payload`` is the controller's cloned ``_Line``."""

    state: SpiderState
    g: int
    actions: Tuple[object, ...]
    lock: dict
    force_id: Optional[str]
    reason: str
    label: str
    payload: object
    priority: tuple
    signature: tuple
    token: tuple


@dataclass
class StrategicFrontier:
    limit: int = 8
    proposals: int = 3
    queue: List[StrategicNode] = field(default_factory=list)
    best_g: Dict[object, int] = field(default_factory=dict)
    best_snap: Dict[object, dict] = field(default_factory=dict)
    labels_at: Dict[object, Set[str]] = field(default_factory=dict)
    expanded: Set[tuple] = field(default_factory=set)
    explored_signatures: Dict[tuple, int] = field(default_factory=dict)
    generated: int = 0
    explored: int = 0
    transpositions: int = 0
    merges: int = 0
    dropped_full: int = 0
    replaced: int = 0
    same_moves: int = 0

    def __post_init__(self) -> None:
        self.limit = max(1, min(16, int(self.limit)))
        self.proposals = max(1, min(4, int(self.proposals)))

    def remember_visit(self, state: SpiderState, g: int, actions: Sequence, lock: dict) -> None:
        """Record the cheapest ancestry at this physical state. Does not queue it."""

        if self.limit <= 1:
            return
        ident = canonical_state_key(state)
        known = self.best_g.get(ident)
        if known is None or int(g) < known:
            self.best_g[ident] = int(g)
            self.best_snap[ident] = self._pack(state, int(g), actions, lock)
            if known is not None:
                self._drop_worse(ident, int(g))
        elif ident not in self.best_snap:
            self.best_snap[ident] = self._pack(state, int(g), actions, lock)

    def consider(
        self,
        *,
        state: SpiderState,
        g: int,
        actions: Sequence,
        lock: dict,
        force_id: Optional[str],
        reason: str,
        label: str,
        payload: object,
    ) -> Tuple[bool, str]:
        """Queue a line, or fold its label into the cheaper ancestry.

        Returns ``(accepted, event)``. ``accepted`` is false when the line
        was merged, skipped, or left unexpanded because the queue was full.
        """

        if self.limit <= 1:
            return False, ""
        ident = canonical_state_key(state)
        label = label or ""
        token = (ident, label, force_id or "")
        if token in self.expanded or any(item.token == token for item in self.queue):
            return False, ""
        known = self.best_g.get(ident)
        if known is not None and int(g) > known:
            self.transpositions += 1
            event = self._union_on_cheaper(ident, label, force_id, reason)
            return False, event
        if known is None or int(g) < known:
            if known is not None and int(g) < known:
                self._drop_worse(ident, int(g))
            self.best_g[ident] = int(g)
            self.best_snap[ident] = self._pack(state, int(g), actions, lock)
        self.labels_at.setdefault(ident, set()).add(label)
        node = self._node(state, int(g), actions, lock, force_id, reason, label, payload, token)
        if len(self.queue) >= self.limit and not self._make_room(node):
            self.dropped_full += 1
            return False, (
                f"frontier: capacity held {reason} unexpanded at g={g}; "
                "a full frontier is not exhaustion"
            )
        self.queue.append(node)
        self.generated += 1
        return True, f"frontier: retain {reason} at g={g} label={label or 'none'}"

    def mark_expanded(self, state: SpiderState, label: str, force_id: Optional[str] = None) -> None:
        if self.limit <= 1:
            return
        self.expanded.add((canonical_state_key(state), label or "", force_id or ""))

    def release(self, state: SpiderState, label: str, force_id: Optional[str] = None) -> None:
        """Let a paused line be queued again. The visit itself is kept."""

        if self.limit <= 1:
            return
        self.expanded.discard((canonical_state_key(state), label or "", force_id or ""))

    def pop_next(self) -> Optional[StrategicNode]:
        """Pop a line. Odd pops can leave the priority pool.

        The first pop, and every even pop after it, stays inside the best
        few priorities. An odd pop takes a never-explored signature outside
        that pool when one exists. Every fourth pop, if every outside
        signature has already been tried, gives the least-served outside
        line another slice. Promise still orders the pool. A campaign label
        is not, by itself, a different signature worth a turn.
        """

        if not self.queue:
            return None
        ranked = sorted(self.queue, key=lambda item: item.priority)
        pool = ranked[: max(3, self.proposals)]
        chosen = None
        if self.explored % 2 == 1:
            pool_signatures = {item.signature for item in pool}
            unseen = [
                item
                for item in ranked
                if item.signature not in pool_signatures
                and self.explored_signatures.get(item.signature, 0) == 0
            ]
            if unseen:
                chosen = unseen[0]
            elif self.explored % 4 == 3:
                outside = [item for item in ranked if item.signature not in pool_signatures]
                if outside:
                    outside.sort(
                        key=lambda item: (
                            self.explored_signatures.get(item.signature, 0),
                            item.priority,
                        )
                    )
                    chosen = outside[0]
        if chosen is None:
            pool.sort(key=lambda item: (self.explored_signatures.get(item.signature, 0), item.priority))
            chosen = pool[0]
        self.queue.remove(chosen)
        self.expanded.add(chosen.token)
        self.explored += 1
        self.explored_signatures[chosen.signature] = self.explored_signatures.get(chosen.signature, 0) + 1
        return chosen

    def pending(self) -> List[dict]:
        return [
            {
                "reason": item.reason,
                "g": item.g,
                "label": item.label,
                "expanded": False,
            }
            for item in self.queue
        ]

    def _union_on_cheaper(self, ident, label: str, force_id: Optional[str], reason: str) -> str:
        """Attach ``label`` to the cheapest ancestry. Do not play the worse g."""

        self.labels_at.setdefault(ident, set()).add(label)
        token = (ident, label, force_id or "")
        if token in self.expanded or any(item.token == token for item in self.queue):
            self.merges += 1
            return (
                f"frontier: transposition keeps g={self.best_g[ident]} "
                f"and {label or 'the line'} is already queued"
            )
        for item in self.queue:
            if item.token[0] == ident and label and label not in (item.lock.get("alternatives") or []):
                item.lock.setdefault("alternatives", []).append(label)
                self.merges += 1
                return (
                    f"frontier: transposition keeps g={self.best_g[ident]} "
                    f"and adds {label} to the cheaper line"
                )
        snap = self.best_snap.get(ident)
        if snap is None or not label:
            self.merges += 1
            return (
                f"frontier: transposition keeps g={self.best_g.get(ident)} "
                f"without a separate copy of {reason}"
            )
        lock = _copy_lock(snap["lock"])
        lock["hold_label"] = label
        lock["label"] = label
        alternatives = list(lock.get("alternatives") or [])
        if label not in alternatives:
            alternatives.append(label)
        lock["alternatives"] = alternatives
        node = self._node(
            snap["state"],
            snap["g"],
            snap["actions"],
            lock,
            None,
            f"cheaper ancestry tries {label}",
            label,
            snap["payload"],
            (ident, label, ""),
        )
        if len(self.queue) >= self.limit and not self._make_room(node):
            self.dropped_full += 1
            return (
                f"frontier: transposition keeps g={snap['g']}; "
                f"{label} stayed unexpanded because the frontier is full"
            )
        self.queue.append(node)
        self.generated += 1
        self.merges += 1
        return (
            f"frontier: transposition keeps g={snap['g']} "
            f"and queues {label} on that ancestry"
        )

    def _drop_worse(self, ident, g: int) -> None:
        kept: List[StrategicNode] = []
        for item in self.queue:
            if item.token[0] == ident and item.g > g:
                self.replaced += 1
                self.labels_at.setdefault(ident, set()).add(item.label)
            else:
                kept.append(item)
        self.queue = kept

    def _make_room(self, incoming: StrategicNode) -> bool:
        """Drop a duplicate signature first. Never treat the drop as a proof."""

        if len(self.queue) < self.limit:
            return True
        signatures = [item.signature for item in self.queue]
        duplicate = None
        for item in sorted(self.queue, key=lambda node: node.priority, reverse=True):
            if signatures.count(item.signature) > 1:
                duplicate = item
                break
        victim = duplicate
        if victim is None:
            # Keep a signature the incoming node does not already represent.
            incoming_seen = incoming.signature
            others = [item for item in self.queue if item.signature == incoming_seen]
            if not others:
                return False
            victim = max(others, key=lambda node: node.priority)
        self.queue.remove(victim)
        self.dropped_full += 1
        return True

    def _node(self, state, g, actions, lock, force_id, reason, label, payload, token) -> StrategicNode:
        foundations = len(state.foundations)
        stock_rows = len(state.stock) // 10
        signature = (foundations, stock_rows, label, face_down_count(state) // 5)
        return StrategicNode(
            state=state,
            g=int(g),
            actions=tuple(actions),
            lock=lock,
            force_id=force_id,
            reason=reason,
            label=label,
            payload=payload,
            priority=line_priority(state, int(g), label),
            signature=signature,
            token=token,
        )

    @staticmethod
    def _pack(state, g, actions, lock) -> dict:
        return {
            "state": state.clone(),
            "g": int(g),
            "actions": tuple(actions),
            "lock": _copy_lock(lock),
            "payload": None,
        }


def _copy_lock(lock: Optional[dict]) -> dict:
    if not lock:
        return {}
    copied = {}
    for key, value in lock.items():
        if isinstance(value, set):
            copied[key] = set(value)
        elif isinstance(value, list):
            copied[key] = list(value)
        elif isinstance(value, dict):
            copied[key] = dict(value)
        elif isinstance(value, tuple):
            copied[key] = tuple(value)
        else:
            copied[key] = value
    return copied
