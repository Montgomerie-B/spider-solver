# First-Foundation Conversion Funnel v0.1

## 1. Verdict

`FOUNDATION_RETENTION_LOSS_CONFIRMED` — 17 replayable treatment successors produced only 5 retained project-progress admissions; exact TT and candidate deduplication are the earliest demonstrated loss gates.

## 2. Existing foundation execution path

Fresh campaign analysis builds a dependency graph and tactical portfolio. `CAMPAIGN_CURRENT_EPOCH` is consumed by `_foundation_successors`, allocated through `TacticalResourceAllocator.request`, and invokes the unchanged `realize_campaign_to_next_epoch`; terminal paths use the unchanged terminal assembly/removal realisers and the rules engine performs complete-sequence removal.

## 3. Demand-gap code audit

1. The intended realiser is `realize_campaign_to_next_epoch` (`foundation_campaign_realizer.py:567`), entered by `_foundation_successors`.
2. Its unlocking demand is the existing `CAMPAIGN_CURRENT_EPOCH` kind (`tactical_resource_allocator.py:45`).
3. At the base SHA, no production demand-derivation function emitted that kind; `_resource_demand` could synthesize it only for compatibility execution without tactical allocation.
4. Allocated StrategicProject execution uses `_explicit_resource_demand` (`anytime_controller.py:5802`), so it could not emit or request the missing kind normally.
5. This is accidental expressibility wiring: the realiser, compatibility fallback, eligibility facts, and allocator contract already existed. Exact locations are also recorded in the JSON audit object.

## 4. Funnel definition

F0–F14 preserve the requested distinctions. Events are de-duplicated by stage, project, campaign, exact-state digest, registry-request digest, exact action-prefix digest, and demand/realiser detail. Drop events use the bounded taxonomy in the result JSON.

## 5. Baseline funnel results

- P0: F7_REPLAYABLE_PROGRESS_RETURNED; demands {'CAMPAIGN_REMOVAL': 2, 'DEPENDENCY_CLOSURE': 2}; realisers {'DEPENDENCY_CLOSURE': 2}.
- P2: F9_PROJECT_CONTINUATION_SERVICED; demands {'CAMPAIGN_REMOVAL': 8, 'DEPENDENCY_CLOSURE': 8}; realisers {'DEPENDENCY_CLOSURE': 8}.
- P7: F8_PROGRESS_RETAINED; demands {'CAMPAIGN_REMOVAL': 7, 'DEPENDENCY_CLOSURE': 7}; realisers {'DEPENDENCY_CLOSURE': 7}.
Aggregate: demands=34, grants=17, realiser calls=17, replayable/retained/serviced=17/4/1.

## 6. Minimal treatment

For the selected live StrategicProject campaign only, an existing actionable critical-path entry now emits the existing `CAMPAIGN_CURRENT_EPOCH` demand at PROBE tier. The allocator, tier budgets, realiser, priorities, proof contracts, and production defaults are unchanged.

## 7. Treatment funnel results

- P0: F7_REPLAYABLE_PROGRESS_RETURNED; demands {'CAMPAIGN_CURRENT_EPOCH': 2, 'CAMPAIGN_REMOVAL': 2, 'DEPENDENCY_CLOSURE': 2}; realisers {'DEPENDENCY_CLOSURE': 2}.
- P2: F9_PROJECT_CONTINUATION_SERVICED; demands {'CAMPAIGN_CURRENT_EPOCH': 8, 'CAMPAIGN_REMOVAL': 8, 'DEPENDENCY_CLOSURE': 8}; realisers {'DEPENDENCY_CLOSURE': 8}.
- P7: F8_PROGRESS_RETAINED; demands {'CAMPAIGN_CURRENT_EPOCH': 7, 'CAMPAIGN_REMOVAL': 7, 'DEPENDENCY_CLOSURE': 7}; realisers {'DEPENDENCY_CLOSURE': 7}.
Aggregate: demands=51 including 17 current-epoch demands; grants=17; realiser calls=17 (all dependency closure); replayable/retained/serviced=17/5/1.

## 8. First-foundation replay

- P0: no F14 endpoint.
- P2: no F14 endpoint.
- P7: no F14 endpoint.

## 9. Earliest causal blocker

17 replayable treatment successors produced only 5 retained project-progress admissions; exact TT and candidate deduplication are the earliest demonstrated loss gates. No second blocker was repaired.
Observed treatment drops: {'TT_DOMINATED': 8, 'SUCCESSOR_DEDUP_DROPPED': 4, 'REALISER_NO_RESULT': 1}. The bridge exposed no terminal-ready state and no removal request.

## 10. Project activity versus conversion

- P0 treatment: projects=2, service=2, semantic progress=0, activity without progress=2; retained=0, serviced=0.
- P2 treatment: projects=4, service=10, semantic progress=1, activity without progress=9; retained=3, serviced=1.
- P7 treatment: projects=4, service=7, semantic progress=1, activity without progress=6; retained=2, serviced=0.

## 11. Integrity/runtime

- P0: replay A/B=True/True; handle errors A/B=0/0; runtime ratio=0.977; tactical ratio=0.975.
- P2: replay A/B=True/True; handle errors A/B=0/0; runtime ratio=0.755; tactical ratio=0.926.
- P7: replay A/B=True/True; handle errors A/B=0/0; runtime ratio=0.997; tactical ratio=0.976.
Post-run review found the original F8 observer immediately after, rather than inside, the successor loop. Search behavior and the exact F7/drop observations were unaffected. The hook is corrected; reported F8/F9 rows were rebuilt deterministically from each exact F7 endpoint, its adjacent dedup/TT drop record, the matching F1 child-request digest, and later selected F2 service. No metrics from different trajectories were combined.

## 12. One next bounded task

Audit exact-state project-intent coalescing for F7 successors: when TT admission or candidate deduplication finds an equal state, determine whether the same-campaign continuation subscriber is transferred to the already retained registry request; test one bounded transfer only if that ownership gap is confirmed, changing no TT rule, priority, or budget.
