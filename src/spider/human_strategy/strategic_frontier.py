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
* A heuristic drop is kept in a bounded deferred pool when it is a distinct
  physical state or a specific untried successor. A campaign-label copy of a
  state that is already retained is not kept. Dominance still refuses a
  worse corrected ancestry. Recovery re-admits one eligible deferred line
  only while the active queue is empty. It does not raise the queue cap.
* Admissible cost is part of the exploration order only. The only mathematical
  prune remains the incumbent bound inside the controller. A line the
  controller refuses before ``consider`` is an incumbent prune, not
  ``dropped_full``. ``dropped_full`` is a heuristic exclusion.
* Each refusal is also recorded in ``exclusion_log``. A full frontier does
  not prove the omitted line cannot improve a complete game. The successor
  of a queued objective is absent until that objective is played.

Bond counts are not compared raw across different foundation counts. The
ordering and the reported-outcome rank add twelve per removed foundation,
which is the number of same-suit bonds a king-to-ace run removes with it.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Set, Tuple

_NAMED_MOVE = re.compile(r"move (\d+) (\d+) (\d+)")

from spider.engine import SpiderState
from spider.packed_state import pack_state
from spider.research_actions import all_legal_actions, face_down_count
from spider.state_identity import canonical_state_key

from .evaluation import admissible_remaining, same_suit_bonds


def strategic_progress(state: SpiderState) -> dict:
    """Heuristic position measures. They order and report. They are not a proof bound."""

    runs = 0
    longest = 0
    for column in state.columns:
        face_up = column.face_up
        if len(face_up) < 2:
            continue
        length = 1
        for index in range(len(face_up) - 2, -1, -1):
            if face_up[index].suit == face_up[index + 1].suit and face_up[index].rank == face_up[index + 1].rank + 1:
                length += 1
            else:
                break
        if length >= 2:
            runs += 1
            longest = max(longest, length)
    return {
        "foundations": len(state.foundations),
        "face_down": face_down_count(state),
        "same_suit_runs": runs,
        "longest_same_suit_run": longest,
        "empty_columns": sum(1 for column in state.columns if column.is_empty()),
        "stock_cards": len(state.stock),
        "heuristic_only": True,
    }


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
    exclusion_log: List[dict] = field(default_factory=list)
    exclusion_overflow: int = 0
    deferred: List[StrategicNode] = field(default_factory=list)
    deferred_seen: Set[tuple] = field(default_factory=set)
    deferred_held: int = 0
    deferred_cap: int = 24
    recoveries: int = 0
    recovery_attempts: int = 0
    recovery_limit: int = 24
    recovered_states: int = 0
    recovered_idents: Set[object] = field(default_factory=set)
    empty_snapshot: Optional[dict] = None
    timing: Optional[dict] = None
    inclusive: Optional[dict] = None

    def _add_elapsed(self, name: str, start: float, end: float) -> None:
        if self.timing is None:
            return
        spent = end - start
        if spent <= 0:
            return
        self.timing[name] = self.timing.get(name, 0.0) + spent

    def _add_inclusive(self, name: str, start: float, end: float) -> None:
        if self.inclusive is None:
            return
        spent = end - start
        if spent <= 0:
            return
        self.inclusive[name] = self.inclusive.get(name, 0.0) + spent

    def __post_init__(self) -> None:
        self.limit = max(1, min(16, int(self.limit)))
        self.proposals = max(1, min(4, int(self.proposals)))
        self.deferred_cap = max(1, min(64, int(self.deferred_cap)))
        self.recovery_limit = max(0, min(32, int(self.recovery_limit)))

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

        started = time.perf_counter()
        try:
            if self.limit <= 1:
                self._add_elapsed("frontier_evaluation", started, time.perf_counter())
                return False, ""
            ident = canonical_state_key(state)
            label = label or ""
            token = (ident, label, force_id or "")
            duplicate = token in self.expanded or any(item.token == token for item in self.queue)
            dedup_done = time.perf_counter()
            if duplicate:
                self._add_elapsed("frontier_dedup", started, dedup_done)
                return False, ""
            known = self.best_g.get(ident)
            if known is not None and int(g) > known:
                self.transpositions += 1
                self._note_exclusion(
                    "transposition_dominance",
                    state=state,
                    g=int(g),
                    reason=reason,
                    label=label,
                    force_id=force_id,
                    priority=line_priority(state, int(g), label),
                    equivalent=True,
                    proof=True,
                )
                event = self._union_on_cheaper(ident, label, force_id, reason)
                evaluated = time.perf_counter()
                self._add_elapsed("frontier_dedup", started, dedup_done)
                self._add_elapsed("frontier_evaluation", dedup_done, evaluated)
                return False, event
            if known is None or int(g) < known:
                if known is not None and int(g) < known:
                    self._drop_worse(ident, int(g))
                self.best_g[ident] = int(g)
                self.best_snap[ident] = self._pack(state, int(g), actions, lock)
            self.labels_at.setdefault(ident, set()).add(label)
            node = self._node(state, int(g), actions, lock, force_id, reason, label, payload, token)
            evaluated = time.perf_counter()
            if len(self.queue) >= self.limit and not self._make_room(node):
                self.dropped_full += 1
                equivalent = self._state_retained(ident)
                self._note_exclusion(
                    "heuristic_admission",
                    state=state,
                    g=int(g),
                    reason=reason,
                    label=label,
                    force_id=force_id,
                    priority=node.priority,
                    equivalent=equivalent,
                    proof=False,
                )
                self._hold_deferred(node, equivalent=equivalent)
                admitted = time.perf_counter()
                self._add_elapsed("frontier_dedup", started, dedup_done)
                self._add_elapsed("frontier_evaluation", dedup_done, evaluated)
                self._add_elapsed("frontier_admission", evaluated, admitted)
                return False, (
                    f"frontier: capacity held {reason} unexpanded at g={g}; "
                    "a full frontier is not exhaustion"
                )
            self.queue.append(node)
            self.generated += 1
            self.deferred = [item for item in self.deferred if item.token != token]
            admitted = time.perf_counter()
            self._add_elapsed("frontier_dedup", started, dedup_done)
            self._add_elapsed("frontier_evaluation", dedup_done, evaluated)
            self._add_elapsed("frontier_admission", evaluated, admitted)
            return True, f"frontier: retain {reason} at g={g} label={label or 'none'}"
        finally:
            self._add_inclusive("frontier", started, time.perf_counter())

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

        started = time.perf_counter()
        try:
            return self._pop_next_ranked()
        finally:
            # Choosing the next admitted line is frontier evaluation, not a new admission.
            self._add_elapsed("frontier_evaluation", started, time.perf_counter())
            self._add_inclusive("frontier", started, time.perf_counter())

    def _pop_next_ranked(self) -> Optional[StrategicNode]:
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
            self._note_exclusion(
                "heuristic_admission",
                state=snap["state"],
                g=int(snap["g"]),
                reason=f"{label} stayed unexpanded because the frontier is full",
                label=label,
                force_id=None,
                priority=node.priority,
                equivalent=True,
                proof=False,
            )
            return (
                f"frontier: transposition keeps g={snap['g']}; "
                f"{label} stayed unexpanded because the frontier is full"
            )
        self.queue.append(node)
        self.generated += 1
        self.merges += 1
        self.deferred = [item for item in self.deferred if item.token != node.token]
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
        removed = [item for item in self.deferred if item.token[0] == ident and item.g > g]
        if removed:
            removed_tokens = {item.token for item in removed}
            self.deferred = [item for item in self.deferred if item.token not in removed_tokens]
            for item in removed:
                self.deferred_seen.discard(item.token)

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
        equivalent = any(
            item is not victim and item.token[0] == victim.token[0] for item in self.queue
        )
        self._note_exclusion(
            "heuristic_admission",
            state=victim.state,
            g=victim.g,
            reason=f"evicted to admit another line: {victim.reason}",
            label=victim.label,
            force_id=victim.force_id,
            priority=victim.priority,
            equivalent=equivalent,
            proof=False,
        )
        self.queue.remove(victim)
        self._hold_deferred(victim, equivalent=equivalent)
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

    def _state_retained(self, ident) -> bool:
        if any(item.token[0] == ident for item in self.queue):
            return True
        return any(token[0] == ident for token in self.expanded)

    def _hold_deferred(self, node: StrategicNode, *, equivalent: bool) -> None:
        """Keep a heuristic drop until the active queue has room again.

        A label copy of a physical state that is already retained is not a
        new line. A worse corrected ancestry is not eligible. The same token
        is stored at most once, so recovery cannot cycle on it.
        """

        if node.token in self.deferred_seen or node.token in self.expanded:
            return
        if any(item.token == node.token for item in self.queue):
            return
        if any(item.token == node.token for item in self.deferred):
            return
        if not node.force_id and equivalent:
            return
        known = self.best_g.get(node.token[0])
        if known is not None and int(node.g) > int(known):
            return
        if len(self.deferred) >= int(self.deferred_cap):
            worst = max(self.deferred, key=_recovery_key)
            if _recovery_key(node) >= _recovery_key(worst):
                return
            self.deferred.remove(worst)
        self.deferred.append(node)
        self.deferred_seen.add(node.token)
        self.deferred_held += 1

    def _pinned_legal(self, node: StrategicNode) -> bool:
        state = node.state
        columns = getattr(state, "columns", None)
        if not isinstance(state, SpiderState) or columns is None or len(columns) != 10:
            return False
        pinned = []
        if isinstance(node.lock, dict):
            pinned = list(node.lock.get("pinned_actions") or [])
        if not pinned:
            return True
        try:
            legal = set(all_legal_actions(state))
        except (TypeError, ValueError):
            return False
        return all(action in legal for action in pinned)

    def eligible_deferred(self) -> List[StrategicNode]:
        """Deferred lines that are still legal and not dominated."""

        found: List[StrategicNode] = []
        for node in self.deferred:
            if node.token in self.expanded:
                continue
            if any(item.token == node.token for item in self.queue):
                continue
            known = self.best_g.get(node.token[0])
            if known is not None and int(node.g) > int(known):
                continue
            if not self._pinned_legal(node):
                continue
            found.append(node)
        found.sort(key=_recovery_key)
        return found

    def recover_one(self) -> Optional[StrategicNode]:
        """Re-admit one deferred line. The queue cap stays where it is.

        Returns None when the queue is not empty, the reconsideration limit
        is spent, or no eligible candidate remains. A returned node is queued
        and is not counted again in ``generated``.
        """

        if self.queue:
            return None
        self.recovery_attempts += 1
        if self.recoveries >= int(self.recovery_limit):
            return None
        eligible = self.eligible_deferred()
        if not eligible:
            return None
        chosen = eligible[0]
        self.deferred = [item for item in self.deferred if item.token != chosen.token]
        self.queue.append(chosen)
        self.recoveries += 1
        ident = chosen.token[0]
        if ident not in self.recovered_idents:
            self.recovered_idents.add(ident)
            self.recovered_states += 1
        return chosen

    def _note_exclusion(
        self,
        kind: str,
        *,
        state: SpiderState,
        g: int,
        reason: str,
        label: str,
        force_id: Optional[str],
        priority,
        equivalent: bool,
        proof: bool,
    ) -> None:
        """Record why a line was not kept. This is not a second prune."""

        if len(self.exclusion_log) >= 128:
            self.exclusion_overflow += 1
            return
        value = None if priority is None else [item for item in priority]
        self.exclusion_log.append(
            {
                "kind": kind,
                "objective": force_id or reason,
                "reason": reason,
                "label": label or "",
                "g": int(g),
                "strategic_value": value,
                "parent_state": pack_state(state).hex()[:16],
                "successor_state": None,
                "equivalent_retained": bool(equivalent),
                "proof": bool(proof),
            }
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


def _names_move(node: StrategicNode) -> bool:
    return _NAMED_MOVE.search(f"{node.force_id or ''} {node.reason or ''}") is not None


def _recovery_key(node: StrategicNode) -> tuple:
    """Lower is recovered sooner. A named legal successor outranks a bare label."""

    return (
        0 if node.force_id else 1,
        0 if _names_move(node) else 1,
        node.priority,
        int(node.g),
        node.label or "",
    )


def pin_named_successor(node: StrategicNode) -> bool:
    """Pin the move named by a recovered line when that move is legal now.

    Deal-alternative labels such as ``PARK:move 1 4 1`` are not played unless
    the controller still emits that candidate. A legal pin makes the untried
    successor the next action. An existing pin is left alone. A move that is
    not legal is not invented.
    """

    if not isinstance(node.lock, dict) or node.lock.get("pinned_actions"):
        return False
    match = _NAMED_MOVE.search(f"{node.force_id or ''} {node.reason or ''}")
    if match is None:
        return False
    # Columns are 1-based in the label. The third number is the card count.
    action = (int(match.group(1)) - 1, int(match.group(2)) - 1, int(match.group(3)))
    if action[0] < 0 or action[1] < 0 or action[2] < 1:
        return False
    try:
        legal = all_legal_actions(node.state)
    except (TypeError, ValueError):
        return False
    if action not in legal:
        return False
    node.lock["pinned_actions"] = [action]
    return True


def build_stall_audit(
    frontier: StrategicFrontier,
    current: Optional[SpiderState],
    *,
    remaining_s: float,
    elapsed_s: float,
    resource_limited: int = 0,
    exhausted_within_bound: int = 0,
    strategic_holds: int = 0,
    deep_ready: int = 0,
) -> dict:
    """Why the active queue is empty. Heuristic drops are not proofs."""

    eligible = frontier.eligible_deferred()
    states: List[SpiderState] = []
    seen = set()
    candidates = []
    if current is not None:
        candidates.append(current)
    candidates.extend(node.state for node in frontier.deferred)
    for state in candidates:
        try:
            ident = canonical_state_key(state)
        except (TypeError, ValueError):
            continue
        if ident in seen:
            continue
        seen.add(ident)
        states.append(state)
    tableau = 0
    deals = 0
    for state in states:
        try:
            actions = all_legal_actions(state)
        except (TypeError, ValueError):
            continue
        tableau += sum(1 for action in actions if action != ("deal",))
        if ("deal",) in actions:
            deals += 1
    unexplored = len(eligible)
    forced = sum(1 for node in eligible if node.force_id)
    can_explore = bool(eligible) and float(remaining_s) > 0.05 and frontier.recoveries < int(frontier.recovery_limit)
    if can_explore:
        decision = (
            "The active frontier is empty and no unplayed seed was queued. "
            f"{len(eligible)} heuristically deferred candidates remain eligible. "
            "Recovery will reconsider one of them. "
            "This is not graph exhaustion and it is not a proof."
        )
    elif frontier.deferred and frontier.recoveries >= int(frontier.recovery_limit):
        decision = (
            "The configured recovery limit has been reached while deferred candidates remain. "
            "PLANNING_STALL here is a reconsideration limit, not proof that every legal continuation was searched."
        )
    else:
        decision = (
            "The active frontier is empty and no eligible deferred candidate remains "
            "under the configured restrictions. PLANNING_STALL is the policy stop. "
            "Heuristic rejection was not treated as impossibility."
        )
    first = None
    if eligible:
        best = eligible[0]
        first = {
            "reason": best.reason,
            "g": int(best.g),
            "label": best.label or "",
            "force_id": best.force_id or "",
        }
    return {
        "elapsed_s": round(float(elapsed_s), 3),
        "retained_strategic_states": len(frontier.best_g),
        "explored_lines": int(frontier.explored),
        "explored_physical_states": len({token[0] for token in frontier.expanded}),
        "eligible_deferred": len(eligible),
        "deferred_held": int(frontier.deferred_held),
        "deferred_remaining": len(frontier.deferred),
        "legal_tableau_actions": int(tableau),
        "legal_stock_deals": int(deals),
        "dominance_discards": int(frontier.transpositions),
        "heuristic_discards": int(frontier.dropped_full),
        "resource_limited_objectives": int(resource_limited),
        "strategic_holds": int(strategic_holds),
        "deep_ready": int(deep_ready),
        "exhausted_within_bound": int(exhausted_within_bound),
        "unexplored_successors": int(unexplored),
        "unexplored_forced_successors": int(forced),
        "remaining_s": round(float(remaining_s), 3),
        "could_explore_with_remaining_time": bool(can_explore),
        "policy_decision": decision,
        "first_candidate": first,
        "recovery_limit": int(frontier.recovery_limit),
    }
