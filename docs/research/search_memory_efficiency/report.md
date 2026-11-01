# Search memory profile for deal 4925153

The profiled search is the reference suit kernel: opening of deal 4925153, optimise mode, scalar incumbent 158, paid ceiling 157, advice off, no route actions. Both samples stopped on the unique cap. A time or RSS stop would not be labelled fixed work. The 250,000 sample was not run. The 25,000 and 100,000 slopes already name the same retained cost.

Source at measurement: `773d765bd4c417b846f5b3c07807b47bd08a1962`. Python 3.14.5. Windows 11. 8 CPUs. `GlobalMemoryStatusEx` total 16,264.7 MB. One worker. The requested cap was 3,000 MB. The applied cap is the minimum of that request, 8,192 MB, and 40 percent of RAM available at launch. The 25,000 sample applied 3,000 MB. The 100,000 sample applied 2,992.5 MB because less RAM was free. Neither sample approached its cap.

Peak RSS is the Windows peak working set. The search abort uses that peak. The accountant uses `sys.getsizeof` once per object id. Container size is not treated as the whole graph. Current working set was read before the accountant built its id set.

## Commands

```text
py -3 tools/profile_search_memory.py --max-unique 25000 --time-limit 900 --memory-mb 3000 --output docs/research/search_memory_efficiency/profile_25k.json
py -3 tools/profile_search_memory.py --max-unique 100000 --time-limit 1800 --memory-mb 3000 --output docs/research/search_memory_efficiency/profile_100k.json
```

## Fixed-work results

| Sample | Unique | Expanded | Generated | Stale pops | Elapsed s | CPU s | Expansions/s | Peak RSS MB | Accounted MB | RSS bytes/identity |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 25,000 | 25,000 | 2,900 | 46,301 | 287 | 31.843 | 31.766 | 86.282 | 74.16 | 34.99 | 3,110 |
| 100,000 | 100,000 | 15,583 | 269,207 | 1,445 | 157.999 | 157.391 | 98.627 | 208.37 | 144.42 | 2,185 |

From 25,000 to 100,000 the peak working set grew by 134.21 MB, or 1.88 KB per added identity. Accounted bytes grew by 109.43 MB, or 1,529 bytes per added identity. At 100,000 the current working set was 208.37 MB and the unaccounted difference was 74.08 MB. That difference is allocator slack, the interpreter, and the bounded suit census. The census keeps counters, one stratum per foundation/stock key, and five leader records. It does not keep a record per node.

The 100,000 sample reached 4 foundations. Ceiling prunes were 0. Lower-bound events were 34,298, of which 26,272 identities were unretained. `best_g` shared all 100,000 keys with nodes. `seen_expand` held the expanded identities and shared those key objects. `expanded_by_g` and `generated_by_g` are a few kilobytes. No terminal was stored.

## Where the bytes are at 100,000 identities

101,425 node objects were retained for 100,000 identities. The extra nodes are superseded arrivals kept for parent reconstruction. Exclusive `getsizeof`:

| Bucket | Bytes | Share of accounted |
| --- | ---: | ---: |
| Seven heap entry tuples | 66,522,928 | 46.1% |
| Identity packs | 16,927,630 | 11.7% |
| Ordered store packs | 16,927,630 | 11.7% |
| Node `__dict__` | 12,982,400 | 9.0% |
| Action tuples | 6,940,856 | 4.8% |
| Heap lists | 5,606,888 | 3.9% |
| `best_g` table | 5,242,960 | 3.6% |
| Node objects | 4,868,400 | 3.4% |
| Unretained proof-prune packs | 4,415,133 | 3.1% |
| Proof-prune set | 2,097,368 | 1.5% |

Identity and store were distinct objects on every node. 21,416 pairs had equal SPK1 bytes while stock remained. 80,009 identities were SPS1 after stock was empty, with a different ordered SPK1 store. Both packs are required after the stock is empty. Sharing can only remove the stock-present duplicate.

Heap occupancy, summed across the seven lanes:

| | Entries | Share |
| --- | ---: | ---: |
| Live, best g, not yet expanded | 591,521 | 85.4% |
| Already expanded, still sitting on the other lanes | 91,909 | 13.3% |
| Superseded by a cheaper arrival | 9,517 | 1.4% |

Entry size follows the tuple length. Cost keys are 3-tuples at 72 bytes. Four-component lanes are 6-tuples at 96 bytes. Five-component lanes are 7-tuples at 104 bytes. The tie sequence is the penultimate field and the node index is last. Observed component ranges stayed inside a small band: corrected cost 0..141, foundation score down to -4,854, bonds down to -55, face-down cards 7..44, stock rows 0..5.

A stale pop advances the round-robin cursor. Deleting the 15 percent that are not live would change which live node expands next, and it would not remove the main cost. The proof-prune set is telemetry. It does not block a later cheaper arrival. It is real memory, and it will grow if proof rejection grows, but it is not the largest bucket at this depth.

## Decision

Keep the reference representation as the default. Add one opt-in compact representation that does not delete stale entries: a slots node, one shared bytes object when the identity and the ordered pack compare equal, and one integer per heap entry. The integer's high bits are the lane key and its low bits are the same tie sequence. A component outside the recorded limits raises, so an unexpected key cannot silently reorder the search.

A local `heapq` check of 300,000 pushes and pops, outside the solver, took 0.744 s for 7-tuples, 0.667 s for wide integers, and 4.469 s for a pure-Python array heap. The array heap was rejected on that throughput gap. The integer size is 28, 32, or 36 bytes for 30, 60, and 90 bit values. The search comparison, not this check, decides whether the compact form stays on the experiment path.

## Paired comparison

The compact implementation was frozen at `0a34919b4167bb50b9165321e6fe16fb26455ccb` before this comparison. Both arms are the opening ceiling-157 search with no route. Each expansion is hashed. The digests match, so compact is the same frozen suit order. It is not a schedule variant and it is not a proof.

| Work | Arm | Elapsed s | Expansions/s | Peak RSS MB | Accounted MB | Heap entry bytes |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| 25,000 | reference | 32.437 | 89.405 | 74.55 | 34.99 | 16,891,888 |
| 25,000 | compact | 32.699 | 88.689 | 53.35 | 21.09 | 5,924,684 |
| 100,000 | reference | 164.764 | 94.578 | 210.52 | 144.42 | 66,522,928 |
| 100,000 | compact | 162.062 | 96.154 | 125.01 | 91.61 | 23,327,988 |

Unique, expanded, generated, duplicate, stale, lower-bound, and proof-identity counts match on both sizes. Live, already-expanded, and superseded heap counts match. The 100,000 digest is `b93c5aa616d92b33cfc4b6969cf4a10cecfbc1dc001b51ee5289a27b39edf708` for 15,583 expansions. The 25,000 digest is `a741849af9ad734915b6d66cfae9aeaf70d3aadadde39f13db4738d2f6221ca9` for 2,900 expansions.

Repacking the retained reference tuples after the RSS snapshot produces the same integer byte count the compact search measured: 66,522,928 tuple bytes become 23,327,988 integer bytes at 100,000 identities. Compact also shares the 21,416 equal stock-present packs and drops the node dictionaries. Peak RSS falls by 40.6 percent at 100,000 identities. Elapsed time does not get worse.

From 25,000 to 100,000, marginal peak RSS is 1,901 bytes per identity for the reference and 1,002 bytes for compact. A 2,000,000-identity compact search projects to about 1,850 MB before any faster growth of the proof-prune set. The attempt therefore uses compact mode, a 2,000,000 identity cap, a 3,600 second limit, and the launch-time RSS clamp. The reference mode remains the default.

## Bounded opening attempt

The comparison above is the qualifying gain. One compact opening search then used it. The source was clean `fe370509bf726c5025a6056fed1fbaeee0ac3b93`. Python 3.14.5. The launch probe was 8 CPUs, 16,264.7 MB total, 7,396.8 MB available. The applied RSS cap was 2,958.7 MB, the minimum of the 3,000 MB request, 8,192 MB, and 40 percent of available RAM. Authentication replayed the historical 158 only to check the scalar: cost 158, path hash `9145868d32e42008`, `actions_loaded_into_search` false. The search read no route. Advice stayed off. The prefix was empty. Seed 0 was recorded and is not wired into successor order.

```text
py -3 tools/autonomous_solve_campaign.py --mode opening-improve --deal deals/4925153.txt --incumbent-cost 158 --cost-ceiling 157 --authenticate docs/research/autonomous_solve_campaign/4925153_cold_158.moves --time-limit 3600 --max-unique 2000000 --memory-mb 3000 --checkpoint-s 600 --representation compact --status docs/research/search_memory_efficiency/status.json --solution-dir docs/research/search_memory_efficiency
```

The attempt stopped on the time limit at 3,602.502 seconds. It did not stop on the identity cap or the RSS cap.

| Field | Value |
| --- | ---: |
| Unique identities | 1,593,761 |
| Expanded | 467,732 |
| Generated | 7,282,460 |
| Duplicate skips | 3,912,200 |
| Stale skips | 81,695 |
| Lower-bound prunes | 1,475,464 |
| Ceiling prunes | 0 |
| Peak RSS MB | 1,851.96 |
| Max foundations | 5 |
| Min live g | 7 |
| Closed g observation | 6 |

`solved` is false. No complete candidate was written. `replay_ok` is true only for the best unfinished partial, which replays at its recorded cost. `validated` is false. `best_verified_g` is null. `verified_improvement` is `NO_VERIFIED_IMPROVEMENT`. `cold_reproduction` is `NOT_RUN`. The kernel provenance string `imported_verified_complete` is a label, not a proof. `ceiling_is_proof` is false. `exact_frontier_retained` is false. `resume_kind` is `sampled_reseed`.

The deepest replayed unfinished states have 5 foundations, 4 face-down cards, and an empty stock. The leader is corrected cost 145. The milestone is corrected cost 147. Both replay. Neither is a finished game. The saved branches are a sample, not the kernel heap. `min_live_g` 7 and `closed_g` 6 are observations of the remaining heap heads. They do not prove that every route costs at least 7.

The 2,000,000-identity projection of about 1,850 MB was an estimate from the 25,000-to-100,000 slope, before extra proof-prune growth. This run reached 1,593,761 identities at 1,851.96 MB, with 1,475,464 lower-bound prunes, and still had headroom under the 2,958.7 MB clamp. Time, not memory, ended it.

The earlier reference opening attempt, a2 in the accepted method-capture ledger, admitted its 1,200,000-identity cap, expanded 334,452 nodes, ran 2,922.161 seconds, and peaked at 2,440.96 MB. It also reached 5 foundations and did not solve. This compact attempt admitted more identities and expanded more nodes at a lower peak. The time budgets differ, so that pair is context. The order-preserving measurement remains the 25,000 and 100,000 table.

## Tests

After the compact kernel was frozen, the maintained selection was run once: the 31 files in `docs/strategic_continuity_v0_123.md` section 19, plus the later global-search, dependency, witness, cycle-escape, campaign, method-capture, packed-heap, and memory-profile modules. The command was `py -3 -m pytest -p no:cacheprovider` with `PYTHONPATH=src`. Result: 783 passed in 276.34 seconds. `tests/test_human_strategy_v0_120.py::test_a_short_live_solve_shares_probes_and_keeps_the_deep_cap_idle` did not fail in this run. That test can still return `PLANNING_STALL` instead of `TIME_LIMIT` in a full suite, and it was not weakened. Eight modules that fail collection were not in this selection and were not edited.

## Not established

No shorter solution was found. The best verified cost remains 158. The cold reproduction remains the validated 164. Optimality is unproved. The old 1,200,000-identity tree was not shown to be memory-bound: it stopped on its identity cap at 2,441 MB. This attempt also had RSS headroom. Raising the unique cap on the unchanged reference kernel is not the result. Compact mode is the same frozen suit order with a smaller retained graph. No second campaign was started. The accepted method-capture ledger, recipe, and historical 158 and 164 files were not rewritten.

## Erratum: retained heap members

The historical profile JSON files are unchanged. Their raw RSS comparison and the compact benefit remain as recorded. The accountant that produced them charged each reference heap tuple and did not charge the tuple's separately allocated members, notably key and sequence integers.

A review of a 1,000-identity reference frontier found 11,648 such retained member objects, 326,144 bytes, absent from the charged set. Those bytes were inside the unaccounted working-set difference. That difference is therefore not only allocator slack, the interpreter, and the suit census. The sentence in "Fixed-work results" that assigns the whole difference to those three is corrected here.

The accountant now charges each tuple member once by object identity. A value already counted, including an interned small integer shared by many keys, is a shared reference and is not added again. Compact entries are single integers and have no separate retained members. This erratum does not rerun the profile or the one-hour search.
