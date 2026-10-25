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
# 4,500 nodes remains available. Its deadline is the proposal slice, not the
# historical 12 seconds. deep_share also caps a deep probe at a fraction of
# the time still left on the global clock.
DERIVATION = (
    "First cap 160 nodes and 0.28s from the v0.119 48-node exhausted graphs "
    "and the 2,000-node/3s probes. Middle cap 800 nodes and 0.55s from partials "
    "that were still reducing cover below 1,151 nodes. Deep cap 4,500 nodes, "
    "the existing excavation capability, with a 1.25s deadline and a 0.15 share "
    "of the remaining global time. The proposal slice is 1.25s so one objective "
    "cannot spend the historical 12s monopoly."
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
                return _Grant("search", first)
            self.identical_skips += 1
            self.deferred += 1
            self.pending_deepen = False
            self._count("temporarily_deferred")
            self.events.append(
                f"budget: deferred {objective} on an unchanged board at {record.allowance_nodes} nodes; "
                "still eligible when the board or the allowance changes"
            )
            return _Grant("defer")
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
        )
        self.records[(state_key, str(objective))] = record
        self.open_partials = [
            item for item in self.open_partials if not (item.objective == record.objective and item.card is card)
        ]
        if useful and self.limits.next_after(allowance.max_nodes) is not None:
            self.open_partials.append(record)

    def take_deepen(self, time_left: float) -> Optional[_DeepGrant]:
        """One larger probe after every target in this proposal had its cheap turn."""

        if self._deepen_taken or self.viable_alternative or not self.open_partials:
            return None
        if not self._deepen_allowed(time_left):
            self.deferred += 1
            self.pending_deepen = True
            self._count("temporarily_deferred")
            self.events.append(
                "budget: deferred a promising partial so another strategic line can run"
            )
            return None
        record = self.open_partials.pop(0)
        nxt = self.limits.next_after(record.allowance_nodes)
        if nxt is None:
            return None
        self._deepen_taken = True
        self.pending_deepen = False
        self.deepened += 1
        self.revisited += 1
        clipped = self.clip(nxt.deadline_s, time_left, deep=True)
        granted = Allowance(nxt.level, nxt.max_cost, nxt.max_nodes, clipped)
        self.events.append(
            f"budget: deepen {record.objective} to {granted.max_nodes} nodes "
            f"with {granted.deadline_s:.2f}s inside the global deadline"
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

        if self.pending_deepen or self.open_partials:
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
            "limits": self.limits.as_dict(),
        }


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
