# 🌐 Multi-Computer Cluster Setup Guide for O0

**Author:** Antigravity (`agy`)  
**Scope:** Distributed Multi-Machine Cluster & Remote Worker Execution  
**Protocol:** Synapse RPC Mesh over HTTP / JSON-RPC  

---

## 1. Overview & Architecture

O0 can run across multiple physical computers simultaneously (e.g. Primary Control Machine, GPU Rig, Remote Laptop, Raspberry Pi, Cloud VM). 

```
                               ┌────────────────────────────────┐
                               │  PRIMARY CONTROL MACHINE       │
                               │  (Node ID: PRIMARY_RIG)        │
                               │  Role: PRIMARY                 │
                               │  Port: 8990                    │
                               └───────────────┬────────────────┘
                                               │
                       ┌───────────────────────┴───────────────────────┐
                       │ Synapse JSON-RPC Mesh (Token Authenticated)   │
                       ▼                                               ▼
         ┌───────────────────────────┐                   ┌───────────────────────────┐
         │  WORKER COMPUTER 1        │                   │  WORKER COMPUTER 2        │
         │  (Node ID: GPU_WORKER)    │                   │  (Node ID: LAPTOP_FIELD)  │
         │  Role: WORKER             │                   │  Role: WORKER             │
         │  Port: 8990               │                   │  Port: 8990               │
         └───────────────────────────┘                   └───────────────────────────┘
```

- **Fail-Open Mesh:** If a worker drops offline, the primary node automatically falls back to local execution.
- **Mutual Authentication:** All RPC calls (`ping`, `dispatch_task`, `query_status`, `query_spatial_memory`) require a shared secret `auth_token`.
- **Latency & Load-Balanced Routing:** Tasks dispatched via `dispatch_optimal` automatically route to the peer with the lowest latency and fewest active tasks.

---

## 2. Network Connectivity Options

To allow computers to talk to each other, choose one of the following network configurations:

### Option A: Local Area Network (Same Wi-Fi / Ethernet)
- Determine each machine's LAN IP address:
  - Windows: Run `ipconfig` (e.g. `192.168.1.100`)
  - Linux/Mac: Run `ip a` or `ifconfig`
- Ensure inbound TCP traffic on port `8990` is permitted in Windows Defender Firewall:
  ```powershell
  New-NetFirewallRule -DisplayName "O0 Cluster RPC" -Direction Inbound -LocalPort 8990 -Protocol TCP -Action Allow
  ```

### Option B: Tailscale / ZeroTier (Recommended for Cross-Network / Remote Work)
- Install [Tailscale](https://tailscale.com) on all computers.
- Each machine gets a secure mesh IP (e.g. `100.x.y.z`) that works across different Wi-Fi networks, mobile hotspots, and routers with zero port forwarding required.

---

## 3. Configuration Setup (`cluster_config.json`)

On any computer participating in the cluster, initialize a configuration file:

```bash
python -m extensions.cluster.cli init-config
```

This generates `cluster_config.json`. Edit it to specify your node identity and known peers:

### On Primary Machine (`192.168.1.100` or `tailscale_primary`):
```json
{
  "node_id": "PRIMARY_RIG",
  "role": "PRIMARY",
  "listen_host": "0.0.0.0",
  "listen_port": 8990,
  "auth_token": "your-cluster-secret-key-123",
  "peers": [
    "http://192.168.1.105:8990"
  ],
  "max_concurrent_tasks": 4
}
```

### On Worker Machine (`192.168.1.105` or `tailscale_worker`):
```json
{
  "node_id": "GPU_WORKER",
  "role": "WORKER",
  "listen_host": "0.0.0.0",
  "listen_port": 8990,
  "auth_token": "your-cluster-secret-key-123",
  "peers": [
    "http://192.168.1.100:8990"
  ],
  "max_concurrent_tasks": 4
}
```

> **Environment Variables:** You can also configure via environment variables without editing JSON:
> - `O0_NODE_ID`: Unique node identifier
> - `O0_NODE_ROLE`: `PRIMARY`, `WORKER`, or `HYBRID`
> - `O0_LISTEN_PORT`: Port number (default `8990`)
> - `O0_AUTH_TOKEN`: Shared secret token
> - `O0_CLUSTER_PEERS`: Comma-separated peer URLs

---

## 4. Starting the Cluster Node Daemon

Run the daemon on each computer:

```bash
# Start with config file defaults:
python -m extensions.cluster.cli start

# Or override parameters via CLI flags:
python -m extensions.cluster.cli start --node-id GPU_WORKER --role WORKER --port 8990
```

Console Output:
```
🚀 Starting O0 Cluster Node [GPU_WORKER] (WORKER) on http://0.0.0.0:8990
   Auth Token: your****
   Registered Peers: 1
Press Ctrl+C to stop node daemon.
```

---

## 5. Checking Cluster Health & Peer Status

From any machine in the cluster, run:

```bash
python -m extensions.cluster.cli status
```

Output:
```
📍 Local Node: PRIMARY_RIG (Role: PRIMARY)
   Endpoint: http://0.0.0.0:8990
---------------------------------------------------------------------------
PEER URL                            STATUS     LATENCY      NODE ID        
---------------------------------------------------------------------------
http://192.168.1.105:8990           🟢 ONLINE  4.12 ms      GPU_WORKER     
---------------------------------------------------------------------------
```

---

## 6. Dispatching Tasks Across Computers

### Automatic Optimal Routing:
To dispatch a task that automatically routes to the healthiest available worker machine:

```bash
python -m extensions.cluster.cli dispatch --task "Audit and optimize Mamba Selective SSM for numerical stability"
```

### Direct Targeting:
To target a specific remote node by URL:

```bash
python -m extensions.cluster.cli dispatch --peer http://192.168.1.105:8990 --task "Execute unit tests on GPU worker"
```

The remote machine executes the task through O0's `EndToEndTaskInjector` and `ResilientCircuitBreaker`, signs the trajectory, syncs the markdown report to `O0-DIRECTORY`, and streams the result back to your terminal!
