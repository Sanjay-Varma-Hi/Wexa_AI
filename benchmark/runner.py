import os
import csv
import time
import random
import threading
import numpy as np
import json
import platform
import subprocess
from datetime import datetime

GLOBAL_VALIDATION_RESULTS = {}

# Import adapters
from benchmark.adapters.cognodb import CognoDBAdapter
from benchmark.adapters.neo4j import Neo4jAdapter
from benchmark.adapters.memgraph import MemgraphAdapter
from benchmark.adapters.falkordb import FalkorDBAdapter
from benchmark.adapters.arangodb import ArangoDBAdapter

NODES_CSV = "data/nodes_sample.csv"
EDGES_CSV = "data/edges_sample.csv"
RESULTS_DIR = "results/raw"
WARMUP_ITERATIONS = 20
MEASURED_ITERATIONS = 100
CONCURRENCY_LEVELS = [1, 10, 40]
MIXED_DURATION = 10.0  # seconds

# Helper to calculate latency percentiles and stats
def calculate_stats(latencies, total_attempts, failed_count, timeout_count):
    if not latencies:
        return {
            "p50": 0.0, "p95": 0.0, "mean": 0.0, "min": 0.0, "max": 0.0,
            "sample_count": 0, "failed_count": failed_count, "timeout_count": timeout_count,
            "total_attempts": total_attempts, "error_rate": 1.0
        }
    return {
        "p50": float(np.percentile(latencies, 50)),
        "p95": float(np.percentile(latencies, 95)),
        "mean": float(np.mean(latencies)),
        "min": float(np.min(latencies)),
        "max": float(np.max(latencies)),
        "sample_count": len(latencies),
        "failed_count": failed_count,
        "timeout_count": timeout_count,
        "total_attempts": total_attempts,
        "error_rate": float(failed_count + timeout_count) / total_attempts
    }

# Thread-local worker execution loop for concurrent mixed read/write throughput
def mixed_workload_worker(adapter_cls, test_nodes, duration, results_list, lock):
    # Instantiate a thread-local adapter connection to ensure 100% thread-safety
    adapter = adapter_cls()
    adapter.connect()
    
    attempts = 0
    success = 0
    failed = 0
    timeouts = 0
    reads = 0
    writes = 0
    latencies = []
    
    write_id = 90000000 + (threading.get_ident() % 10000) * 10000
    start_time = time.time()
    
    while time.time() - start_time < duration:
        nid = random.choice(test_nodes)
        is_read = random.random() < 0.90  # 90% reads, 10% writes
        attempts += 1
        
        op_start = time.perf_counter()
        try:
            if is_read:
                reads += 1
                # READ: 2-hop traversal
                adapter.hop_traversal(nid, 2)
            else:
                writes += 1
                # WRITE: Create a new user node and link it to an existing node
                adapter.write_operation(write_id, nid)
                write_id += 1
            
            lat = (time.perf_counter() - op_start) * 1000.0
            latencies.append(lat)
            success += 1
        except TimeoutError:
            timeouts += 1
        except Exception:
            failed += 1
            
    adapter.close()
    
    with lock:
        results_list.append({
            "attempts": attempts,
            "success": success,
            "failed": failed,
            "timeouts": timeouts,
            "reads": reads,
            "writes": writes,
            "latencies": latencies
        })

def run_database_benchmark(name, adapter_cls, nodes, edges, test_nodes, validation_nodes):
    print(f"\n[INFO] Starting Benchmarks for: {name}")
    print("[INFO] Connecting to database...")
    
    adapter = adapter_cls()
    adapter.connect()
    
    # Verify readiness
    if not adapter.health_check():
        raise RuntimeError(f"Database {name} failed health check. Verify it is running and accessible.")
        
    print("[INFO] Clearing database...")
    adapter.clear_data()
    
    print("[INFO] Creating indices...")
    adapter.create_indexes()
    
    # 1. Ingestion Phase
    # We time ONLY the database load operations (excluding initial CSV load and parsing)
    # FalkorDB / Memgraph / CognoDB use unwind queries; Arango uses bulk inserts.
    print(f"[INFO] Ingesting {len(nodes)} nodes and {len(edges)} edges...")
    ingest_start = time.perf_counter()
    adapter.load_nodes(nodes)
    adapter.load_relationships(edges)
    total_ingest_time = time.perf_counter() - ingest_start
    print(f"[INFO] Ingest completed in {total_ingest_time:.2f}s")
    
    ingest_results = {
        "total_time_s": total_ingest_time,
        "nodes_per_sec": len(nodes) / total_ingest_time if total_ingest_time > 0 else 0,
        "edges_per_sec": len(edges) / total_ingest_time if total_ingest_time > 0 else 0
    }
    
    # 2. Validation Pass
    # Verify the database is actually returning correct and equivalent structures
    print("[INFO] Running Cross-Database Query Correctness Validation...")
    db_val = {}
    for node_id in validation_nodes:
        h1 = adapter.hop_traversal(node_id, 1)
        h2 = adapter.hop_traversal(node_id, 2)
        pl = adapter.point_lookup(node_id)
        
        # Verify counts are integers and point lookups return valid lists
        if not isinstance(h1, int) or not isinstance(h2, int):
            raise AssertionError(f"Validation failed: Hop traversal count is not an integer for node {node_id}")
        if pl is None or len(pl) < 3:
            raise AssertionError(f"Validation failed: Point lookup returned invalid structure for node {node_id}: {pl}")
            
        db_val[str(node_id)] = {
            "point_lookup": pl,
            "1-hop": h1,
            "2-hop": h2
        }
        
    # Compile aggregation results for validation
    raw_agg = adapter.run_aggregation()
    agg_dict = {}
    for item in raw_agg:
        if item and len(item) >= 2:
            age = item[0]
            count = item[1]
            if age is not None:
                agg_dict[str(age)] = int(count)
    db_val["aggregation"] = agg_dict
    
    # Save to global validation map
    GLOBAL_VALIDATION_RESULTS[name] = db_val
    
    # Cross-compare with other databases that have already run
    if len(GLOBAL_VALIDATION_RESULTS) > 1:
        ref_db_name = list(GLOBAL_VALIDATION_RESULTS.keys())[0]
        ref_val = GLOBAL_VALIDATION_RESULTS[ref_db_name]
        
        for node_id in validation_nodes:
            nid_str = str(node_id)
            ref_node = ref_val[nid_str]
            curr_node = db_val[nid_str]
            
            if curr_node["point_lookup"] != ref_node["point_lookup"]:
                raise AssertionError(
                    f"Canonical Semantic Mismatch on Point Lookup for Node ID {node_id}!\n"
                    f"  {ref_db_name} returned: {ref_node['point_lookup']}\n"
                    f"  {name} returned: {curr_node['point_lookup']}"
                )
            if curr_node["1-hop"] != ref_node["1-hop"]:
                raise AssertionError(
                    f"Canonical Semantic Mismatch on 1-Hop count for Node ID {node_id}!\n"
                    f"  {ref_db_name} returned: {ref_node['1-hop']}\n"
                    f"  {name} returned: {curr_node['1-hop']}"
                )
            if curr_node["2-hop"] != ref_node["2-hop"]:
                raise AssertionError(
                    f"Canonical Semantic Mismatch on 2-Hop count for Node ID {node_id}!\n"
                    f"  {ref_db_name} returned: {ref_node['2-hop']}\n"
                    f"  {name} returned: {curr_node['2-hop']}"
                )
                
        if db_val["aggregation"] != ref_val["aggregation"]:
            raise AssertionError(
                f"Canonical Semantic Mismatch on Aggregations!\n"
                f"  {ref_db_name} returned: {ref_val['aggregation']}\n"
                f"  {name} returned: {db_val['aggregation']}"
            )
            
    print("[INFO] Query correctness and cross-database validation completed successfully.")

    # 3. Read workloads (Point lookup, Filtered lookup, Hop traversals, Aggregations)
    workload_results = {}
            
    # Point Lookup
    print("[INFO] Warming up Point Lookups...")
    for nid in test_nodes[:WARMUP_ITERATIONS]:
        adapter.point_lookup(nid)
        
    print("[INFO] Executing Point Lookups...")
    attempts, success, failed, timeouts = 0, 0, 0, 0
    latencies = []
    for nid in test_nodes:
        attempts += 1
        start = time.perf_counter()
        try:
            res = adapter.point_lookup(nid)
            if res is None:
                raise ValueError("Query returned empty result")
            latencies.append((time.perf_counter() - start) * 1000.0)
            success += 1
        except TimeoutError:
            timeouts += 1
        except Exception:
            failed += 1
    workload_results["point_lookup"] = calculate_stats(latencies, attempts, failed, timeouts)

    # Filtered Lookup
    print("[INFO] Warming up Filtered Lookups...")
    test_filters = [(25, 1), (30, 0), (22, 1), (28, 0), (35, 1)] * 20
    for age, gender in test_filters[:WARMUP_ITERATIONS]:
        adapter.filtered_lookup(age, gender)
        
    print("[INFO] Executing Indexed/Filtered Lookups...")
    attempts, success, failed, timeouts = 0, 0, 0, 0
    latencies = []
    # Seed specific age and gender combinations that return non-empty records in Pokec
    test_filters = [(25, 1), (30, 0), (22, 1), (28, 0), (35, 1)] * 20
    for age, gender in test_filters:
        attempts += 1
        start = time.perf_counter()
        try:
            res = adapter.filtered_lookup(age, gender)
            latencies.append((time.perf_counter() - start) * 1000.0)
            success += 1
        except TimeoutError:
            timeouts += 1
        except Exception:
            failed += 1
    workload_results["filtered_lookup"] = calculate_stats(latencies, attempts, failed, timeouts)

    # Traversals (1-hop, 2-hop, 3-hop)
    for hop in [1, 2, 3]:
        print(f"[INFO] Warming up {hop}-Hop Traversals...")
        for nid in test_nodes[:WARMUP_ITERATIONS]:
            adapter.hop_traversal(nid, hop)
            
        print(f"[INFO] Executing {hop}-Hop Traversals...")
        attempts, success, failed, timeouts = 0, 0, 0, 0
        latencies = []
        for nid in test_nodes:
            attempts += 1
            start = time.perf_counter()
            try:
                adapter.hop_traversal(nid, hop)
                latencies.append((time.perf_counter() - start) * 1000.0)
                success += 1
            except TimeoutError:
                timeouts += 1
            except Exception:
                failed += 1
        workload_results[f"{hop}-hop"] = calculate_stats(latencies, attempts, failed, timeouts)

    # Aggregation
    print("[INFO] Warming up Aggregations...")
    for _ in range(WARMUP_ITERATIONS):
        adapter.run_aggregation()
        
    print("[INFO] Executing Aggregations...")
    attempts, success, failed, timeouts = 0, 0, 0, 0
    latencies = []
    for _ in range(MEASURED_ITERATIONS):
        attempts += 1
        start = time.perf_counter()
        try:
            adapter.run_aggregation()
            latencies.append((time.perf_counter() - start) * 1000.0)
            success += 1
        except TimeoutError:
            timeouts += 1
        except Exception:
            failed += 1
    workload_results["aggregation"] = calculate_stats(latencies, attempts, failed, timeouts)

    # 4. Concurrent Mixed Workload Sweeps
    print("[INFO] Starting Mixed Concurrent Workload Sweeps...")
    concurrency_results = {}
    
    for c in CONCURRENCY_LEVELS:
        print(f"[INFO] Sweeping concurrency C={c}...")
        worker_results = []
        lock = threading.Lock()
        threads = []
        
        sweep_start = time.perf_counter()
        for _ in range(c):
            t = threading.Thread(target=mixed_workload_worker, args=(adapter_cls, test_nodes, MIXED_DURATION, worker_results, lock))
            threads.append(t)
            t.start()
            
        for t in threads:
            t.join()
            
        sweep_duration = time.perf_counter() - sweep_start
        
        # Consolidate results across all workers
        total_attempts = sum(w["attempts"] for w in worker_results)
        total_success = sum(w["success"] for w in worker_results)
        total_failed = sum(w["failed"] for w in worker_results)
        total_timeouts = sum(w["timeouts"] for w in worker_results)
        total_reads = sum(w["reads"] for w in worker_results)
        total_writes = sum(w["writes"] for w in worker_results)
        
        all_lats = []
        for w in worker_results:
            all_lats.extend(w["latencies"])
            
        qps = total_success / sweep_duration if sweep_duration > 0 else 0
        error_rate = float(total_failed + total_timeouts) / total_attempts if total_attempts > 0 else 0
        
        concurrency_results[str(c)] = {
            "concurrency": c,
            "total_requests": total_attempts,
            "reads": total_reads,
            "writes": total_writes,
            "successful_requests": total_success,
            "failed_requests": total_failed,
            "timeout_count": total_timeouts,
            "qps": qps,
            "error_rate": error_rate,
            "latency_ms": {
                "p50": float(np.percentile(all_lats, 50)) if all_lats else 0.0,
                "p95": float(np.percentile(all_lats, 95)) if all_lats else 0.0,
                "mean": float(np.mean(all_lats)) if all_lats else 0.0,
                "min": float(np.min(all_lats)) if all_lats else 0.0,
                "max": float(np.max(all_lats)) if all_lats else 0.0
            }
        }
        print(f"[INFO] Concurrency C={c} sweep finished: QPS={qps:.1f}, Error Rate={error_rate*100:.1f}%")

    # Clean up write updates by clearing the database
    print("[INFO] Cleaning up mixed workload write changes...")
    adapter.clear_data()
    adapter.close()
    
    # Build complete structured JSON result schema
    db_version = "Unknown"
    # Try to grab version dynamically where supported
    try:
        temp = adapter_cls()
        temp.connect()
        if hasattr(temp, "db") and hasattr(temp.db, "version"):
            db_version = temp.db.version()
        elif hasattr(temp, "driver") and hasattr(temp, "uri"):
            # Bolt versions can be probed
            with temp.driver.session() as s:
                res = s.run("call dbms.components() YIELD name, versions, edition RETURN versions[0] AS ver")
                db_version = res.single()["ver"]
        temp.close()
    except Exception:
        pass

    commit_sha = "Unknown"
    try:
        commit_sha = subprocess.check_output(["git", "rev-parse", "HEAD"]).decode().strip()
    except Exception:
        pass

    results_json = {
        "database": name,
        "database_version": db_version,
        "benchmark_version": "1.0.0",
        "benchmark_commit_sha": commit_sha,
        "timestamp": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "host": {
            "os": platform.system(),
            "os_release": platform.release(),
            "architecture": platform.machine(),
            "python_version": platform.python_version()
        },
        "dataset": {
            "nodes": len(nodes),
            "edges": len(edges)
        },
        "warmup_iterations": WARMUP_ITERATIONS,
        "measured_iterations": MEASURED_ITERATIONS,
        "ingestion": ingest_results,
        "workloads": workload_results,
        "concurrency_sweeps": concurrency_results
    }
    
    os.makedirs(RESULTS_DIR, exist_ok=True)
    out_file = os.path.join(RESULTS_DIR, f"{name.lower().replace(' ', '_')}.json")
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(results_json, f, indent=4)
        
    print(f"[INFO] Raw results saved to {out_file}")
    return results_json

def main():
    print("[INFO] Loading dataset CSVs...")
    nodes, edges = [], []
    with open(NODES_CSV, 'r', encoding='utf-8') as f:
        for r in csv.DictReader(f):
            nodes.append({
                'id': int(r['id']), 
                'public': int(r['public']) if r['public'] else None, 
                'gender': int(r['gender']) if r['gender'] else None, 
                'region': r['region'], 
                'age': int(r['age']) if r['age'] else None
            })
            
    with open(EDGES_CSV, 'r', encoding='utf-8') as f:
        for r in csv.DictReader(f):
            edges.append({
                'from_id': int(r['from_id']), 
                'to_id': int(r['to_id'])
            })
            
    print(f"[INFO] Loaded {len(nodes)} nodes and {len(edges)} edges.")
    
    # Deterministically select 100 query nodes for benchmark consistency
    random.seed(42)
    node_ids = sorted([n['id'] for n in nodes])
    test_nodes = random.sample(node_ids, MEASURED_ITERATIONS)
    
    # Pick a subset of 5 nodes for validation checks
    validation_nodes = test_nodes[:5]
    
    active_adapters = []
    
    # Select which adapters are configured in the environment
    if os.getenv("COGNODB_URI"):
        active_adapters.append(("CognoDB Cloud", CognoDBAdapter))
    if os.getenv("ARANGODB_URI"):
        active_adapters.append(("ArangoDB", ArangoDBAdapter))
    if os.getenv("FALKORDB_HOST"):
        active_adapters.append(("FalkorDB", FalkorDBAdapter))
    if os.getenv("MEMGRAPH_URI"):
        active_adapters.append(("Memgraph", MemgraphAdapter))
    if os.getenv("NEO4J_URI"):
        active_adapters.append(("Neo4j", Neo4jAdapter))
        
    for name, adapter_cls in active_adapters:
        try:
            run_database_benchmark(name, adapter_cls, nodes, edges, test_nodes, validation_nodes)
        except Exception as e:
            print(f"[ERROR] Failed benchmarking {name}: {e}")

if __name__ == "__main__":
    main()
