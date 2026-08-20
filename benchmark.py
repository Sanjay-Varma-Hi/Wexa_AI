import os
import csv
import time
import random
import threading
import numpy as np
import json
from dotenv import load_dotenv

# Database drivers
from neo4j import GraphDatabase
from arango import ArangoClient
from falkordb import FalkorDB

# Visualization
import matplotlib.pyplot as plt

load_dotenv()

NODES_CSV = "data/nodes_sample.csv"
EDGES_CSV = "data/edges_sample.csv"
LAT_ITERS = 100
CONCURRENCY = [1, 10, 40]

# --- Database Operations ---

# Wipe existing database data before running benchmarks
def clear_db(db_type, conn):
    if db_type == "bolt":
        with conn.session() as s:
            # Delete edges in batches of 10,000 to avoid transaction memory OOM crashes
            while s.run("MATCH ()-[r:FRIEND]->() WITH r LIMIT 10000 DELETE r RETURN count(r)").single()[0] > 0: pass
            # Delete nodes in batches of 10,000
            while s.run("MATCH (n) WITH n LIMIT 10000 DETACH DELETE n RETURN count(n)").single()[0] > 0: pass
            try: s.run("DROP CONSTRAINT user_id_unique").consume()
            except Exception: pass
    elif db_type == "falkor":
        try: conn.delete()
        except Exception: pass
        return conn  # Return graph connection reference
    elif db_type == "arango":
        for col in ['Friend', 'User']:
            if conn.has_collection(col): conn.delete_collection(col)
        conn.create_collection('User')
        conn.create_collection('Friend', edge=True)
        # Create standard hash index on user ID field
        conn.collection('User').add_hash_index(fields=['id'], unique=True)
    return conn

# Create indices on User(id) to ensure point lookups are optimized
def create_indices(db_type, conn):
    if db_type == "bolt":
        with conn.session() as s:
            # Try constraint creation first (varies by neo4j/memgraph syntax versions)
            try: s.run("CREATE CONSTRAINT ON (u:User) ASSERT u.id IS UNIQUE").consume()
            except Exception:
                try: s.run("CREATE CONSTRAINT user_id_unique FOR (u:User) REQUIRE u.id IS UNIQUE").consume()
                except Exception: pass
            try: s.run("CREATE INDEX FOR (u:User) ON (u.id)").consume()
            except Exception:
                try: s.run("CREATE INDEX ON :User(id)").consume()
                except Exception: pass
    elif db_type == "falkor":
        try: conn.query("CREATE INDEX FOR (u:User) ON (u.id)")
        except Exception: pass

# Import nodes and relationships in 1,000-element chunks
def ingest_data(db_type, conn, nodes, edges):
    if db_type == "bolt":
        with conn.session() as s:
            for i in range(0, len(nodes), 1000):
                s.run("UNWIND $batch AS r CREATE (:User {id:r.id, public:r.public, gender:r.gender, region:r.region, age:r.age})", batch=nodes[i:i+1000]).consume()
            for i in range(0, len(edges), 1000):
                s.run("UNWIND $batch AS r MATCH (u:User) WHERE u.id=r.from_id MATCH (v:User) WHERE v.id=r.to_id CREATE (u)-[:FRIEND]->(v)", batch=edges[i:i+1000]).consume()
    elif db_type == "falkor":
        for i in range(0, len(nodes), 1000):
            conn.query("UNWIND $batch AS r CREATE (:User {id:r.id, public:r.public, gender:r.gender, region:r.region, age:r.age})", {'batch': nodes[i:i+1000]})
        for i in range(0, len(edges), 1000):
            conn.query("UNWIND $batch AS r MATCH (u:User) WHERE u.id=r.from_id MATCH (v:User) WHERE v.id=r.to_id CREATE (u)-[:FRIEND]->(v)", {'batch': edges[i:i+1000]})
    elif db_type == "arango":
        user_coll = conn.collection('User')
        friend_coll = conn.collection('Friend')
        for i in range(0, len(nodes), 1000):
            batch = nodes[i:i+1000]
            payload = [{'_key': str(r['id']), 'id': r['id'], 'public': r['public'], 'gender': r['gender'], 'region': r['region'], 'age': r['age']} for r in batch]
            user_coll.insert_many(payload)
        for i in range(0, len(edges), 1000):
            batch = edges[i:i+1000]
            payload = [{'_from': f"User/{r['from_id']}", '_to': f"User/{r['to_id']}"} for r in batch]
            friend_coll.insert_many(payload)

# Execute depth-hop friendship traversals
def run_traversal(db_type, conn, node_id, hops):
    if db_type == "bolt":
        with conn.session() as s:
            if hops == 1: q = "MATCH (u:User {id: $id})-[:FRIEND]->(v) RETURN count(v)"
            elif hops == 2: q = "MATCH (u:User {id: $id})-[:FRIEND]->()-[:FRIEND]->(v) RETURN count(distinct v)"
            elif hops == 3: q = "MATCH (u:User {id: $id})-[:FRIEND]->()-[:FRIEND]->()-[:FRIEND]->(v) RETURN count(distinct v)"
            return s.run(q, id=node_id).single()[0]
    elif db_type == "falkor":
        if hops == 1: q = "MATCH (u:User {id: $id})-[:FRIEND]->(v) RETURN count(v)"
        elif hops == 2: q = "MATCH (u:User {id: $id})-[:FRIEND]->()-[:FRIEND]->(v) RETURN count(distinct v)"
        elif hops == 3: q = "MATCH (u:User {id: $id})-[:FRIEND]->()-[:FRIEND]->()-[:FRIEND]->(v) RETURN count(distinct v)"
        return conn.query(q, {'id': node_id}).result_set[0][0]
    elif db_type == "arango":
        q = f"RETURN LENGTH(FOR v IN {hops}..{hops} OUTBOUND CONCAT('User/', @id) Friend RETURN DISTINCT v._key)"
        return conn.aql.execute(q, bind_vars={'id': str(node_id)}).next()

# Lookup user profile attributes by exact ID
def run_point_lookup(db_type, conn, node_id):
    if db_type == "bolt":
        with conn.session() as s:
            rec = s.run("MATCH (u:User {id: $id}) RETURN u.age, u.gender, u.region", id=node_id).single()
            return rec.values() if rec else None
    elif db_type == "falkor":
        res = conn.query("MATCH (u:User {id: $id}) RETURN u.age, u.gender, u.region", {'id': node_id})
        return res.result_set[0] if res.result_set else None
    elif db_type == "arango":
        cursor = conn.aql.execute("FOR u IN User FILTER u.id == @id RETURN [u.age, u.gender, u.region]", bind_vars={'id': node_id})
        return cursor.next() if not cursor.empty() else None

# Filter nodes matching age and gender criteria
def run_filtered_lookup(db_type, conn, age, gender):
    if db_type == "bolt":
        with conn.session() as s:
            return s.run("MATCH (u:User) WHERE u.age = $age AND u.gender = $gender RETURN count(u)", age=age, gender=gender).single()[0]
    elif db_type == "falkor":
        return conn.query("MATCH (u:User) WHERE u.age = $age AND u.gender = $gender RETURN count(u)", {'age': age, 'gender': gender}).result_set[0][0]
    elif db_type == "arango":
        return conn.aql.execute("RETURN LENGTH(FOR u IN User FILTER u.age == @age AND u.gender == @gender RETURN u)", bind_vars={'age': age, 'gender': gender}).next()

# Run a count grouping profiles by age
def run_aggregation(db_type, conn):
    if db_type == "bolt":
        with conn.session() as s: return list(s.run("MATCH (u:User) RETURN u.age, count(u)"))
    elif db_type == "falkor":
        return conn.query("MATCH (u:User) RETURN u.age, count(u)").result_set
    elif db_type == "arango":
        return list(conn.aql.execute("FOR u IN User COLLECT age = u.age WITH COUNT INTO count RETURN [age, count]"))

# Create a new user node and link it to an existing user
def run_write(db_type, conn, new_id, existing_id):
    if db_type == "bolt":
        with conn.session() as s:
            s.run("CREATE (n:User {id: $new_id, public: 1, gender: 1, region: 'test', age: 30}) WITH n MATCH (u:User {id: $existing_id}) CREATE (u)-[:FRIEND]->(n)", new_id=new_id, existing_id=existing_id).consume()
    elif db_type == "falkor":
        conn.query("CREATE (n:User {id: $new_id, public: 1, gender: 1, region: 'test', age: 30}) WITH n MATCH (u:User {id: $existing_id}) CREATE (u)-[:FRIEND]->(n)", {'new_id': new_id, 'existing_id': existing_id})
    elif db_type == "arango":
        conn.aql.execute("INSERT {_key: TO_STRING(@new_id), id: @new_id, public: 1, gender: 1, region: 'test', age: 30} INTO User INSERT {_from: CONCAT('User/', @existing_id), _to: CONCAT('User/', TO_STRING(@new_id))} INTO Friend", bind_vars={'new_id': new_id, 'existing_id': str(existing_id)})

# --- Benchmark Runner ---

# Execute function and return time taken in ms
def measure(func, *args):
    start = time.perf_counter()
    func(*args)
    return (time.perf_counter() - start) * 1000.0

# Worker thread execution loop for concurrent mixed read/write throughput
def concurrent_worker(db_type, conn, test_nodes, duration, results_container):
    tx_count = 0
    start = time.time()
    write_id = 90000000 + (threading.get_ident() % 10000) * 10000
    while time.time() - start < duration:
        try:
            if random.random() < 0.9:
                run_traversal(db_type, conn, random.choice(test_nodes), 2)  # 90% reads (2-hop)
            else:
                run_write(db_type, conn, write_id, random.choice(test_nodes))  # 10% writes
                write_id += 1
            tx_count += 1
        except Exception:
            pass
    results_container.append(tx_count)

# Coordinate all metrics gathering for a single database engine
def run_benchmarks(name, db_type, conn, nodes, edges, test_nodes):
    print(f"\nBenchmarking {name}...")
    results = {}
    
    # Ingestion
    start = time.perf_counter()
    ingest_data(db_type, conn, nodes, edges)
    total_ingest = time.perf_counter() - start
    print(f"  Ingestion finished in {total_ingest:.2f}s")
    results['ingest'] = total_ingest
    
    # Warmup loop (20 iterations) to let graph engines build caches
    for nid in test_nodes[:20]:
        try:
            run_traversal(db_type, conn, nid, 1)
            run_point_lookup(db_type, conn, nid)
        except Exception: pass
        
    # Traversals (1, 2, 3 hops)
    for hop in [1, 2, 3]:
        lats = []
        for nid in test_nodes:
            try: lats.append(measure(run_traversal, db_type, conn, nid, hop))
            except Exception: pass
        if lats:
            results[f"{hop}-hop"] = {'p50': np.percentile(lats, 50), 'p95': np.percentile(lats, 95)}
            
    # Point lookups
    lats = [measure(run_point_lookup, db_type, conn, nid) for nid in test_nodes]
    results['point'] = {'p50': np.percentile(lats, 50), 'p95': np.percentile(lats, 95)}
    
    # Filtered profile lookups
    lats = []
    for _ in range(LAT_ITERS):
        age, gender = random.randint(20, 50), random.choice([0, 1])
        try: lats.append(measure(run_filtered_lookup, db_type, conn, age, gender))
        except Exception: pass
    results['filtered'] = {'p50': np.percentile(lats, 50), 'p95': np.percentile(lats, 95)}
    
    # Group-by aggregations
    lats = []
    for _ in range(10):
        try: lats.append(measure(run_aggregation, db_type, conn))
        except Exception: pass
    results['agg'] = {'p50': np.percentile(lats, 50), 'p95': np.percentile(lats, 95)}
    
    # Mixed concurrency sweeps
    mixed_results = {}
    for c in CONCURRENCY:
        threads = []
        counts = []
        start_t = time.perf_counter()
        for _ in range(c):
            t = threading.Thread(target=concurrent_worker, args=(db_type, conn, test_nodes, 10, counts))
            threads.append(t)
            t.start()
        for t in threads: t.join()
        qps = sum(counts) / (time.perf_counter() - start_t)
        print(f"  Concurrency {c}: {qps:.1f} QPS")
        mixed_results[str(c)] = qps
    results['mixed'] = mixed_results
    return results

# Generate matplotlib visualization charts
def generate_plots(results):
    os.makedirs("charts", exist_ok=True)
    dbs = list(results.keys())
    
    # Latency chart
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5))
    hops = ['1-hop', '2-hop', '3-hop']
    x = np.arange(len(hops))
    w = 0.15
    for i, db in enumerate(dbs):
        ax1.bar(x + (i - len(dbs)/2)*w + w/2, [results[db]['reads'].get(h, {}).get('p50', 0) for h in hops], w, label=db)
        ax2.bar(x + (i - len(dbs)/2)*w + w/2, [results[db]['reads'].get(h, {}).get('p95', 0) for h in hops], w, label=db)
    ax1.set_title("p50 Latency (ms)")
    ax1.set_xticks(x)
    ax1.set_xticklabels(hops)
    ax1.set_yscale('log')
    ax2.set_title("p95 Latency (ms)")
    ax2.set_xticks(x)
    ax2.set_xticklabels(hops)
    ax2.set_yscale('log')
    plt.legend()
    plt.savefig("charts/latency_comparison.png", dpi=300)
    plt.close()

    # Throughput QPS chart
    plt.figure(figsize=(7, 4))
    for db in dbs:
        plt.plot(CONCURRENCY, [results[db]['mixed'].get(str(c), 0) for c in CONCURRENCY], marker='o', label=db)
    plt.title("Mixed Throughput (QPS)")
    plt.xlabel("Concurrency")
    plt.ylabel("QPS")
    plt.legend()
    plt.grid(True, linestyle="--", alpha=0.5)
    plt.tight_layout()
    plt.savefig("charts/throughput_comparison.png", dpi=300)
    plt.close()

def main():
    print("Loading CSV files...")
    nodes, edges = [], []
    with open(NODES_CSV, 'r', encoding='utf-8') as f:
        for r in csv.DictReader(f):
            nodes.append({'id': int(r['id']), 'public': int(r['public']) if r['public'] else None, 'gender': int(r['gender']) if r['gender'] else None, 'region': r['region'], 'age': int(r['age']) if r['age'] else None})
    with open(EDGES_CSV, 'r', encoding='utf-8') as f:
        for r in csv.DictReader(f):
            edges.append({'from_id': int(r['from_id']), 'to_id': int(r['to_id'])})
            
    random.seed(42)
    test_nodes = random.sample([n['id'] for n in nodes], LAT_ITERS)
    
    # Establish drivers config from environment
    dbs_config = []
    if os.getenv("COGNODB_URI"):
        dbs_config.append(("CognoDB Cloud", "bolt", GraphDatabase.driver(os.getenv("COGNODB_URI"), auth=(os.getenv("COGNODB_USER"), os.getenv("COGNODB_PASSWORD")))))
    if os.getenv("ARANGODB_URI"):
        sys_db = ArangoClient(hosts=os.getenv("ARANGODB_URI")).db('_system', username=os.getenv("ARANGODB_USER"), password=os.getenv("ARANGODB_PASSWORD"))
        if not sys_db.has_database('pokec'): sys_db.create_database('pokec')
        dbs_config.append(("ArangoDB", "arango", ArangoClient(hosts=os.getenv("ARANGODB_URI")).db('pokec', username=os.getenv("ARANGODB_USER"), password=os.getenv("ARANGODB_PASSWORD"))))
    if os.getenv("FALKORDB_HOST"):
        dbs_config.append(("FalkorDB", "falkor", FalkorDB(host=os.getenv("FALKORDB_HOST"), port=int(os.getenv("FALKORDB_PORT", 6379))).select_graph("pokec")))
    if os.getenv("MEMGRAPH_URI"):
        dbs_config.append(("Memgraph", "bolt", GraphDatabase.driver(os.getenv("MEMGRAPH_URI"))))
    if os.getenv("NEO4J_URI"):
        dbs_config.append(("Neo4j", "bolt", GraphDatabase.driver(os.getenv("NEO4J_URI"), auth=(os.getenv("NEO4J_USER"), os.getenv("NEO4J_PASSWORD")))))

    results = {}
    for name, db_type, conn in dbs_config:
        try:
            conn = clear_db(db_type, conn)
            create_indices(db_type, conn)
            run_res = run_benchmarks(name, db_type, conn, nodes, edges, test_nodes)
            
            results[name] = {
                'ingestion': {
                    'node_rate': len(nodes) / run_res['ingest'] if run_res['ingest'] > 0 else 0,
                    'edge_rate': len(edges) / run_res['ingest'] if run_res['ingest'] > 0 else 0,
                    'total_load_time': run_res['ingest']
                },
                'reads': {
                    '1-hop': run_res.get('1-hop', {}),
                    '2-hop': run_res.get('2-hop', {}),
                    '3-hop': run_res.get('3-hop', {}),
                    'point_lookup': run_res.get('point', {}),
                    'filtered_lookup': run_res.get('filtered', {}),
                    'aggregation': run_res.get('agg', {})
                },
                'mixed': run_res['mixed']
            }
        except Exception as e:
            print(f"Error on {name}: {e}")
        finally:
            if hasattr(conn, "close"): conn.close()
            
    with open("results.json", "w") as f:
        json.dump(results, f, indent=4)
        
    try: generate_plots(results)
    except Exception as e: print(f"Plotting failed: {e}")

    # Output Markdown summary table
    print("\n" + "="*40 + "\nRESULTS MATRIX\n" + "="*40)
    headers = ["Database", "Ingest Nodes/s", "Ingest Edges/s", "Total Ingest (s)", "1-Hop p50/p95", "2-Hop p50/p95", "3-Hop p50/p95", "Point Lk p50/p95", "Filt Lk p50/p95", "Agg p50/p95", "QPS (C=1/10/40)"]
    print("| " + " | ".join(headers) + " |")
    print("|" + "|".join(["---" for _ in headers]) + "|")
    for db, data in results.items():
        ing = data['ingestion']
        r = data['reads']
        m = data['mixed']
        row = [
            db, f"{ing['node_rate']:.1f}", f"{ing['edge_rate']:.1f}", f"{ing['total_load_time']:.2f}",
            f"{r['1-hop'].get('p50',0):.2f}/{r['1-hop'].get('p95',0):.2f}",
            f"{r['2-hop'].get('p50',0):.2f}/{r['2-hop'].get('p95',0):.2f}",
            f"{r['3-hop'].get('p50',0):.2f}/{r['3-hop'].get('p95',0):.2f}",
            f"{r['point_lookup'].get('p50',0):.2f}/{r['point_lookup'].get('p95',0):.2f}",
            f"{r['filtered_lookup'].get('p50',0):.2f}/{r['filtered_lookup'].get('p95',0):.2f}",
            f"{r['aggregation'].get('p50',0):.2f}/{r['aggregation'].get('p95',0):.2f}",
            f"{m.get('1',0):.1f}/{m.get('10',0):.1f}/{m.get('40',0):.1f}"
        ]
        print("| " + " | ".join(row) + " |")

if __name__ == "__main__":
    main()
