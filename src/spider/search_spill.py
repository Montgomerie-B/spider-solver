"""Disk copy of a best-first frontier.

The search rules stay in the kernel. This store only keeps identities, nodes,
and a consistent heap snapshot so a prefix can continue after RAM fills.
A snapshot is resumable only when the heaps and the nodes were committed
together. An unfinished transaction rolls back to that snapshot.
"""

from __future__ import annotations

import array
import json
import sqlite3
from pathlib import Path
from typing import Optional


_MISSING = object()
_HOT_LIMIT = 20_000


def _encode_action(action) -> Optional[str]:
    if action is None:
        return None
    return json.dumps(list(action))


def _decode_action(raw: Optional[str]):
    if raw is None:
        return None
    return tuple(json.loads(raw))


def _dump_heap(items: list) -> bytes:
    if not items:
        return b"I"
    if isinstance(items[0], int):
        try:
            raw = bytearray()
            for item in items:
                raw += int(item).to_bytes(16, "little", signed=False)
            return b"I" + bytes(raw)
        except OverflowError:
            pass
    return b"J" + json.dumps(items).encode("utf-8")


def _load_heap(blob: bytes) -> list:
    if not blob or blob == b"I":
        return []
    kind = blob[:1]
    body = blob[1:]
    if kind == b"I":
        return [int.from_bytes(body[i:i + 16], "little", signed=False) for i in range(0, len(body), 16)]
    return list(json.loads(body.decode("utf-8")))


class FrontierSpill:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.con = sqlite3.connect(str(self.path), timeout=60)
        self.con.isolation_level = "DEFERRED"
        self.con.execute("PRAGMA journal_mode=WAL")
        self.con.execute("PRAGMA synchronous=NORMAL")
        self._schema()
        self.hot_nodes: dict = {}
        self.hot_best: dict = {}
        self.hot_expand: dict = {}
        self.hot_pruned: set = set()
        self.hot_limit = _HOT_LIMIT
        self.checkpoint_expanded = -50_000
        self.active = False
        self.resumable = self._meta("resumable") == "1"
        if self.resumable:
            self.node_count = int(self.con.execute("SELECT COUNT(*) FROM nodes").fetchone()[0])
            self.unique = int(self.con.execute("SELECT COUNT(*) FROM best").fetchone()[0])
            self.active = self.node_count > 0
            self.resumable = self.active
        else:
            self.node_count = 0
            self.unique = 0

    def close(self) -> None:
        self.con.close()

    def _schema(self) -> None:
        self.con.execute("CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT)")
        self.con.execute("CREATE TABLE IF NOT EXISTS best (ident BLOB PRIMARY KEY, g INTEGER)")
        self.con.execute("CREATE TABLE IF NOT EXISTS expanded (ident BLOB PRIMARY KEY, g INTEGER)")
        self.con.execute(
            "CREATE TABLE IF NOT EXISTS nodes ("
            "id INTEGER PRIMARY KEY, ident BLOB, store BLOB, g INTEGER, "
            "origin INTEGER, parent INTEGER, action TEXT, depth INTEGER)"
        )
        self.con.execute("CREATE TABLE IF NOT EXISTS pruned (ident BLOB PRIMARY KEY)")
        self.con.execute("CREATE TABLE IF NOT EXISTS blobs (k TEXT PRIMARY KEY, v BLOB)")
        self.con.commit()

    def _meta(self, key: str) -> Optional[str]:
        row = self.con.execute("SELECT v FROM meta WHERE k=?", (key,)).fetchone()
        return None if row is None else str(row[0])

    def _set_meta(self, key: str, value) -> None:
        self.con.execute(
            "INSERT OR REPLACE INTO meta(k, v) VALUES (?, ?)",
            (key, str(value)),
        )

    @classmethod
    def peek(cls, path) -> Optional[dict]:
        candidate = Path(path)
        if not candidate.is_file():
            return None
        con = sqlite3.connect(str(candidate), timeout=30)
        try:
            row = con.execute(
                "SELECT v FROM meta WHERE k='resumable'"
            ).fetchone()
            if row is None or str(row[0]) != "1":
                return {"resumable": False}
            unique = con.execute("SELECT COUNT(*) FROM best").fetchone()
            return {"resumable": True, "unique": int(unique[0])}
        except sqlite3.Error:
            return {"resumable": False}
        finally:
            con.close()

    def activate(self, best_g: dict, nodes: list, seen_expand: dict, pruned: set) -> tuple:
        """Copy a RAM frontier into this file and return the disk views.

        The caller drops the RAM objects after this returns. The heaps are
        checkpointed by the kernel once those views are installed.
        """

        if self.resumable:
            raise RuntimeError("a stored frontier is not replaced")
        self.con.execute("DELETE FROM best")
        self.con.execute("DELETE FROM expanded")
        self.con.execute("DELETE FROM nodes")
        self.con.execute("DELETE FROM pruned")
        self.con.executemany("INSERT INTO best(ident, g) VALUES (?, ?)", best_g.items())
        self.con.executemany(
            "INSERT INTO expanded(ident, g) VALUES (?, ?)",
            seen_expand.items(),
        )
        self.con.executemany(
            "INSERT INTO nodes(id, ident, store, g, origin, parent, action, depth) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                (
                    index,
                    node.ident,
                    node.store,
                    int(node.g),
                    int(node.origin),
                    int(node.parent),
                    _encode_action(node.action),
                    int(node.depth),
                )
                for index, node in enumerate(nodes)
            ),
        )
        if pruned:
            self.con.executemany("INSERT INTO pruned(ident) VALUES (?)", ((item,) for item in pruned))
        self.node_count = len(nodes)
        self.unique = len(best_g)
        self.active = True
        self.hot_nodes.clear()
        self.hot_best.clear()
        self.hot_expand.clear()
        self.hot_pruned.clear()
        return self.best_view(), self.node_view(), self.expand_view(), self.pruned_view()

    def best_view(self):
        return _DiskMap(self, "best", self.hot_best)

    def expand_view(self):
        return _DiskMap(self, "expanded", self.hot_expand)

    def node_view(self):
        return _DiskNodes(self)

    def pruned_view(self):
        return _DiskSet(self)

    def due(self, expanded: int) -> bool:
        return int(expanded) - int(self.checkpoint_expanded) >= 50_000

    def shrink(self) -> None:
        self.hot_nodes.clear()
        self.hot_best.clear()
        self.hot_expand.clear()
        self.hot_pruned.clear()

    def insert_node(self, index: int, node) -> None:
        self.con.execute(
            "INSERT OR REPLACE INTO nodes(id, ident, store, g, origin, parent, action, depth) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                int(index),
                node.ident,
                node.store,
                int(node.g),
                int(node.origin),
                int(node.parent),
                _encode_action(node.action),
                int(node.depth),
            ),
        )

    def fetch_node(self, index: int):
        row = self.con.execute(
            "SELECT ident, store, g, origin, parent, action, depth FROM nodes WHERE id=?",
            (int(index),),
        ).fetchone()
        if row is None:
            raise IndexError(index)
        from spider.search_kernel import CompactSearchNode

        return CompactSearchNode(
            row[0],
            row[1],
            int(row[2]),
            int(row[3]),
            int(row[4]),
            _decode_action(row[5]),
            int(row[6]),
        )

    def note_new_identity(self) -> None:
        self.unique += 1

    def checkpoint(self, heaps: dict, entry_nodes, result) -> None:
        for name, heap in heaps.items():
            self.con.execute(
                "INSERT OR REPLACE INTO blobs(k, v) VALUES (?, ?)",
                (f"heap:{name}", _dump_heap(list(heap))),
            )
        blob = b"" if entry_nodes is None else entry_nodes.tobytes()
        self.con.execute(
            "INSERT OR REPLACE INTO blobs(k, v) VALUES (?, ?)",
            ("entry_nodes", blob),
        )
        self._set_meta("unique", int(result.unique))
        self._set_meta("expanded", int(result.expanded))
        self._set_meta("generated", int(result.generated))
        self._set_meta("duplicate_skips", int(result.duplicate_skips))
        self._set_meta("stale_skips", int(result.stale_skips))
        self._set_meta("lower_bound_prunes", int(result.lower_bound_prunes))
        self._set_meta("proof_prune_identities", int(result.proof_prune_identities))
        self._set_meta("node_count", int(self.node_count))
        self._set_meta("resumable", "1")
        self.con.commit()
        self.resumable = True
        self.checkpoint_expanded = int(result.expanded)

    def load_heaps(self, names) -> tuple:
        heaps = {}
        for name in names:
            row = self.con.execute(
                "SELECT v FROM blobs WHERE k=?",
                (f"heap:{name}",),
            ).fetchone()
            heaps[name] = _load_heap(bytes(row[0]) if row and row[0] is not None else b"I")
        row = self.con.execute("SELECT v FROM blobs WHERE k='entry_nodes'").fetchone()
        entry = array.array("I")
        if row and row[0]:
            entry.frombytes(bytes(row[0]))
        return heaps, entry

    def load_counters(self) -> dict:
        keys = (
            "unique",
            "expanded",
            "generated",
            "duplicate_skips",
            "stale_skips",
            "lower_bound_prunes",
            "proof_prune_identities",
        )
        return {key: int(self._meta(key) or 0) for key in keys}


class _DiskMap:
    def __init__(self, spill: FrontierSpill, table: str, hot: dict):
        self.spill = spill
        self.table = table
        self.hot = hot

    def get(self, key, default=None):
        if key in self.hot:
            return self.hot[key]
        row = self.spill.con.execute(
            f"SELECT g FROM {self.table} WHERE ident=?",
            (key,),
        ).fetchone()
        if row is None:
            return default
        value = int(row[0])
        self.hot[key] = value
        self._trim()
        return value

    def __contains__(self, key) -> bool:
        return self.get(key, _MISSING) is not _MISSING

    def __getitem__(self, key):
        value = self.get(key, _MISSING)
        if value is _MISSING:
            raise KeyError(key)
        return value

    def __setitem__(self, key, value) -> None:
        new = key not in self
        self.hot[key] = int(value)
        self.spill.con.execute(
            f"INSERT OR REPLACE INTO {self.table}(ident, g) VALUES (?, ?)",
            (key, int(value)),
        )
        if new and self.table == "best":
            self.spill.note_new_identity()
        self._trim()

    def __len__(self) -> int:
        if self.table == "best":
            return int(self.spill.unique)
        row = self.spill.con.execute(f"SELECT COUNT(*) FROM {self.table}").fetchone()
        return int(row[0])

    def _trim(self) -> None:
        if len(self.hot) > self.spill.hot_limit:
            self.hot.clear()


class _DiskNodes:
    def __init__(self, spill: FrontierSpill):
        self.spill = spill

    def __len__(self) -> int:
        return int(self.spill.node_count)

    def append(self, node) -> None:
        index = int(self.spill.node_count)
        self.spill.insert_node(index, node)
        self.spill.hot_nodes[index] = node
        self.spill.node_count += 1
        if len(self.spill.hot_nodes) > self.spill.hot_limit:
            self.spill.hot_nodes.clear()

    def __getitem__(self, index: int):
        index = int(index)
        held = self.spill.hot_nodes.get(index)
        if held is not None:
            return held
        node = self.spill.fetch_node(index)
        self.spill.hot_nodes[index] = node
        if len(self.spill.hot_nodes) > self.spill.hot_limit:
            self.spill.hot_nodes.clear()
            self.spill.hot_nodes[index] = node
        return node

    def __iter__(self):
        for index in range(len(self)):
            yield self[index]

    def __setitem__(self, index: int, node) -> None:
        index = int(index)
        self.spill.insert_node(index, node)
        self.spill.hot_nodes[index] = node


class _DiskSet:
    def __init__(self, spill: FrontierSpill):
        self.spill = spill

    def add(self, key) -> None:
        if key in self:
            return
        self.spill.hot_pruned.add(key)
        self.spill.con.execute("INSERT OR IGNORE INTO pruned(ident) VALUES (?)", (key,))

    def __contains__(self, key) -> bool:
        if key in self.spill.hot_pruned:
            return True
        row = self.spill.con.execute(
            "SELECT 1 FROM pruned WHERE ident=?",
            (key,),
        ).fetchone()
        if row is None:
            return False
        self.spill.hot_pruned.add(key)
        return True

    def __iter__(self):
        yielded = set()
        for key in self.spill.hot_pruned:
            yielded.add(key)
            yield key
        for (key,) in self.spill.con.execute("SELECT ident FROM pruned"):
            if key not in yielded:
                yield key
