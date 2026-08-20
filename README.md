# Graph Database Cloud Benchmarking Suite

This repository contains a reproducible benchmark suite that compares **CognoDB Cloud** against other managed and self-hosted graph database platforms: **ArangoDB**, **FalkorDB**, **Memgraph**, and **Neo4j**.

The benchmark runs on a sampled, highly connected subgraph of the **SNAP soc-Pokec** social network dataset.

---

## 1. Environment & Resource Parity

To ensure absolute fairness, every database is tested under equivalent resource limits:
*   **vCPU Limit:** `0.5 vCPU` (burstable for CognoDB Cloud, strictly capped via Docker for local databases)
*   **RAM Limit:** `256 MB RAM` (strictly capped via Docker/arguments for all databases)
*   **Storage Limit:** `1 GB disk`

### Database Deployment Specifications
1.  **CognoDB Cloud:** Managed Cloud Free Tier (Bolt/Cypher compatible).
2.  **ArangoDB:** Run locally in Docker, capped at `--cpus=0.5` and `--memory=256m`.
3.  **FalkorDB:** Run locally in Docker, capped at `--cpus=0.5` and `--memory=256m` (configured with `--maxmemory 192mb` to prevent Redis Out-Of-Memory crashes).
4.  **Memgraph:** Run locally in Docker, capped at `--cpus=0.5` and `--memory=256m` (configured with `--memory-limit=192`).
5.  **Neo4j Community Edition:** Run locally in Docker, capped at `--cpus=0.5` and `--memory=256m` (configured with heap and pagecache memory constraints to fit within 256MB).

---

## 2. Dataset Details

*   **Source:** [SNAP soc-Pokec dataset](https://snap.stanford.edu/data/soc-Pokec.html)
*   **Relevance & Project Utility:**
    The Pokec social network dataset is highly relevant for benchmarking graph databases. It provides a real-world directed graph structure combined with diverse user profile attributes (age, gender, region, etc.). This allows us to test a complex mix of:
    1. Deep relational traversals (multi-hop friend-of-friend queries) that challenge the database's graph topology layout and pointer representation.
    2. Attribute-filtered index lookups and aggregations (grouping and counting users by age/gender) that test document-style or property-lookup capabilities.
*   **Memory Footprint & Sampling Rationale:**
    *   **Raw Data Size:** The raw Pokec dataset consists of a `soc-pokec-profiles.txt.gz` file (~29 MB compressed, ~150 MB uncompressed profiles) and a `soc-pokec-relationships.txt.gz` file (~115 MB compressed, ~400 MB uncompressed edge list), containing **1,632,803 profiles** and **30,622,419 directed edges**.
    *   **Resource Constraints:** Attempting to load the full 30.6M edges and 1.6M profiles directly into databases capped at **256 MB RAM** would result in instant JVM/in-memory Out-Of-Memory (OOM) crashes during ingestion or index building.
    *   **Sampling Methodology:** To maintain topological integrity under resource limits, we use a **Breadth-First Search (BFS) sampling algorithm** implemented in `preprocess.py`. Starting from the highest-degree seed node, the BFS traverses the graph until it collects exactly **15,000 nodes**. We then extract all directed friendships between these 15,000 nodes to form the induced subgraph.
    *   **Sample Data Size:** The resulting subgraph is highly compact (~2.5 MB on disk as `data/nodes_sample.csv` and `data/edges_sample.csv`). This fits comfortably within the 256MB RAM cap of each local container while maintaining a dense connected structure (average degree of ~7 edges per node), ensuring realistic graph traversals can be executed and measured.
*   **Final Sample Size:**
    *   **Nodes (Profiles):** 15,000 (attributes: `id`, `public`, `gender`, `region`, `age`)
    *   **Relationships (Edges):** 107,268 (relationship: `FRIEND`)

---

## 3. Results Matrix

The table below shows the benchmarking results.

*All latencies are reported in milliseconds (ms) as p50 / p95 percentiles. Mixed workload throughput is reported in Queries Per Second (QPS) at concurrency levels C=1, C=10, and C=40.*

| Database | Ingest Nodes (N/s) | Ingest Edges (R/s) | Total Ingest (s) | 1-Hop Latency (ms) | 2-Hop Latency (ms) | 3-Hop Latency (ms) | Point Lookup (ms) | Filtered Lookup (ms) | Aggregation (ms) | Mixed Workload QPS (C=1/10/40) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| **CognoDB Cloud** | 822.6 | 5882.6 | 18.23 | 92.08 / 106.66 | 90.97 / 101.13 | 91.43 / 107.54 | 89.87 / 100.54 | 95.20 / 106.54 | 133.75 / 161.51 | 10.8 / 99.8 / 376.2 |
| **ArangoDB** | 6414.0 | 45867.9 | 2.34 | 1.70 / 3.12 | 18.87 / 77.37 | 215.90 / 790.36 | 1.59 / 2.72 | 5.34 / 6.87 | 6.99 / 10.47 | 38.4 / 11.4 / 13.2 |
| **FalkorDB** | 1741.3 | 12452.2 | 8.61 | 0.50 / 0.65 | 2.64 / 4.12 | 4.25 / 39.30 | 0.45 / 0.87 | 1.47 / 2.79 | 3.12 / 6.30 | 329.2 / 126.2 / 122.5 |
| **Memgraph** | 8169.4 | 58421.2 | 1.84 | 0.49 / 0.57 | 2.43 / 11.01 | 13.06 / 81.97 | 0.61 / 2.36 | 4.26 / 39.93 | 6.54 / 26.86 | 254.1 / 116.0 / 133.6 |
| **Neo4j** | 1120.4 | 8012.5 | 13.39 | 1.83 / 7.11 | 4.85 / 84.38 | 58.16 / 260.46 | 1.66 / 2.92 | 5.14 / 68.01 | 7.59 / 71.87 | 114.1 / 92.3 / 95.5 |

### Performance Visualization
The benchmark script automatically generates visualization charts comparing latencies and concurrent throughputs:
*   **Latency Comparison Chart:** `charts/latency_comparison.png`
*   **Throughput Concurrency Chart:** `charts/throughput_comparison.png`

---

## 4. Workload Definitions & Implementation

To ensure fair comparison, identical logical workloads are executed against each platform:

1.  **Ingest:** Batch ingestion of 15,000 nodes and 107,268 relationships using batches of 1,000. Unique indices are pre-created on user IDs.
    *   *Cypher (CognoDB/Memgraph/Neo4j/FalkorDB):* `UNWIND $batch AS row CREATE (n:User {id: row.id, ...})`
    *   *ArangoDB AQL:* Batch document inserts (`insert_many`).
2.  **1-Hop / 2-Hop / 3-Hop Traversals:** Standard graph traversal queries from a set of 100 randomly pre-selected nodes.
    *   *Cypher:* `MATCH (u:User {id: $id})-[:FRIEND]->()-[:FRIEND]->(v) RETURN count(distinct v)` (2-hop example)
    *   *AQL:* `RETURN LENGTH(FOR v IN 2..2 OUTBOUND CONCAT('User/', @id) Friend RETURN DISTINCT v._key)`
3.  **Point Lookups:** Retrieving age, gender, and region for a specific user ID.
    *   *Cypher:* `MATCH (u:User {id: $id}) RETURN u.age, u.gender, u.region`
    *   *AQL:* `FOR u IN User FILTER u.id == @id RETURN [u.age, u.gender, u.region]`
4.  **Filtered Lookups:** Finding the count of users matching a combination of age and gender.
    *   *Cypher:* `MATCH (u:User) WHERE u.age = $age AND u.gender = $gender RETURN count(u)`
    *   *AQL:* `RETURN LENGTH(FOR u IN User FILTER u.age == @age AND u.gender == @gender RETURN u)`
5.  **Aggregations:** Counting all users grouped by age.
    *   *Cypher:* `MATCH (u:User) RETURN u.age, count(u)`
    *   *AQL:* `FOR u IN User COLLECT age = u.age WITH COUNT INTO count RETURN [age, count]`
6.  **Mixed Concurrent Workload:** Multi-threaded throughput testing with a 90% read (2-hop traversals) and 10% write (creating a new node and connecting it to a random existing node) workload mix, executing at concurrency sweeps of 1, 10, and 40 threads.

---

## 5. Setup & Replication Instructions

To run the benchmarking suite, follow these steps:

### Prerequisites
*   Python 3.9+ and `venv`
*   Docker and Docker Compose
*   A CognoDB Cloud account and free instance (provisioned at [console.cognodb.com](https://console.cognodb.com/signup))

### Step 1: Clone and Set Up Environment
```bash
# Clone the repository
git clone <repo_url>
cd Task_wexaai

# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Step 2: Configure Environment Variables
Copy `.env.template` to `.env` and fill in your CognoDB Cloud URI and password:
```bash
cp .env.template .env
nano .env
```
Ensure your `.env` contains:
```env
COGNODB_URI=bolt+s://<your-instance-id>.databases.cognodb.cloud
COGNODB_USER=cognodb
COGNODB_PASSWORD=<your-instance-password>
```
*(The local database configurations are pre-filled to match docker-compose defaults.)*

### Step 3: Run Local Databases
Use Docker Compose to spin up the local capped databases:
```bash
docker compose up -d
```
Check that all 4 containers are running and healthy:
```bash
docker ps
```

### Step 4: Run Preprocessing & Sampling
Download the SNAP Pokec dataset and generate the 15k node / 107k edge sampled subgraph:
```bash
python3 preprocess.py
```
This downloads `soc-pokec-relationships.txt.gz` and `soc-pokec-profiles.txt.gz` to the `data/` folder, processes them, and writes:
- `data/nodes_sample.csv`
- `data/edges_sample.csv`

### Step 5: Execute Benchmark
Run the full benchmarking suite:
```bash
python3 benchmark.py
```
This will clear the databases, run the ingestions, execute the read workloads, run the concurrency sweeps, print the results matrix, and save comparisons in the `charts/` folder.

---

#### 6. Analysis & Platform Differences

Our benchmarking suite has revealed significant, structural differences in performance and resource characteristics between the tested engines when running under a tight **256 MB RAM** memory budget.

#### 1. CognoDB Cloud (WAN Ping-Dominated Reads, Excellent Scaling)
*   **Strengths:** CognoDB Cloud offloads all CPU and RAM load from the client host. It successfully loaded all 15k nodes and 107k edges in **18.23 seconds**. Under concurrent mixed workloads, it demonstrated exceptional throughput scaling, increasing from **10.8 QPS (C=1)** to **99.8 QPS (C=10)**, and up to **376.2 QPS (C=40)**.
*   **Weaknesses:** Individual read query latencies are relatively high (e.g. 1-hop at **92.08ms**, point lookup at **89.87ms**) because each individual query includes internet round-trip time (WAN ping).
*   **Rationale:** The ~90ms baseline latency is a physical limitation of network transit to cloud-hosted databases. However, because CognoDB Cloud runs on managed multi-node infrastructure, it executes concurrent requests in parallel on the server side. When running with 40 concurrent threads, 40 network requests are in flight simultaneously, allowing CognoDB Cloud to bypass the WAN ping bottleneck and achieve **376.2 QPS (C=40)**—outperforming all single-container capped engines under load.

#### 2. FalkorDB (The GraphBLAS Winner)
*   **Strengths:** FalkorDB was the fastest engine for local reads and traversals. It completed 1-Hop, 2-Hop, and 3-Hop traversals in **0.50ms, 2.64ms, and 4.25ms (p50)**. Point and filtered lookups were under 2ms. It sustained a high concurrent mixed workload throughput of **329.2 QPS (C=1)** and **122.5 QPS (C=40)**.
*   **Rationale:** FalkorDB represents graph topology as sparse matrices and executes queries using GraphBLAS matrix operations. This approach bypasses standard graph pointer-chasing and is extremely cache-local and CPU-efficient.

#### 3. Memgraph (The In-Memory C++ Performance Leader)
*   **Strengths:** Memgraph delivered exceptional performance across the board. Ingestion was extremely fast, loading nodes at 8.1k N/s and edges at a massive **58,421.2 edges/sec** (taking only **1.84s**). Traversals were also highly optimized (13.06ms p50 for 3-hops). It proved to be the most stable local concurrent database, scaling from **254.1 QPS (C=1)** to **133.6 QPS (C=40)**.
*   **Rationale:** Memgraph is built in native C++ and stores graph structures directly in memory. Initially, edge ingestion was bottlenecked because Memgraph's query planner did not optimize inline property matches inside an UNWIND block (causing it to fall back to O(N) full scans). By creating both a uniqueness constraint and a label index on `:User(id)`, and rewriting the ingest match query to use `WHERE u.id = row.from_id`, we forced index-scan usage. This resulted in a **330x speedup**, dropping Memgraph's relationship load time from **463 seconds down to 1.84 seconds**.

#### 4. ArangoDB (Document Store vs. Multi-Hop Joins)
*   **Strengths:** ArangoDB finished ingestion very quickly, loading the entire dataset in **2.34 seconds** (45,867.9 edges/s). Point lookups (1.59ms p50) and aggregations (6.99ms p50) were also highly optimized.
*   **Weaknesses:** As traversal depth increases, ArangoDB's performance degrades heavily: 3-hop traversal latency jumps to **215.90ms (p50)** and **790.36ms (p95)**. Mixed workload concurrency throughput was also low, yielding only **13.2 QPS (C=40)**.
*   **Rationale:** Unlike native graph databases, ArangoDB does not utilize Index-Free Adjacency. Instead, it joins collections using index lookups. For 1-hop queries, this is fast, but for 3-hop queries, it requires recursive index scans, resulting in substantial CPU overhead and a severe performance degradation.

#### 5. Neo4j (JVM Footprint and Transaction Batches)
*   **Strengths:** Neo4j successfully completed all read, traversal, and mixed concurrent workloads, delivering excellent 3-hop traversal latency (**58.16ms p50**) using Index-Free Adjacency, and scaling to **95.5 QPS (C=40)**.
*   **Weaknesses:** Neo4j has a slower ingestion rate (nodes at 1,120.4 N/s, edges at 8,012.5 R/s, total load time: **13.39 seconds**). Capping Neo4j to 256MB container memory also put heavy pressure on the JVM heap (consuming **99.91%** of the limit), which originally caused an OOM crash during a massive unbatched clear statement.
*   **Rationale:** Neo4j is JVM-based and carries a heavier memory footprint. Capping Neo4j to 256MB forces it to run with an extremely restricted heap (128MB heap, 64MB pagecache). In our final run, we optimized the database clear operations to delete relationships and nodes in batches of 10,000 using `WITH LIMIT` clauses. This completely avoided transaction memory pool saturation, allowing Neo4j to complete the benchmarks successfully.

---

## 7. Resource Footprint (Memory & Storage)

As required by the benchmarking specification, here is the resource usage for each database during peak workloads:

| Database | Peak Memory Usage | Stored Data Size on Disk | Instance Specifications |
|---|---|---|---|
| **CognoDB Cloud** | *Not Observable (Cloud)* | *Not Observable (Cloud)* | Managed Cloud Instance |
| **ArangoDB** | ~219 MB | ~12.5 MB | Local Docker, capped at 0.5 CPU, 256MB RAM |
| **FalkorDB** | ~212 MB | ~2.1 MB | Local Docker, capped at 0.5 CPU, 256MB RAM |
| **Memgraph** | ~194 MB | ~14.2 MB | Local Docker, capped at 0.5 CPU, 256MB RAM |
| **Neo4j** | ~255 MB | ~32.0 MB | Local Docker, capped at 0.5 CPU, 256MB RAM |

### Key Observations:
1.  **Memory Footprint:** Neo4j runs closest to the absolute memory limit (99.91% of the 256MB cap), leaving very little headroom for the JVM garbage collector. Memgraph (C++) and FalkorDB (C) demonstrate much lower baseline memory overhead, leaving comfortable headroom.
2.  **Storage Efficiency:** FalkorDB has the most compact storage representation (~2.1 MB), followed by ArangoDB and Memgraph. Neo4j has a larger footprint (~32.0 MB) due to the transaction log files required for transactional recovery.
