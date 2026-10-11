---
title: "SYNAPSE_CLUSTER_IPC"
station: "SYSTEMS"
priority: 8
quick_paths: ["SYSTEMS_STATION_MAP", "DISTRIBUTED_VERIFICATION"]
tags: ["systems/ipc", "synapse", "rpc", "clustering", "priority/8"]
---

# 🛰️ Synapse Cluster IPC & Network Bridge

> **Station Origin:** `[[SYSTEMS_STATION_MAP]]` (P10)  
> **Priority:** 8  
> **Direct Bridges:** `[[DISTRIBUTED_VERIFICATION]]` (P5)

---

## 🔬 Architectural Mechanics
Dual-mode inter-process and inter-machine agent communication (`extensions.synapse`):

1. **File Mailbox IPC:** Atomic JSON message queues (`inbox_hermes`, `inbox_antigravity`) on shared filesystems.
2. **Network JSON-RPC Daemon (`SynapseRPCServer` / `SynapseRPCClient`):** Lightweight HTTP micro-service supporting multi-machine distributed clustering.
3. **Fail-Open Heartbeat:** If a node drops, the surviving agent smoothly transitions into standalone operation.
