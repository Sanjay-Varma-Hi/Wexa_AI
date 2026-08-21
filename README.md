# Graph Database Benchmarking Suite: CognoDB Cloud vs. Local Databases

This repository contains a scientifically rigorous, reproducible benchmark suite designed to compare the performance characteristics of **CognoDB Cloud** against four managed/self-hosted graph database engines: **ArangoDB**, **FalkorDB**, **Memgraph**, and **Neo4j Community**.

The benchmarks are executed against a sampled, highly connected subgraph of the public **SNAP soc-Pokec** social network dataset.

---

## 1. Environment & Resource Specifications

To establish a defensible baseline of comparison, controlled resource parity was applied across the self-hosted platforms where possible. However, because CognoDB Cloud is evaluated as a managed service, key physical host characteristics (vCPU, memory, storage pooling, multi-tenant scheduling) are opaque.

### Client Hardware & OS Specs
* **Host Platform:** macOS (Darwin 25.5.0)
* **Architecture:** ARM64 (Apple Silicon)
* **Python Runtime:** Python v3.9.6
* **Client Driver Versions:**
  * `neo4j` Python Driver: `v5.23.0`
  * `python-arango` Driver: `v7.9.0`
  * `falkordb` Driver: `v1.0.4`

### Database Engine Deployments & Resource Constraints
1. **CognoDB Cloud:** Managed Cloud Instance (Bolt-compatible API). Physical host hardware configurations are unobservable; execution results include network round-trip effects (WAN latency).
2. **ArangoDB (v3.11.10):** Runs locally in Docker. Capped at `0.5 vCPU` and `256 MB RAM` via Docker resource limits.
3. **FalkorDB (v4.20.3):** Runs locally in Docker. Capped at `0.5 vCPU` and `256 MB RAM` (engine configured with `--maxmemory 192mb` to prevent memory eviction crashes).
4. **Memgraph (v3.12.0):** Runs locally in Docker. Capped at `0.5 vCPU` and `256 MB RAM` (configured with `--memory-limit=192` to avoid out-of-memory container terminates).
5. **Neo4j Community (v5.22.0):** Runs locally in Docker. Capped at `0.5 vCPU` and `256 MB RAM` (configured with `server.memory.heap.initial_size=96m`, `server.memory.heap.max_size=128m`, and `server.memory.pagecache.size=32m`).

---

## 2. Dataset Preprocessing & Utility

### Relevance & Project Utility
The **Stanford SNAP soc-Pokec** dataset is a real-world directed graph representing a Slovakian social network. It is highly suited for benchmarking graph engines because it combines high topological density (multi-hop traversal paths) with rich user profile attributes (age, gender, region). This allows execution of:
* **Topology traversals:** Evaluates pointer representation, index lookups, and graph representation in memory.
* **Property filtering:** Measures document/relational filtering capabilities on nodes.

### Sampling Rationale & Durability Limits
* **Full Dataset Size:** Contains **1,632,803 profiles** (nodes) and **30,622,419 relationships** (directed edges).
* **RAM Constraints:** Attempting to ingest the full graph into databases limited to **256 MB RAM** results in transaction log saturation, heap exhaustion, or JVM crashes.
* **Sampling Algorithm:** [`preprocess.py`](file:///Users/sanjayvarma/Documents/Projects/Task_wexaai/preprocess.py) performs a deterministic Breadth-First Search (BFS) starting from the global highest out-degree node (ID: `5867`, out-degree: `8,763`). Adjacency lists are sorted prior to traversal to guarantee deterministic output. Traversal halts exactly at **15,000 nodes**, extracting all friendships (induced subgraph) within this set.
* **Final Preprocessed Size:**
  * **Nodes (User Profiles):** 15,000
  * **Relationships (FRIEND Edges):** 104,602
  * **Missing Profiles:** 0 (All sampled nodes contain corresponding profiles)
  * **Average Out-Degree:** 6.97 edges/node

---

## 3. Indexing Configurations

| Database | User ID Index | Filtered Fields Index (age, gender) | Indexing Mechanism |
| --- | --- | --- | --- |
| **CognoDB Cloud** | Unique constraint on `User.id` | None | Managed B-Tree / Implicit Unique Index |
| **ArangoDB** | Unique hash index on `User.id` | None | RocksDB Hash Index |
| **FalkorDB** | Range index on `User.id` | None | GraphBLAS Sparse Matrix Index |
| **Memgraph** | Unique constraint on `User.id` | None | In-Memory Label-Property SkipList |
| **Neo4j Community**| Unique constraint on `User.id` | None | Native Cypher Range Index (B-Tree) |

> [!NOTE]
> **Attribute Filters:** Indexes are intentionally omitted on `age` and `gender` attributes. The filtered lookup workload is designed to force a full collection scan, measuring the engine's property lookup and scanning efficiency under limited RAM.

---

## 4. Results Matrix

The matrix below summarizes the performance metrics from the final execution run.

* *All single-query latencies are reported in milliseconds (ms) as p50 percentiles.*
* *Throughput is reported in Queries Per Second (QPS) at thread concurrency levels C=1, C=10, and C=40.*
* *Mixed workload error rates are reported at C=40.*

| Database | Ingest Nodes/s | Ingest Edges/s | Total Ingest (s) | 1-Hop p50 (ms) | 2-Hop p50 (ms) | 3-Hop p50 (ms) | Point p50 (ms) | Filter p50 (ms) | Agg p50 (ms) | Concurrency QPS (C=1 / 10 / 40) | Error Rate (C=40) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| **CognoDB Cloud** | 698.9 | 4873.7 | 21.46 | 89.87 | 120.35 | 750.37 | 120.06 | 93.94 | 125.89 | 6.6 / 14.5 / 15.7 | 1.4% |
| **ArangoDB** | 6295.6 | 43902.4 | 2.38 | 3.11 | 17.29 | 224.16 | 1.95 | 5.26 | 6.28 | 43.4 / 18.6 / 21.8 | 2.2% |
| **Memgraph** | 8477.1 | 59114.7 | 1.77 | 0.88 | 2.27 | 14.05 | 0.53 | 4.56 | 4.49 | 287.1 / 170.7 / 212.5 | 1.5% |
| **Neo4j** | 508.9 | 3548.6 | 29.48 | 3.42 | 4.70 | 73.54 | 4.23 | 8.09 | 9.15 | 66.3 / 73.3 / 18.9 | 10.5% |
| **FalkorDB** | 1432.9 | 9992.5 | 10.47 | 0.46 | 2.64 | 4.48 | 0.53 | 1.79 | 4.50 | 340.8 / 169.9 / 174.4 | 5.6% |

### Key Observations & Methodological Realities
1. **Local-vs-Cloud Latency Profiles:** CognoDB Cloud displays a base single-query latency of ~85-120ms, which is dominated by network round-trip time (RTT). The four self-hosted local databases run within isolated Docker containers on `localhost` and display low single-digit millisecond response times. This comparison represents controlled resource parity for self-hosted instances under a 256MB RAM ceiling, but does not isolate SaaS virtualization overhead on CognoDB.
2. **Sustained Concurrent Throughput:** Running concurrent workers with thread-isolated connection adapters shows that local engines scale significantly under read-heavy workloads (Memgraph reaching 212.5 QPS, FalkorDB reaching 174.4 QPS). CognoDB Cloud concurrent throughput is bounded near 15.7 QPS, indicating network socket and SaaS service-layer serialization bounds.
3. **Traversal Performance Trends:** FalkorDB displays highly stable traversal latencies as path depth increases from 1-hop to 3-hops (0.46ms to 4.48ms). This observed trend is consistent with a GraphBLAS matrix representation which executes hops as sparse matrix-matrix multiplications, although deep profiling would be needed to isolate the exact speed contribution of the engine vs local index lookups. Memgraph displays highly efficient in-memory traversal and fast ingestion.


### Performance Visualization Charts
The orchestrator automatically outputs visualization plots under the `charts/` directory:
* **Hop Traversal Latency Comparison:** [`charts/latency_comparison.png`](file:///Users/sanjayvarma/Documents/Projects/Task_wexaai/charts/latency_comparison.png) (log-scale plot of hop performance)
* **Concurrency Scaling Plot:** [`charts/throughput_comparison.png`](file:///Users/sanjayvarma/Documents/Projects/Task_wexaai/charts/throughput_comparison.png) (line chart showing throughput scaling from C=1 to C=40)

---

## 5. Workload Cypher & AQL Definitions

To verify query equivalence, logically identical workloads are executed across all engines:

1. **Ingest Phase:** Batched unwinding of node lists and edge lists (batches of 1,000).
   * *Cypher (Neo4j, Memgraph, FalkorDB, CognoDB):*
     `UNWIND $batch AS r CREATE (:User {id: r.id, public: r.public, gender: r.gender, region: r.region, age: r.age})`
     `UNWIND $batch AS r MATCH (u:User) WHERE u.id = r.from_id MATCH (v:User) WHERE v.id = r.to_id CREATE (u)-[:FRIEND]->(v)`
   * *ArangoDB AQL:* Uses `insert_many` payload insertion API targeting the `User` and `Friend` collections.
2. **Point Lookups:** Retrieves attributes of a single node.
   * *Cypher:* `MATCH (u:User {id: $id}) RETURN u.age, u.gender, u.region`
   * *AQL:* `FOR u IN User FILTER u.id == @id RETURN [u.age, u.gender, u.region]`
3. **Filtered Lookups:** Scans collection matching user attribute predicates.
   * *Cypher:* `MATCH (u:User) WHERE u.age = $age AND u.gender = $gender RETURN count(u)`
   * *AQL:* `RETURN LENGTH(FOR u IN User FILTER u.age == @age AND u.gender == @gender RETURN u)`
4. **Traversal Hops (2-hop example):** Computes reachable unique neighbor set size.
   * *Cypher:* `MATCH (u:User {id: $id})-[:FRIEND]->()-[:FRIEND]->(v) RETURN count(distinct v)`
   * *AQL:* `RETURN LENGTH(FOR v IN 2..2 OUTBOUND CONCAT('User/', @id) Friend RETURN DISTINCT v._key)`
5. **Aggregation:** Groups and counts profiles.
   * *Cypher:* `MATCH (u:User) RETURN u.age, count(u)`
   * *AQL:* `FOR u IN User COLLECT age = u.age WITH COUNT INTO count RETURN [age, count]`

---

## 6. Reproducibility Guide

Follow these steps to run the complete benchmarking suite on your machine.

### Setup Prerequisites
* Python 3.9+ installed and configured.
* Docker Daemon and Docker Compose CLI tools installed and running.
* A CognoDB Cloud instance provisioned.

### Step 1: Clone and Prepare Environment
```bash
# Clone the repository
git clone https://github.com/Sanjay-Varma-Hi/Wexa_AI.git
cd Wexa_AI

# Create virtual environment and install dependencies
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Step 2: Configure Environment Variables
Copy `.env.template` to `.env` and enter your CognoDB credentials:
```bash
cp .env.template .env
nano .env
```
Ensure `.env` contains:
```env
COGNODB_URI=bolt://db-fdd28aa3.bravo.databases.cognodb.com:7687
COGNODB_USER=cognodb
COGNODB_PASSWORD=your_password_here
```

### Step 3: Run the Orchestrator
Execute the unified orchestrator script. This script automatically handles:
1. Cleaning existing Docker containers and volumes (`docker compose down -v`).
2. Booting containers for ArangoDB, FalkorDB, Memgraph, and Neo4j.
3. Actively polling container ports until they are healthy.
4. Preprocessing the raw Pokec dataset to sample the deterministic subgraph.
5. Ingesting, validating, warming up, and running benchmarks.
6. Generating charts and report files.

```bash
python3 run_benchmark.py
```

All summary results will print directly to the console, raw metrics will be recorded in `results/raw/`, aggregated rates in `results/summary.csv`, and visualization charts saved under `charts/`.
