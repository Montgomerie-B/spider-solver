"""Account retained search memory without copying the frontier.

``sys.getsizeof`` of a container is recorded as the container only.
Payload bytes are charged once per object identity, so a pack shared by a
node, ``best_g`` and ``seen_expand`` is not counted three times.
"""

from __future__ import annotations

import sys
from typing import Dict, Optional

from spider.packed_heap import unpack_lane_key


def _charge(obj, bucket: str, seen: set, buckets: Dict[str, int]) -> int:
    marker = id(obj)
    if marker in seen:
        buckets[bucket + "_shared_refs"] = buckets.get(bucket + "_shared_refs", 0) + 1
        return 0
    seen.add(marker)
    size = int(sys.getsizeof(obj))
    buckets[bucket] = buckets.get(bucket, 0) + size
    buckets[bucket + "_objects"] = buckets.get(bucket + "_objects", 0) + 1
    return size


def account_retained(diagnostics: dict, *, ceiling: Optional[int]) -> dict:
    """Summarise one finished kernel. The caller drops ``diagnostics`` afterwards."""

    nodes = diagnostics["nodes"]
    best_g = diagnostics["best_g"]
    heaps = diagnostics["heaps"]
    seen_expand = diagnostics["seen_expand"]
    pruned = diagnostics["pruned_identities"]
    seen: set = set()
    buckets: Dict[str, int] = {}

    same_object = 0
    equal_payload = 0
    different_payload = 0
    ident_spk1 = 0
    ident_sps1 = 0
    store_bytes = 0
    ident_bytes = 0
    for node in nodes:
        _charge(node, "node_object", seen, buckets)
        node_dict = getattr(node, "__dict__", None)
        if isinstance(node_dict, dict):
            _charge(node_dict, "node_dict", seen, buckets)
        ident = node.ident
        store = node.store
        ident_bytes += len(ident)
        store_bytes += len(store)
        if ident.startswith(b"SPK1"):
            ident_spk1 += 1
        elif ident.startswith(b"SPS1"):
            ident_sps1 += 1
        if ident is store:
            same_object += 1
        elif ident == store:
            equal_payload += 1
        else:
            different_payload += 1
        _charge(ident, "identity_bytes", seen, buckets)
        _charge(store, "store_bytes", seen, buckets)
        for scalar in (node.g, node.origin, node.parent, node.depth):
            _charge(scalar, "node_scalar", seen, buckets)
        if node.action is not None:
            _charge(node.action, "action_tuple", seen, buckets)
            for part in node.action:
                _charge(part, "action_part", seen, buckets)
    _charge(nodes, "node_list", seen, buckets)
    _charge(best_g, "best_g_dict", seen, buckets)
    best_shared = 0
    best_exclusive = 0
    for ident in best_g:
        if id(ident) in seen:
            best_shared += 1
        else:
            best_exclusive += 1
            _charge(ident, "best_g_exclusive_key", seen, buckets)
    _charge(seen_expand, "seen_expand_dict", seen, buckets)
    expand_shared = 0
    expand_exclusive = 0
    for ident in seen_expand:
        if id(ident) in seen:
            expand_shared += 1
        else:
            expand_exclusive += 1
            _charge(ident, "seen_expand_exclusive_key", seen, buckets)
    for mapping_name in ("expanded_by_g", "generated_by_g"):
        mapping = diagnostics.get(mapping_name)
        if isinstance(mapping, dict):
            _charge(mapping, mapping_name, seen, buckets)
            for key, value in mapping.items():
                _charge(key, mapping_name + "_key", seen, buckets)
                _charge(value, mapping_name + "_value", seen, buckets)
    terminals = diagnostics.get("terminals") or []
    if isinstance(terminals, list):
        _charge(terminals, "terminal_list", seen, buckets)
        for terminal in terminals:
            if isinstance(terminal, dict):
                _charge(terminal, "terminal_record", seen, buckets)
                for key, value in terminal.items():
                    _charge(key, "terminal_field", seen, buckets)
                    _charge(value, "terminal_field", seen, buckets)
    _charge(pruned, "pruned_set", seen, buckets)
    pruned_shared = 0
    pruned_exclusive = 0
    pruned_exclusive_payload = 0
    for ident in pruned:
        if id(ident) in seen:
            pruned_shared += 1
        else:
            pruned_exclusive += 1
            pruned_exclusive_payload += len(ident)
            _charge(ident, "pruned_exclusive_key", seen, buckets)

    entry_nodes = diagnostics.get("entry_nodes")
    seq_mask = diagnostics.get("seq_mask")
    if entry_nodes is not None:
        _charge(entry_nodes, "entry_nodes", seen, buckets)
    lanes = {}
    heap_entries = 0
    live_entries = 0
    superseded_entries = 0
    expanded_entries = 0
    for name, heap in heaps.items():
        _charge(heap, "heap_list", seen, buckets)
        lane_live = 0
        lane_superseded = 0
        lane_expanded = 0
        key_length = None
        entry_bytes = 0
        component_min: list = []
        component_max: list = []
        seq_min = None
        seq_max = None
        for entry in heap:
            entry_bytes += _charge(entry, "heap_entry", seen, buckets)
            if isinstance(entry, tuple):
                key_parts = entry[:-2]
                seq = int(entry[-2])
                node_i = entry[-1]
            elif isinstance(entry, int) and entry_nodes is not None and seq_mask is not None:
                seq = int(entry) & int(seq_mask)
                node_i = int(entry_nodes[seq])
                key_parts = unpack_lane_key(name, int(entry))[0]
            else:
                continue
            if key_length is None:
                key_length = len(key_parts)
            for index, component in enumerate(key_parts):
                if index >= len(component_min):
                    component_min.append(int(component))
                    component_max.append(int(component))
                else:
                    component_min[index] = min(component_min[index], int(component))
                    component_max[index] = max(component_max[index], int(component))
            seq_min = seq if seq_min is None else min(seq_min, seq)
            seq_max = seq if seq_max is None else max(seq_max, seq)
            node = nodes[node_i]
            g = int(node.g)
            best = best_g.get(node.ident)
            expanded_at = seen_expand.get(node.ident)
            if best is None or g != int(best) or (ceiling is not None and g > int(ceiling)):
                lane_superseded += 1
            elif expanded_at is not None and int(expanded_at) <= g:
                lane_expanded += 1
            else:
                lane_live += 1
        lanes[name] = {
            "entries": len(heap),
            "live": lane_live,
            "superseded": lane_superseded,
            "already_expanded": lane_expanded,
            "key_length": key_length,
            "key_component_min": component_min,
            "key_component_max": component_max,
            "seq_min": seq_min,
            "seq_max": seq_max,
            "entry_bytes": entry_bytes,
            "list_bytes": sys.getsizeof(heap),
        }
        heap_entries += len(heap)
        live_entries += lane_live
        superseded_entries += lane_superseded
        expanded_entries += lane_expanded

    accounted = sum(
        amount
        for key, amount in buckets.items()
        if not key.endswith("_objects") and not key.endswith("_shared_refs")
    )
    node_count = len(nodes)
    return {
        "schema": "spider-search-memory-profile-27",
        "accounting": "exclusive_getsizeof_by_object_id",
        "node_count": node_count,
        "ident_same_object_as_store": same_object,
        "ident_equal_payload_distinct_object": equal_payload,
        "ident_different_payload": different_payload,
        "ident_spk1": ident_spk1,
        "ident_sps1": ident_sps1,
        "identity_payload_bytes": ident_bytes,
        "store_payload_bytes": store_bytes,
        "best_g_keys": len(best_g),
        "best_g_keys_shared_with_node": best_shared,
        "best_g_keys_exclusive": best_exclusive,
        "seen_expand_keys": len(seen_expand),
        "seen_expand_keys_shared": expand_shared,
        "seen_expand_keys_exclusive": expand_exclusive,
        "pruned_identities": len(pruned),
        "pruned_shared_with_retained": pruned_shared,
        "pruned_exclusive": pruned_exclusive,
        "pruned_exclusive_payload_bytes": pruned_exclusive_payload,
        "heap_entries": heap_entries,
        "live_heap_entries": live_entries,
        "superseded_heap_entries": superseded_entries,
        "already_expanded_heap_entries": expanded_entries,
        "lanes": lanes,
        "buckets": buckets,
        "accounted_bytes": accounted,
        "accounted_bytes_per_node": None if node_count == 0 else round(accounted / node_count, 2),
    }
