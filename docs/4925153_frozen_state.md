# Deal 4925153 — Current Project State (August 2026)

## Authoritative status

Deal 4925153 remains the primary development benchmark, but the forward solver architecture is explicitly deal-independent.

- **Verified replayable incumbent:** 172 corrected MobilityWare moves.
- **Source:** original user-supplied complete trace in `solutions/4925153_canonical.moves`.
- **Trace contents:** 169 tableau moves, 5 stock deals, 174 explicit commands.
- **Solved:** yes; 8 foundations completed and stock exhausted.
- **Project-generated complete solution below 172:** none yet.
- **User historical leaderboard best:** 167.
- **Other leaderboard evidence:** 154.
- **Leaderboard best:** 119.

The MobilityWare leaderboard screenshot labels the same benchmark as Deal #492515. The repository retains its historical internal identifier `4925153` until a deliberate repository-wide rename is undertaken.

The 119 score is treated as credible evidence that a radically shorter legal route exists. It is benchmark evidence, not a hard-coded solver rule.

## Move-accounting correction

A previously reported 163-move result is withdrawn. No distinct 163-move sequence exists.

The legacy function `mw_move_cost` incorrectly assigned zero cost whenever a move transferred the entire face-up stack to an empty column, even when face-down cards remained beneath that stack.

The verified MobilityWare rule treats a move as free only when it relocates an entire fully open column to an empty column — the source has no face-down cards remaining.

For the canonical trace:

- explicit commands: 174
- verified free full-column relocations: 2
- corrected MobilityWare total: 172

Automatic foundation removals cost zero. All five stock deals cost one.

`legacy_mw` is retained only for forensic compatibility and must never be used for search, pruning, ranking, incumbent comparison or benchmark claims.

See `docs/4925153_move_accounting_incident.md`.

## Durable solution archive

Every future complete candidate must pass the central archive pipeline:

1. replay independently from the true initial deal;
2. verify legality, solved state, foundations and stock;
3. recalculate corrected `mobilityware_moves`;
4. compare strictly against the independently verified incumbent;
5. write immutable history and current-best files atomically;
6. read the move file back and replay it again.

Default external archive:

`C:\SpiderSolver\solutions\4925153`

A solver improvement does not operationally exist until the distinct move sequence has been independently replayed and successfully stored in the external archive.

See `docs/solution_archive.md`.

## Reusable infrastructure

The following capabilities are valid and should be reused:

- rule-accurate replay and corrected MobilityWare accounting;
- canonical state reconstruction and structural hashing;
- transposition/checkpoint support;
- collision-safe exact state identity;
- zero-cost free-column quotienting;
- algebraic quotient expansion;
- packed state representation;
- exact corrected-cost corridor search;
- hybrid/legacy move ordering where useful;
- layered-planner dependency, campaign, scorer, realizer and controller experiments;
- durable incumbent capture and read-back verification.

These are implementation assets. They no longer define the high-level strategy by themselves.

## Exact corridor findings

The mispriced-reveal hypothesis has been extensively tested under corrected accounting.

Exact local one-move optimisation corridors have been closed around:

- commands 26-32 (reveal 29);
- commands 43-51 (reveals 43/47/51);
- commands 96-101 (reveal 99);
- commands 126-132 (reveal 129);
- commands 147-151 (reveal 150).

For commands 69-79, exact search has exhausted ceilings through corrected cost 9 with no target. The remaining one-move saving would require a cost-10 search, whose naive projection was not justified by its expected runtime.

These negative results are genuine closures of the natural local-substitution hypothesis. They should not be reopened without new structural evidence or materially stronger admissible search machinery.

## Strategic conclusion

The project is no longer treating local optimisation of the 172 route as the main programme.

The leaderboard evidence (172 replayed project route, user 167, another 154, best 119) strongly suggests that the major remaining opportunity is strategic rather than a collection of isolated one-move substitutions.

The forward architecture is therefore an **anytime perfect-information solver**:

`analyse -> generate strategic options -> realise tactics -> first solve -> improve -> tighten bounds -> prove`

The canonical human route remains valuable as:

- a verified incumbent;
- a sequence of successful states and suffixes;
- diagnostic evidence about human play;
- a reconnection scaffold for selected optimisation searches.

It is not assumed to resemble the optimal route.

## Current development direction

The authoritative forward documents are:

- `docs/anytime_solver_architecture.md`
- `docs/anytime_solver_development_plan.md`

The immediate development sprint is **generic foundation-removal feasibility analysis**.

For any deal/state, the analyser should determine:

- earliest stock epoch in which each of the two foundations of each suit is theoretically possible, based on card availability;
- foundations that are impossible before later stock rows for hard availability reasons;
- practical build-readiness versus removal-readiness from the current tableau;
- required buried cards and dependency chains;
- existing same-suit fragments and blockers;
- likely empty-column requirements;
- strategic value of removal now versus consolidation for later.

The output is a dynamic **removal frontier**, not a fixed suit order.

This will then be combined with:

1. downstream reveal/dependency analysis;
2. empty-column lifecycle and recoverability;
3. exact known-stock reception analysis;
4. a generic admissible lower-bound API;
5. strategic objective generation;
6. tactical realisation using the existing exact quotient engine;
7. an anytime controller that finds a first solution quickly and then improves it continuously.

## Benchmark milestones

These are diagnostics for this deal, not generic solver rules:

- any solver-generated complete solution from scratch;
- <=172;
- <172 — first genuine project improvement;
- <=167 — reach the user's historical level;
- <=154 — demonstrate materially stronger strategic play;
- approach/reach 119.

Long-term success is not defined by this one deal alone. Strategic changes must also improve or remain sound on unseen Spider deals.

---

*Last updated: 13 August 2026.*
