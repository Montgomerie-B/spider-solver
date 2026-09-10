# Simple Progressive Search v0.24 — FD14 Plateau Boundary Search

## 1. Verdict

`FD14_BOUNDARY_FINDS_NEW_FD13_EXIT` — 16 distinct fd13 boundary class(es) differ from the v0.23 checkpoint

Exact fd14-plateau exploration found a different fd13 door. The v0.10/v0.23 checkpoint is not the only hard-progress exit from fd14.

- Branch: `agent/simple-progressive-fd14-boundary-search-v0-24`
- Base SHA: `cf32569a9826278c5cb3892ff078936aebda8ea8`
- Previous verdict: `LEGACY_FD13_ALTERNATIVES_SYMMETRY_COLLAPSE`
- No new heuristic. No fd13 descent. No buried-stack targeting.

## 2. fd14 root

- path=43 MW=43 fd=14 stock=0 empties=[] run=1
- ordered=`53504b3101000000040a3a2c360835042302310b0d322913050915191b11282d0c2b1a29010a0b1a010c3b2706153423323124162c1c2200081413121d071d223300062d242118341900070d0c2621393c37040c18360a2a280706050403020911033d17000612272a053801000d3d3c3b3a39383726081c251b3300071716352b140925`
- symmetry=`5350533101000000000612272a05380100062d242118341900070d0c2621393c3700071716352b14092500081413121d071d2233000d3d3c3b3a39383726081c251b33010c3b2706153423323124162c1c22040a3a2c360835042302310b0d322913040c18360a2a280706050403020911033d17050915191b11282d0c2b1a29010a0b1a`
- historical match: True

## 3. Face-down census

- col 1: fd=4 fu=10 `c10,d12,c6,s8`
- col 2: fd=5 fu=9 `h5,h9,h11,h1,d8`
- col 3: fd=1 fu=12 `c11`
- col 7: fd=4 fu=12 `h8,c6,s10,d10`

## 4. Root actions

- legal=5 symmetry classes=5
- actions=[[2, 0, 1], [2, 3, 1], [2, 8, 1], [4, 1, 1], [7, 2, 1]]

## 5. Current fd13 exit

- path=101 MW=101 fd=13 empties=[] reveal=`c11`
- ordered=`53504b310100000004083a2c360835042302310b0d1c050515191b11282d0c2b1a2900013b00121413121d071d1c1b1a19181716153433323100022d2c00080d0c262139383706041118360a2a280706050403020911033d3c0b0a290827000812272a0524133201000d3d3c3b3a393837262524232221000b1716352b14092534332201`
- symmetry=`535053310100000000013b00022d2c00080d0c262139383706000812272a0524133201000b1716352b14092534332201000d3d3c3b3a39383726252423222100121413121d071d1c1b1a19181716153433323104083a2c360835042302310b0d1c041118360a2a280706050403020911033d3c0b0a290827050515191b11282d0c2b1a29`

## 6. Search

- unique=1222 expanded=993 generated=6836 dups=2767
- max_depth=80 engine_order_first=True stop=max_new exhausted=False
- empties 0/1/>=2 = 1222/0/0 max_empty=0 max_run=5 max_adj=30 max_blocks=7
- elapsed_s=1.597106300003361 rss_mb=21.81640625
- domain_violations=0

Unbounded last-action LIFO (diagnostic) reached depth 2167 with 1.29M unique
plateau states and zero fd13 exits: a C-move spine starved every reveal parent.
The adopted organisation is engine-order DFS (first legal action first) plus a
backtrack cap of 80, above the known 58-primitive door. That is graph scheduling,
not a Spider heuristic. The historical current door was not re-hit because 16 new
c11 classes appeared on the (2,0,1) frontier first and the harvest cap stopped the run.

## 7. Boundary exits

- exit edges=16 distinct classes=16
- current classes=0 hits=0
- new classes=16
- first current: origin=None depth=None expanded=None unique=None reveal=`None`
- first new: origin=[2, 0, 1] depth=81 cost=124 reveal=`c11` replay=True
- reveal-target counts: {'c11': 16}

## 8. Per-frontier

- origin 0 [2, 0, 1]: expanded=993 unique=1217 generated=6837 dups=2767 max_depth=80 exits=16 current_hits=0 new=16 frontier=224
- origin 1 [2, 3, 1]: expanded=0 unique=1 generated=0 dups=0 max_depth=1 exits=0 current_hits=0 new=0 frontier=1
- origin 2 [2, 8, 1]: expanded=0 unique=1 generated=0 dups=0 max_depth=1 exits=0 current_hits=0 new=0 frontier=1
- origin 3 [4, 1, 1]: expanded=0 unique=1 generated=0 dups=0 max_depth=1 exits=0 current_hits=0 new=0 frontier=1
- origin 4 [7, 2, 1]: expanded=0 unique=1 generated=0 dups=0 max_depth=1 exits=0 current_hits=0 new=0 frontier=1

## 9. Exactly one next recommendation

A genuinely different fd13 checkpoint exists. Next: a fair exact probe of the new boundary class(es) without a new heuristic and without descending from the poisoned current fd13 region.

## Integrity

Verdict FD14_BOUNDARY_FINDS_NEW_FD13_EXIT. new_exits=16 current_hits=0 exhausted=False.

Base SHA `cf32569a9826278c5cb3892ff078936aebda8ea8`. Deal `deals/4925153.txt`.
No new heuristic. No fd13 descent. No column targeting. No production change.

