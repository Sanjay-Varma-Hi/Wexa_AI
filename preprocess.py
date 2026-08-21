import os
import gzip
import urllib.request
import collections
import csv
import json
import time

REL_URL = "https://snap.stanford.edu/data/soc-pokec-relationships.txt.gz"
PROF_URL = "https://snap.stanford.edu/data/soc-pokec-profiles.txt.gz"

DATA_DIR = "data"
RESULTS_DIR = "results"
REL_PATH = os.path.join(DATA_DIR, "soc-pokec-relationships.txt.gz")
PROF_PATH = os.path.join(DATA_DIR, "soc-pokec-profiles.txt.gz")
NODES_OUT = os.path.join(DATA_DIR, "nodes_sample.csv")
EDGES_OUT = os.path.join(DATA_DIR, "edges_sample.csv")
METADATA_OUT = os.path.join(RESULTS_DIR, "metadata.json")

LIMIT_NODES = 15000

def download_file(url, path):
    if os.path.exists(path):
        print(f"[INFO] File {path} already exists. Skipping download.")
        return
    print(f"[INFO] Downloading {url}...")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    urllib.request.urlretrieve(url, path)

def sample_subgraph():
    print("[INFO] Phase 1: Finding the global highest out-degree seed node...")
    out_degrees = collections.defaultdict(int)
    total_source_relationships = 0
    
    # First pass: stream the relationships file to get exact degrees and total count
    # without holding all edges in memory
    with gzip.open(REL_PATH, 'rt', encoding='utf-8') as f:
        for line in f:
            total_source_relationships += 1
            parts = line.strip().split('\t')
            if len(parts) >= 2:
                u = int(parts[0])
                out_degrees[u] += 1
                
    # Find the absolute highest out-degree node globally
    seed_node = max(out_degrees.keys(), key=lambda k: out_degrees[k])
    seed_degree = out_degrees[seed_node]
    print(f"[INFO] Global seed node identified: ID={seed_node} with Out-Degree={seed_degree}")
    
    print("[INFO] Phase 2: Building sorted adjacency lists for deterministic BFS...")
    adj = collections.defaultdict(list)
    with gzip.open(REL_PATH, 'rt', encoding='utf-8') as f:
        for line in f:
            parts = line.strip().split('\t')
            if len(parts) >= 2:
                u, v = int(parts[0]), int(parts[1])
                adj[u].append(v)
                
    # Sort neighbor lists to guarantee deterministic BFS traversal order
    for u in adj:
        adj[u].sort()
        
    print("[INFO] Phase 3: Executing deterministic BFS traversal...")
    visited = {seed_node}
    queue = collections.deque([seed_node])
    
    while queue and len(visited) < LIMIT_NODES:
        curr = queue.popleft()
        for neighbor in adj[curr]:
            if neighbor not in visited:
                visited.add(neighbor)
                queue.append(neighbor)
                if len(visited) >= LIMIT_NODES:
                    break
                    
    # Fallback in case of disconnected components
    if len(visited) < LIMIT_NODES:
        print("[WARNING] BFS traversal queue exhausted before reaching target node limit. Appending extra nodes.")
        for node in sorted(adj.keys()):
            if node not in visited:
                visited.add(node)
                if len(visited) >= LIMIT_NODES:
                    break
                    
    print("[INFO] Phase 4: Filtering relationships within the sampled node set...")
    edges = []
    # Read relationships one more time to extract the exact induced subgraph
    with gzip.open(REL_PATH, 'rt', encoding='utf-8') as f:
        for line in f:
            parts = line.strip().split('\t')
            if len(parts) >= 2:
                u, v = int(parts[0]), int(parts[1])
                if u in visited and v in visited:
                    edges.append((u, v))
                    
    return visited, edges, total_source_relationships, seed_node

def write_data(selected_nodes, edges, total_source_relationships, seed_node):
    print("[INFO] Phase 5: Extracting profile attributes...")
    profiles = {}
    nodes_with_profiles = 0
    
    with gzip.open(PROF_PATH, 'rt', encoding='utf-8', errors='ignore') as f:
        for line in f:
            parts = line.strip().split('\t')
            if len(parts) >= 1:
                try:
                    uid = int(parts[0])
                except ValueError:
                    continue
                if uid in selected_nodes:
                    nodes_with_profiles += 1
                    profiles[uid] = {
                        'id': uid,
                        'public': int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else None,
                        'gender': int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else None,
                        'region': parts[4].strip() if len(parts) > 4 else "",
                        'age': int(parts[7]) if len(parts) > 7 and parts[7].isdigit() else None
                    }
                    
    # Ensure every single selected node exists in the profile dataset
    for uid in selected_nodes:
        if uid not in profiles:
            profiles[uid] = {'id': uid, 'public': None, 'gender': None, 'region': '', 'age': None}
            
    missing_profiles = len(selected_nodes) - nodes_with_profiles

    # Write nodes file
    with open(NODES_OUT, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=['id', 'public', 'gender', 'region', 'age'])
        writer.writeheader()
        for uid in sorted(profiles.keys()):
            writer.writerow(profiles[uid])

    # Write edges file
    with open(EDGES_OUT, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['from_id', 'to_id'])
        # Sort edges to ensure file output is fully deterministic
        writer.writerows(sorted(edges))
        
    avg_out_degree = len(edges) / len(selected_nodes)
    
    metadata = {
        "dataset_name": "Stanford SNAP soc-Pokec",
        "dataset_url": "https://snap.stanford.edu/data/soc-Pokec.html",
        "total_source_relationships": total_source_relationships,
        "sampled_nodes": len(selected_nodes),
        "sampled_relationships": len(edges),
        "sampling_method": f"BFS starting from global highest out-degree seed node ({seed_node})",
        "seed_node": seed_node,
        "nodes_with_profile_attributes": nodes_with_profiles,
        "missing_profiles": missing_profiles,
        "average_out_degree": avg_out_degree,
        "generation_timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    }
    
    os.makedirs(RESULTS_DIR, exist_ok=True)
    with open(METADATA_OUT, 'w', encoding='utf-8') as f:
        json.dump(metadata, f, indent=4)
        
    print("\n" + "="*50 + "\nDATASET METADATA GENERATED\n" + "="*50)
    for k, v in metadata.items():
        print(f"{k}: {v}")
    print("="*50 + "\n")

if __name__ == "__main__":
    os.makedirs(DATA_DIR, exist_ok=True)
    download_file(REL_URL, REL_PATH)
    download_file(PROF_URL, PROF_PATH)
    nodes, edges, total_source_rel, seed_node = sample_subgraph()
    write_data(nodes, edges, total_source_rel, seed_node)
