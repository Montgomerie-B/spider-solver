"""Durable Play Lab history. Rules and scoring belong exclusively to SpiderState.

The save contains the original deal and an append-only action tree, never pickles.
Every node is reconstructed and checked on recovery. Navigation changes a pointer.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from .app_paths import local_app_root
from .cards import Card
from .deal import load_deal, stock_deal_rounds, validate_four_suit_two_deck
from .engine import SpiderState
from .metrics import Action, format_action, parse_moves_file, replay_actions_detailed
from .rules import MW_RULES
from .solution_archive import normalize_actions
from .state_identity import canonical_state_key


def timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def sessions_dir() -> Path:
    return local_app_root() / "PlayLab" / "Sessions"


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def state_digest(state: SpiderState) -> str:
    payload = json.dumps(canonical_state_key(state).to_jsonable(), sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()


@contextmanager
def writer_lock(path: Path):
    """Serialize compare-and-replace; OS releases this lock even after a crash."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_suffix(path.suffix + ".lock").open("a+b") as stream:
        if os.name == "nt":
            import msvcrt
            if stream.seek(0, os.SEEK_END) == 0:
                stream.write(b"0")
                stream.flush()
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            try:
                yield
            finally:
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            try:
                yield
            finally:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def apply_action(state: SpiderState, action: Action) -> int:
    if action == ("deal",):
        return state.deal(rules=MW_RULES)
    return state.move(*action, rules=MW_RULES)


class AutosaveError(OSError):
    """Current work remains in memory; resolve storage failure before continuing."""


@dataclass(frozen=True)
class HistoryNode:
    id: str
    parent: str | None
    action: str | None
    cost: int
    g: int
    ordinal: int
    stock_deals: int
    foundations: int
    face_down: int
    empty_columns: int
    state_hash: str
    created: str
    flips: int = 0
    removals: int = 0


class PlaySession:
    VERSION = 1

    def __init__(self, cards: list[Card], deal_id: str, *, name: str | None = None,
                 path: Path | None = None):
        validate_four_suit_two_deck(cards)
        self.cards = tuple(cards)
        self.deal_id = deal_id
        self.id = uuid4().hex
        self.name = name or f"{deal_id} · {datetime.now():%d %b %H:%M}"
        self.created = timestamp()
        self.path = Path(path) if path else sessions_dir() / f"{deal_id}_{self.id}.json"
        self.nodes: dict[str, HistoryNode] = {}
        self._states: dict[str, SpiderState] = {}
        self.children: dict[str, list[str]] = {}
        self.preferred: dict[str, str] = {}
        self.routes: dict[str, dict] = {}
        self.active_route: str | None = None
        self._disk_digest: str | None = None
        self.dirty = False
        root = self._make_node(None, None, SpiderState.from_cards(list(cards)), 0)
        self.current = root.id
        self.root = root.id
        self.save()

    @classmethod
    def from_deal(cls, deal_path: Path, **kwargs) -> PlaySession:
        return cls(load_deal(deal_path), deal_path.stem, **kwargs)

    @property
    def node(self) -> HistoryNode:
        return self.nodes[self.current]

    @property
    def state(self) -> SpiderState:
        # Callers cannot mutate the cached snapshots.
        return self._states[self.current].clone()

    def _make_node(self, parent: str | None, action: Action | None,
                   state: SpiderState, cost: int, *, node_id=None, created=None):
        prev = self.nodes.get(parent)
        fd = sum(len(c.face_down) for c in state.columns)
        foundations = len(state.foundations)
        node = HistoryNode(
            node_id or uuid4().hex, parent, format_action(action) if action else None,
            cost, (prev.g if prev else 0) + cost, (prev.ordinal + 1) if prev else 0,
            (50 - len(state.stock)) // 10, foundations, fd,
            sum(c.is_empty() for c in state.columns), state_digest(state),
            created or timestamp(), (prev.face_down - fd) if prev else 0,
            (foundations - prev.foundations) if prev else 0,
        )
        self.nodes[node.id] = node
        self._states[node.id] = state
        self.children[node.id] = []
        if parent is not None:
            self.children[parent].append(node.id)
        return node

    def path_ids(self, node_id: str | None = None) -> list[str]:
        ids = []
        cursor = self.current if node_id is None else node_id
        while cursor is not None:
            ids.append(cursor)
            cursor = self.nodes[cursor].parent
        return ids[::-1]

    def actions(self) -> list[Action]:
        return normalize_actions([self.nodes[n].action for n in self.path_ids()[1:]])

    def act(self, action: Action) -> None:
        if self.dirty:
            raise AutosaveError("Save/recover the unsaved action before continuing.")
        state = self.state
        cost = apply_action(state, action)  # illegal actions have no side effects
        line = format_action(action)
        child = next((n for n in self.children[self.current]
                      if self.nodes[n].action == line), None)
        if child is None:
            child = self._make_node(self.current, action, state, cost).id
        self.preferred[self.current] = child
        self.current = child
        self.save()

    def goto(self, node_id: str) -> None:
        if self.dirty:
            raise AutosaveError("Save/recover the unsaved action before navigating.")
        if node_id not in self.nodes:
            raise ValueError("Unknown history node")
        ids = self.path_ids(node_id)
        for parent, child in zip(ids, ids[1:]):
            self.preferred[parent] = child
        self.current = node_id
        self.save()

    def undo(self) -> None:
        self.goto(self.node.parent or self.root)

    def redo(self, child: str | None = None) -> None:
        choices = self.children[self.current]
        child = child or self.preferred.get(self.current) or (choices[0] if choices else None)
        if child is not None:
            if child not in choices:
                raise ValueError("Redo target is not a child")
            self.goto(child)

    def load_solution(self, path: Path) -> str:
        if self.dirty:
            raise AutosaveError("Save/recover before importing a solution.")
        actions = parse_moves_file(path)
        state = SpiderState.from_cards(list(self.cards))
        snapshots = []
        for index, action in enumerate(actions, 1):
            try:
                cost = apply_action(state, action)
            except ValueError as exc:
                raise ValueError(f"Solution action {index}: {exc}") from exc
            snapshots.append((state.clone(), cost))
        # Only attach the route after the entire import passes legality checking.
        parent = self.root
        ids = [parent]
        for action, (snapshot, cost) in zip(actions, snapshots):
            child = next((n for n in self.children[parent]
                          if self.nodes[n].action == format_action(action)), None)
            if child is None:
                child = self._make_node(parent, action, snapshot, cost).id
            self.preferred[parent] = child
            ids.append(child)
            parent = child
        route_id = uuid4().hex
        self.routes[route_id] = {"name": path.name, "source": str(path), "nodes": ids}
        self.active_route = route_id
        self.current = self.root
        self.save()
        return route_id

    def route_position(self) -> tuple[dict | None, int, bool]:
        route = self.routes.get(self.active_route)
        if route is None:
            return None, 0, False
        common = 0
        ids = self.path_ids()
        for a, b in zip(ids, route["nodes"]):
            if a != b:
                break
            common += 1
        return route, common - 1, self.current not in route["nodes"]

    def expected_action(self) -> Action | None:
        route, index, branched = self.route_position()
        if route and not branched and index + 1 < len(route["nodes"]):
            return normalize_actions([self.nodes[route["nodes"][index + 1]].action])[0]
        return None

    def next(self) -> None:
        route, index, branched = self.route_position()
        if route and not branched and index + 1 < len(route["nodes"]):
            self.goto(route["nodes"][index + 1])
        else:
            self.redo()

    def last(self) -> None:
        route, _, branched = self.route_position()
        target = self.current
        if route and not branched:
            target = route["nodes"][-1]
        else:
            while self.children[target]:
                target = self.preferred.get(target, self.children[target][0])
        self.goto(target)

    def future_stock(self):
        return list(enumerate(stock_deal_rounds(self.state.stock), self.node.stock_deals + 1))

    def document(self) -> dict:
        return {"version": self.VERSION, "id": self.id, "name": self.name,
                "deal_id": self.deal_id, "created": self.created, "updated": timestamp(),
                "cards": [str(c) for c in self.cards], "root": self.root,
                "current": self.current, "nodes": [asdict(n) for n in self.nodes.values()],
                "preferred": self.preferred, "routes": self.routes,
                "active_route": self.active_route, "rules": "MW_RULES_corrected_v1"}

    def save(self, path: Path | None = None) -> None:
        destination = Path(path) if path else self.path
        try:
            with writer_lock(destination):
                if destination == self.path and destination.exists():
                    old = destination.read_bytes()
                    if hashlib.sha256(old).hexdigest() != self._disk_digest:
                        raise OSError("Session changed in another window. Save a recovery copy.")
                    atomic_write(destination.with_suffix(".json.bak"), old.decode("utf-8"))
                text = json.dumps(self.document(), indent=2, ensure_ascii=False) + "\n"
                atomic_write(destination, text)
            self.path = destination
            self._disk_digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
            self.dirty = False
        except OSError as exc:
            self.dirty = True
            raise AutosaveError(f"Autosave failed; work is still in memory: {exc}") from exc

    @classmethod
    def load(cls, path: Path) -> PlaySession:
        raw = path.read_bytes()
        data = json.loads(raw)
        if data["version"] != cls.VERSION or data["rules"] != "MW_RULES_corrected_v1":
            raise ValueError("Unsupported session or rules version")
        self = cls.__new__(cls)
        self.cards = tuple(Card.parse(c) for c in data["cards"])
        validate_four_suit_two_deck(list(self.cards))
        for key in ("id", "name", "deal_id", "created", "root", "current", "active_route"):
            setattr(self, key, data[key])
        self.nodes, self._states, self.children = {}, {}, {}
        for stored in data["nodes"]:
            parent = stored["parent"]
            if stored["id"] in self.nodes:
                raise ValueError("Duplicate history node")
            if parent is None:
                if self.nodes or stored["id"] != self.root or stored["action"] is not None:
                    raise ValueError("Invalid history root")
                state = SpiderState.from_cards(list(self.cards))
                action, cost = None, 0
            else:
                if parent not in self.nodes:
                    raise ValueError("History parent missing or out of order")
                state = self._states[parent].clone()
                action = normalize_actions([stored["action"]])[0]
                cost = apply_action(state, action)
            node = self._make_node(parent, action, state, cost,
                                   node_id=stored["id"], created=stored["created"])
            if asdict(node) != stored:
                raise ValueError(f"History integrity check failed at action {node.ordinal}")
        if self.current not in self.nodes:
            raise ValueError("Missing current history position")
        self.preferred, self.routes = data["preferred"], data["routes"]
        for parent, child in self.preferred.items():
            if child not in self.children.get(parent, []):
                raise ValueError("Invalid redo edge")
        for route in self.routes.values():
            if not route["nodes"] or self.path_ids(route["nodes"][-1]) != route["nodes"]:
                raise ValueError("Invalid replay route")
        if self.active_route is not None and self.active_route not in self.routes:
            raise ValueError("Missing active route")
        self.path, self.dirty = path, False
        self._disk_digest = hashlib.sha256(raw).hexdigest()
        return self

    def export(self, path: Path) -> dict:
        if not (path.name.endswith(".moves") or path.name.endswith(".moves.txt")):
            raise ValueError("Export filename must end with .moves or .moves.txt")
        actions = self.actions()
        fresh = SpiderState.from_cards(list(self.cards))
        counters = replay_actions_detailed(fresh, actions)
        if counters["mobilityware_moves"] != self.node.g or state_digest(fresh) != self.node.state_hash:
            raise ValueError("Independent replay verification FAILED: state or MW cost mismatch")
        if self.state.is_solved() != fresh.is_solved():
            raise ValueError("Independent replay verification FAILED: solved mismatch")
        report = {**counters, "solved": fresh.is_solved(), "foundations": len(fresh.foundations),
                  "verified": True, "session_id": self.id, "node_id": self.current,
                  "deal_id": self.deal_id, "state_hash": state_digest(fresh)}
        body = "# Spider Play Lab — independently replay-verified current line\n"
        body += "\n".join(format_action(a) for a in actions) + "\n"
        # Never overwrite the only session with an exported moves file.
        if path.resolve() == self.path.resolve() or path.with_suffix(".json").resolve() == self.path.resolve():
            raise ValueError("Choose an export name different from the session file")
        atomic_write(path, body)
        atomic_write(path.with_suffix(".json"), json.dumps(
            {**self.document(), "verification": report}, indent=2, ensure_ascii=False) + "\n")
        return report
