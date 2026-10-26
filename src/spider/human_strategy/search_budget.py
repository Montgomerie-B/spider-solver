"""Wall-clock and node allowances for one strategic solve.

The numbers are the v0.119 measurement on deal 4925153, not a law of the
game. Callers can replace them. A nested probe clips its deadline to the
time this coordinator still has, and to the time its caller passed in.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from spider.state_identity import canonical_state_key

# v0.119 elapsed probes that had already exhausted their graph did so at 48
# nodes (4h and one Qh). The first node cap is three times that.
# Those probes were allowed 2,000 nodes and 3 seconds, so 160 nodes is about
# 0.24 seconds. 0.28 seconds leaves a little room for the interpreter.
# Partials that still reduced cover after the first cap, and before the
# 4,500-node tier, used up to 1,151 nodes. 800 is the configured bridge.
# 0.55 seconds keeps two such probes inside the 1.25 second proposal slice.
# 4,500 nodes remains available. The ordinary ladder deadline is still the
# proposal slice. A separate reserve can give one justified 4,500-node probe
# a longer wall clock, clipped by the global remainder and by deep_share.
# Node count and wall clock are different budgets.
DERIVATION = (
    "First cap 160 nodes and 0.28s from the v0.119 48-node exhausted graphs "
    "and the 2,000-node/3s probes. Middle cap 800 nodes and 0.55s from partials "
    "that were still reducing cover below 1,151 nodes. Deep cap 4,500 nodes, "
    "the existing excavation capability. The ordinary ladder deadline is 1.25s "
    "and a 0.15 share of the remaining global time. The proposal slice is 1.25s "
    "so one objective cannot spend the historical 12s monopoly on every probe. "
    "A cover drop is not the only reason to try the next allowance: a limited "
    "reserve may deepen one blocked objective when an empty column, a buried "
    "receiver, or an intermediate sequence makes the extra search worth attempting. "
    "A separate deep reserve may give that 4,500-node rung up to about 12 seconds "
    "when the remaining global deadline and the deep share leave at least 6.5 seconds. "
    "A TIME_LIMIT is not a permanent disqualification when an intermediate sequence "
    "or that position evidence exists. The node allowance and the wall-clock allowance "
    "are reported separately."
)

_RESOURCE = frozenset({"NODE_LIMIT", "TIME_LIMIT", "PROBE_LIMIT"})
_EXHAUSTED = frozenset(
    {"GRAPH_EXHAUSTED_WITHIN_BOUND", "PROVEN_INFEASIBLE_UNDER_EXPLICIT_CONDITIONS"}
)


@dataclass(frozen=True)
class Allowance:
    level: int
    max_cost: int
    max_nodes: int
    deadline_s: float
    reserved_deep: bool = False


@dataclass(frozen=True)
class TacticalLimits:
    proposal_slice_s: float = 1.25
    reserve_s: float = 1.25
    deep_share: float = 0.15
    ladder: tuple = (
        (2, 4, 160, 0.28),
        (3, 6, 800, 0.55),
        (4, 8, 4500, 1.25),
    )

    def step(self, index: int) -> Allowance:
        level, cost, nodes, deadline = self.ladder[index]
        return Allowance(int(level), int(cost), int(nodes), float(deadline))

    def first(self) -> Allowance:
        return self.step(0)

    def next_after(self, nodes: int) -> Optional[Allowance]:
        for level, cost, cap, deadline in self.ladder:
            if int(cap) > int(nodes):
                return Allowance(int(level), int(cost), int(cap), float(deadline))
        return None

    def as_dict(self) -> dict:
        return {
            "proposal_slice_s": self.proposal_slice_s,
            "reserve_s": self.reserve_s,
            "deep_share": self.deep_share,
            "ladder": [
                {
                    "level": int(level),
                    "max_cost": int(cost),
                    "max_nodes": int(nodes),
                    "deadline_s": float(deadline),
                }
                for level, cost, nodes, deadline in self.ladder
            ],
            "derivation": DERIVATION,
        }


@dataclass
class _Grant:
    kind: str
    allowance: Optional[Allowance] = None
    plan: object = None


@dataclass
class _DeepGrant:
    card: object
    objective: str
    column: int
    allowance: Allowance


@dataclass
class _Record:
    objective: str
    column: int
    card: object
    allowance_nodes: int
    allowance_cost: int
    time_allowance: float
    classification: str
    useful: bool
    plan: object
    level_index: int
    justification: str = ""


@dataclass
class BudgetCoordinator:
    """Tracks one solve and decides the next tactical allowance.

    The object lives in a process table. Frontier snapshots store only the
    integer key, so a copied lock still sees this coordinator.
    """

    deadline: float
    limits: TacticalLimits
    events: List[str] = field(default_factory=list)
    nodes_granted: int = 0
    nodes_used: int = 0
    by_objective: Dict[str, dict] = field(default_factory=dict)
    by_state: Dict[object, dict] = field(default_factory=dict)
    records: Dict[tuple, _Record] = field(default_factory=dict)
    open_partials: List[_Record] = field(default_factory=list)
    classifications: Dict[str, int] = field(default_factory=dict)
    deferred: int = 0
    revisited: int = 0
    deepened: int = 0
    identical_skips: int = 0
    physical_duplicates: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    nodes_saved: int = 0
    refused_reuse: int = 0
    larger_reprobes: int = 0
    hits_by_status: Dict[str, int] = field(default_factory=dict)
    alternatives_waiting: int = 0
    proposal_turns: int = 0
    pending_deepen: bool = False
    viable_alternative: bool = False
    proposal_g: Dict[tuple, int] = field(default_factory=dict)
    strategic_holds: List[_Record] = field(default_factory=list)
    decision_log: List[dict] = field(default_factory=list)
    nonmonotone_deepened: int = 0
    nonmonotone_limit: int = 3
    deep_ready: List[_Record] = field(default_factory=list)
    deep_used: int = 0
    deep_limit: int = 2
    deep_wall_s: float = 12.0
    deep_minimum_s: float = 6.5
    deep_limit_noted: bool = False
    detail: bool = False
    _deepen_taken: bool = False

    def remaining(self) -> float:
        return self.deadline - time.perf_counter()

    def clip(self, deadline_s: float, time_left: float, *, deep: bool = False) -> float:
        """A nested allowance cannot outlive the caller or the global clock."""

        remaining = max(0.0, self.remaining())
        allowed = min(float(deadline_s), max(0.0, float(time_left)), remaining)
        if deep:
            allowed = min(allowed, remaining * float(self.limits.deep_share))
        return max(0.0, allowed)

    def note_cache(self, *, hit: bool, category: str = "", nodes: int = 0, refused: int = 0, larger: bool = False) -> None:
        if hit:
            self.cache_hits += 1
            self.nodes_saved += int(nodes)
            if category:
                self.hits_by_status[category] = int(self.hits_by_status.get(category, 0)) + 1
        else:
            self.cache_misses += 1
            self.refused_reuse += int(refused)
            if larger:
                self.larger_reprobes += 1

    def begin_proposal(self) -> None:
        self._deepen_taken = False
        self.viable_alternative = False
        self.proposal_turns += 1

    def note_alternatives(self, waiting: int) -> None:
        self.alternatives_waiting = max(0, int(waiting))

    def note_viable(self) -> None:
        self.viable_alternative = True

    def _count(self, name: str) -> None:
        self.classifications[name] = int(self.classifications.get(name, 0)) + 1

    def _note(self, kind: str, objective: str, reason: str) -> None:
        """One scheduling decision. This is not a per-node trace."""

        if len(self.decision_log) >= 400 and not self.detail:
            return
        if len(self.decision_log) >= 800:
            return
        self.decision_log.append(
            {"kind": kind, "objective": str(objective), "reason": reason}
        )

    def _bucket(self, store: dict, key) -> dict:
        found = store.get(key)
        if found is None:
            found = {"seconds": 0.0, "nodes": 0, "visits": 0}
            store[key] = found
        return found

    def begin_probe(self, state, objective: str, column: int, card, time_left: float) -> _Grant:
        state_key = canonical_state_key(state)
        record = self.records.get((state_key, str(objective)))
        first = self.limits.first()
        if record is None:
            self._note("select", objective, "first allowance on this state and objective")
            return _Grant("search", first)
        if record.useful and self.limits.next_after(record.allowance_nodes) is not None:
            self._count("temporarily_deferred")
            return _Grant("replay", plan=record.plan)
        if record.classification == "proved_impossible":
            self.identical_skips += 1
            self._count("proved_impossible")
            return _Grant("replay", plan=record.plan)
        if record.classification == "exhausted_within_bound":
            self.identical_skips += 1
            self._count("exhausted_within_bound")
            return _Grant("replay", plan=record.plan)
        if record.classification == "resource_limited":
            stopped_by_clock = getattr(record.plan, "status", "") == "TIME_LIMIT" or getattr(record.plan, "stop", "") == "TIME_LIMIT"
            if stopped_by_clock and float(time_left) > float(record.time_allowance) + 0.05:
                self._note("select", objective, "the same node cap has more time left")
                return _Grant(
                    "search",
                    Allowance(
                        int(record.level_index) + 2,
                        record.allowance_cost,
                        record.allowance_nodes,
                        float(time_left),
                    ),
                )
            if (not stopped_by_clock) and first.max_nodes > record.allowance_nodes:
                self._note("select", objective, "the allowance is larger than the stored probe")
                return _Grant("search", first)
            self.identical_skips += 1
            self.deferred += 1
            self.pending_deepen = False
            self._count("temporarily_deferred")
            self._note(
                "defer",
                objective,
                f"unchanged board at {record.allowance_nodes} nodes; eligible when the board or the allowance changes",
            )
            self.events.append(
                f"budget: deferred {objective} on an unchanged board at {record.allowance_nodes} nodes; "
                "still eligible when the board or the allowance changes"
            )
            return _Grant("defer")
        self._note("select", objective, "no stored probe covers this request")
        return _Grant("search", first)

    def finish(self, state, objective, column, card, plan, allowance: Allowance, elapsed: float) -> None:
        state_key = canonical_state_key(state)
        nodes = int(getattr(plan, "nodes", 0) or 0)
        self.nodes_granted += int(allowance.max_nodes)
        self.nodes_used += nodes
        objective_bucket = self._bucket(self.by_objective, str(objective))
        state_bucket = self._bucket(self.by_state, state_key)
        for bucket in (objective_bucket, state_bucket):
            bucket["seconds"] = float(bucket["seconds"]) + float(elapsed)
            bucket["nodes"] = int(bucket["nodes"]) + nodes
            bucket["visits"] = int(bucket["visits"]) + 1
        classification = _classify(plan)
        useful = classification == "progress"
        justification = "" if useful else _nonmonotone_reason(state, card, plan)
        self._count(classification)
        if classification == "completed":
            self.viable_alternative = True
        record = _Record(
            objective=str(objective),
            column=int(column),
            card=card,
            allowance_nodes=int(allowance.max_nodes),
            allowance_cost=int(allowance.max_cost),
            time_allowance=float(allowance.deadline_s),
            classification=classification,
            useful=useful,
            plan=plan,
            level_index=max(0, int(allowance.level) - 2),
            justification=justification,
        )
        self.records[(state_key, str(objective))] = record
        self.open_partials = [item for item in self.open_partials if item.objective != record.objective]
        self.strategic_holds = [item for item in self.strategic_holds if item.objective != record.objective]
        self.deep_ready = [item for item in self.deep_ready if item.objective != record.objective]
        nxt = self.limits.next_after(allowance.max_nodes)
        if useful and nxt is not None:
            self.open_partials.append(record)
            self._note("progress", record.objective, "cover fell inside the node allowance")
        elif justification and classification == "resource_limited" and nxt is not None:
            if self._reserves_deep_rung(nxt):
                self.deep_ready.append(record)
                self._note(
                    "justify",
                    record.objective,
                    justification + "; eligible for the reserved deep rung",
                )
            else:
                self.strategic_holds.append(record)
                self._note("justify", record.objective, justification)

    def take_deepen(self, time_left: float) -> Optional[_DeepGrant]:
        """One larger probe after every target in this proposal had its cheap turn.

        Cover that fell inside its node budget still uses the ladder clock.
        A justified probe whose next rung is 4,500 nodes can instead draw the
        reserved deep wall. That wall is not the proposal slice. The 160-to-800
        reserve is unchanged and is not spent by a reserved deep grant.
        """

        if self._deepen_taken or self.viable_alternative:
            return None
        if self.open_partials:
            if not self._deepen_allowed(time_left):
                return self._defer_deepen(self.open_partials[0])
            return self._grant_ladder(self.open_partials, time_left, nonmonotone=False)
        reserved = self._grant_reserved(time_left)
        if reserved is not None:
            return reserved
        if not self.strategic_holds:
            return None
        if self.nonmonotone_deepened >= int(self.nonmonotone_limit):
            self._note("stop", self.strategic_holds[0].objective, "the nonmonotone reserve is spent")
            return None
        if not self._deepen_allowed(time_left):
            return self._defer_deepen(self.strategic_holds[0])
        return self._grant_ladder(self.strategic_holds, time_left, nonmonotone=True)

    def _defer_deepen(self, record: _Record) -> None:
        self.deferred += 1
        self.pending_deepen = True
        self._count("temporarily_deferred")
        self._note("defer", record.objective, "another strategic line still needs a cheap probe")
        self.events.append(
            "budget: deferred a promising partial so another strategic line can run"
        )
        return None

    def _grant_ladder(self, pool: List[_Record], time_left: float, *, nonmonotone: bool) -> Optional[_DeepGrant]:
        record = pool.pop(0)
        nxt = self.limits.next_after(record.allowance_nodes)
        if nxt is None:
            return None
        self._deepen_taken = True
        self.pending_deepen = False
        self.deepened += 1
        self.revisited += 1
        if nonmonotone:
            self.nonmonotone_deepened += 1
        clipped = self.clip(nxt.deadline_s, time_left, deep=True)
        granted = Allowance(nxt.level, nxt.max_cost, nxt.max_nodes, clipped)
        why = record.justification or "cover fell inside the previous allowance"
        self._note("deepen", record.objective, why)
        self.events.append(
            f"budget: deepen {record.objective} to {granted.max_nodes} nodes "
            f"with {granted.deadline_s:.2f}s inside the global deadline; {why}"
        )
        return _DeepGrant(record.card, record.objective, record.column, granted)

    def _deep_wall(self) -> float:
        """Wall clock for one reserved 4,500-node probe. Ignores the proposal slice."""

        remaining = max(0.0, self.remaining())
        share = remaining * float(self.limits.deep_share)
        return max(0.0, min(float(self.deep_wall_s), remaining, share))

    def _reserves_deep_rung(self, nxt: Allowance) -> bool:
        """True when ``nxt`` is the top ladder rung and it has at least 4,500 nodes."""

        return int(nxt.max_nodes) >= 4500 and self.limits.next_after(nxt.max_nodes) is None

    def _grant_reserved(self, time_left: float) -> Optional[_DeepGrant]:
        """One 4,500-node probe whose clock is the global remainder, not the slice.

        A short remainder leaves the record queued so a later call can still
        grant a cheap deepen. The same objective is not granted twice: the
        next rung after 4,500 does not exist, and ``deep_limit`` caps the solve.
        """

        if not self.deep_ready or not self._deepen_allowed(time_left):
            return None
        wall = self._deep_wall()
        if wall + 1e-9 < float(self.deep_minimum_s):
            return None
        record = self.deep_ready[0]
        nxt = self.limits.next_after(record.allowance_nodes)
        if nxt is None or int(nxt.max_nodes) < 4500:
            self.deep_ready.pop(0)
            return self._grant_reserved(time_left)
        if self.deep_used >= int(self.deep_limit):
            if not self.deep_limit_noted:
                self.deep_limit_noted = True
                self._note("stop", record.objective, "the deep investigation reserve is spent")
            return None
        self.deep_ready.pop(0)
        self._deepen_taken = True
        self.pending_deepen = False
        self.deepened += 1
        self.revisited += 1
        self.deep_used += 1
        granted = Allowance(nxt.level, nxt.max_cost, nxt.max_nodes, wall, True)
        why = record.justification or "reserved deep rung"
        self._note(
            "deepen",
            record.objective,
            f"{why}; reserved {granted.max_nodes} nodes and {granted.deadline_s:.2f}s",
        )
        self.events.append(
            f"budget: reserved deep {record.objective} to {granted.max_nodes} nodes "
            f"with {granted.deadline_s:.2f}s of wall clock inside the global deadline; "
            f"node budget and time budget are separate; {why}"
        )
        return _DeepGrant(record.card, record.objective, record.column, granted)

    def _deepen_allowed(self, time_left: float) -> bool:
        remaining = self.remaining()
        if remaining < float(self.limits.reserve_s) + 0.05:
            return False
        if float(time_left) < 0.2:
            return False
        if self.alternatives_waiting > 0 and self.proposal_turns <= self.alternatives_waiting:
            return False
        return True

    def should_skip_proposal(self, ident, label, g: int, blocked) -> bool:
        """Skip a foundation rebuild for the same state, objective, and cost.

        A cheaper ancestry is not skipped. A partial that is waiting for a
        larger allowance is not skipped either.
        """

        if self.pending_deepen or self.open_partials or self.strategic_holds or self.deep_ready:
            return False
        token = (ident, str(label or ""), tuple(blocked))
        seen = self.proposal_g.get(token)
        if seen is None or int(g) < int(seen):
            return False
        self.physical_duplicates += 1
        self.events.append(
            "budget: skipped a foundation proposal for an authoritative state "
            "and objective already evaluated at this cost"
        )
        return True

    def mark_evaluated(self, ident, label, g: int, blocked) -> None:
        token = (ident, str(label or ""), tuple(blocked))
        seen = self.proposal_g.get(token)
        if seen is None or int(g) < int(seen):
            self.proposal_g[token] = int(g)

    def snapshot(self) -> dict:
        objectives = []
        for name, bucket in self.by_objective.items():
            objectives.append(
                {
                    "objective": name,
                    "seconds": round(float(bucket["seconds"]), 3),
                    "nodes": int(bucket["nodes"]),
                    "visits": int(bucket["visits"]),
                }
            )
        objectives.sort(key=lambda item: (-item["nodes"], item["objective"]))
        awaiting = sum(
            1
            for record in self.records.values()
            if record.classification in {"temporarily_deferred", "resource_limited", "progress"}
        )
        return {
            "remaining_s": round(max(0.0, self.remaining()), 3),
            "nodes_granted": int(self.nodes_granted),
            "nodes_used": int(self.nodes_used),
            "objectives": len(self.by_objective),
            "authoritative_states": len(self.by_state),
            "awaiting": int(awaiting),
            "alternatives_waiting": int(self.alternatives_waiting),
            "deferred": int(self.deferred),
            "revisited": int(self.revisited),
            "deepened": int(self.deepened),
            "identical_skips": int(self.identical_skips),
            "physical_duplicates": int(self.physical_duplicates),
            "cache_hits": int(self.cache_hits),
            "cache_misses": int(self.cache_misses),
            "nodes_saved": int(self.nodes_saved),
            "refused_reuse": int(self.refused_reuse),
            "larger_reprobes": int(self.larger_reprobes),
            "hits_by_status": dict(self.hits_by_status),
            "classifications": dict(self.classifications),
            "objective_work": objectives[:12],
            "nonmonotone_deepened": int(self.nonmonotone_deepened),
            "strategic_holds": len(self.strategic_holds),
            "deep_ready": len(self.deep_ready),
            "deep_used": int(self.deep_used),
            "deep_limit": int(self.deep_limit),
            "deep_wall_s": float(self.deep_wall_s),
            "deep_minimum_s": float(self.deep_minimum_s),
            "decisions": list(self.decision_log[-24:]),
            "limits": self.limits.as_dict(),
        }


def _nonmonotone_reason(state, card, plan) -> str:
    """Why a probe that did not reduce cover may still receive one larger allowance.

    The reason allocates a bounded reserve. It is not a proof the card can be reached.
    A node cap with no actions and no supporting position does not qualify.
    """

    if plan is None or card is None or state is None:
        return ""
    status = getattr(plan, "status", "") or ""
    stop = getattr(plan, "stop", "") or ""
    clock_stop = status == "TIME_LIMIT" or stop == "TIME_LIMIT"
    if clock_stop:
        # A clock that expired before any expansion is not evidence. A clock
        # that stopped after an intermediate sequence, or after the position
        # evidence below, can still justify one larger allowance.
        nodes = int(getattr(plan, "nodes", 0) or 0)
        actions = tuple(getattr(plan, "actions", ()) or ())
        if nodes <= 0 and not actions:
            return ""
    if status in _EXHAUSTED or stop in _EXHAUSTED:
        return ""
    if status in {"unlocked", "exposed"}:
        return ""
    depth_before = int(getattr(plan, "depth_before", 0) or 0)
    depth_after = int(getattr(plan, "depth_after", 0) or 0)
    if depth_before <= 0 or depth_after < depth_before:
        return ""
    if status not in _RESOURCE | {"progress"} and stop not in _RESOURCE:
        return ""
    actions = tuple(getattr(plan, "actions", ()) or ())
    empties = any(column.is_empty() for column in state.columns)
    need = int(getattr(card, "rank", 0) or 0) - 1
    buried_receiver = False
    if need >= 1:
        for column in state.columns:
            face_up = column.face_up
            for index, item in enumerate(face_up):
                if item.rank == need and index != len(face_up) - 1:
                    buried_receiver = True
                    break
            if buried_receiver:
                break
    same_suit = False
    suit = getattr(card, "suit", "")
    for column in state.columns:
        face_up = column.face_up
        for index in range(len(face_up) - 1):
            left, right = face_up[index], face_up[index + 1]
            if left.suit == suit and right.suit == suit and left.rank == right.rank + 1:
                same_suit = True
                break
        if same_suit:
            break
    if actions:
        return "an intermediate sequence left the target cover unchanged"
    if empties and (buried_receiver or same_suit):
        return "an empty column can support a receiver or a same-suit run before the cover falls"
    return ""


def _classify(plan) -> str:
    status = getattr(plan, "status", "") or ""
    stop = getattr(plan, "stop", "") or ""
    if status == "PROVEN_INFEASIBLE_UNDER_EXPLICIT_CONDITIONS":
        return "proved_impossible"
    if status in _EXHAUSTED or stop in _EXHAUSTED:
        return "exhausted_within_bound"
    if status in {"unlocked", "exposed"}:
        return "completed"
    if status == "progress" and int(getattr(plan, "depth_after", 0)) < int(getattr(plan, "depth_before", 0)):
        if stop == "TIME_LIMIT":
            return "resource_limited"
        return "progress"
    if status in _RESOURCE or stop in _RESOURCE:
        return "resource_limited"
    if status in {"temporarily_deferred", "deferred"}:
        return "temporarily_deferred"
    return "resource_limited"


_BUDGETS: Dict[int, BudgetCoordinator] = {}


def register_budget(budget: BudgetCoordinator) -> int:
    key = id(budget)
    _BUDGETS[key] = budget
    return key


def unregister_budget(key: Optional[int]) -> None:
    if key is not None:
        _BUDGETS.pop(int(key), None)


def resolve_budget(lock) -> Optional[BudgetCoordinator]:
    if not isinstance(lock, dict):
        return None
    key = lock.get("budget_key")
    if key is None:
        return None
    return _BUDGETS.get(int(key))
