"""Spatial memory navigator for O0's Synaptic Vault Architecture.

Implements graph-based navigation across Stations (Priority 10),
Quick Paths, and Equidistant Midpoints (Priority 5) for ultra-fast,
priority-ordered context retrieval without exhaustive full-vault scans.
"""
from __future__ import annotations

import heapq
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_FM_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def _parse_frontmatter(text: str) -> dict[str, Any]:
    m = _FM_RE.match(text)
    if not m:
        return {}
    fm: dict[str, Any] = {}
    for line in m.group(1).splitlines():
        if ":" not in line:
            continue
        k, _, v = line.partition(":")
        k = k.strip()
        v = v.strip()
        if not k:
            continue
        if v.startswith("[") and v.endswith("]"):
            fm[k] = [x.strip().strip("'\"") for x in v[1:-1].split(",") if x.strip()]
        else:
            try:
                fm[k] = int(v) if v.isdigit() else v.strip("'\"")
            except Exception:
                fm[k] = v.strip("'\"")
    return fm


@dataclass
class VaultNode:
    name: str
    path: str
    station: str
    priority: int  # 1 to 10
    quick_paths: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    content: str = ""


class SpatialVaultNavigator:
    """Graph navigator for Obsidian memory vault using Quick Paths and Priority gradients."""

    def __init__(self, vault_root: Path | str):
        self.vault_root = Path(vault_root)
        self.nodes: dict[str, VaultNode] = {}
        self.station_map: dict[str, list[str]] = {}

    def index_vault(self) -> dict[str, Any]:
        """Scan vault markdown notes and build the synaptic routing graph."""
        self.nodes.clear()
        self.station_map.clear()

        if not self.vault_root.exists():
            return {"indexed": 0, "stations": 0}

        for md_file in self.vault_root.rglob("*.md"):
            try:
                text = md_file.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue

            fm = _parse_frontmatter(text)
            node_name = md_file.stem
            priority = int(fm.get("priority", 5))
            station = str(fm.get("station", "GENERAL")).upper()
            quick_paths = fm.get("quick_paths", [])
            if isinstance(quick_paths, str):
                quick_paths = [quick_paths]
            tags = fm.get("tags", [])
            if isinstance(tags, str):
                tags = [tags]

            body = _FM_RE.sub("", text).strip()

            node = VaultNode(
                name=node_name,
                path=str(md_file),
                station=station,
                priority=priority,
                quick_paths=quick_paths,
                tags=tags,
                content=body,
            )
            self.nodes[node_name] = node
            self.station_map.setdefault(station, []).append(node_name)

        return {"indexed": len(self.nodes), "stations": len(self.station_map)}

    def get_station_core(self, station_name: str) -> VaultNode | None:
        """Find the Priority 10 core hub for a station."""
        station_name = station_name.upper()
        candidates = self.station_map.get(station_name, [])
        for name in candidates:
            node = self.nodes.get(name)
            if node and node.priority == 10:
                return node
        return None

    def route_quick_path(self, from_node: str, to_node: str) -> list[str]:
        """Find the shortest hop sequence between two nodes along Quick Paths."""
        if from_node not in self.nodes or to_node not in self.nodes:
            return []

        # Shortest path using BFS
        queue: list[tuple[str, list[str]]] = [(from_node, [from_node])]
        visited = {from_node}

        while queue:
            curr, path = queue.pop(0)
            if curr == to_node:
                return path

            curr_node = self.nodes[curr]
            for neighbor in curr_node.quick_paths:
                if neighbor in self.nodes and neighbor not in visited:
                    visited.add(neighbor)
                    queue.append((neighbor, path + [neighbor]))

        return []

    def priority_search(
        self,
        keywords: list[str],
        min_priority: int = 5,
        target_station: str | None = None,
        limit: int = 5,
    ) -> list[VaultNode]:
        """Fast priority-filtered lookup: evaluates highest priority nodes first."""
        target_station = target_station.upper() if target_station else None
        tokens = {k.lower() for k in keywords}

        candidates = []
        for node in self.nodes.values():
            if node.priority < min_priority:
                continue
            if target_station and node.station != target_station and target_station not in node.station:
                continue

            node_tokens = {node.name.lower()} | {t.lower() for t in node.tags}
            matches = len(tokens & node_tokens)
            if matches > 0:
                # Rank by (priority, match count) descending
                candidates.append((node.priority, matches, node))

        candidates.sort(key=lambda x: (x[0], x[1]), reverse=True)
        return [c[2] for c in candidates[:limit]]
