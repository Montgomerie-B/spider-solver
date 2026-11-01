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

## Not established

These samples do not show a shorter solution. They do not prove the old 1,200,000-identity tree was memory-bound: that run peaked near 2,441 MB under a 3,000 MB request. Raising the unique cap on the reference kernel is not an efficiency result. Optimality remains unproved.
