import os
import gzip
import urllib.request
import collections
import csv

# URLs for Stanford SNAP Pokec social network dataset
REL_URL = "https://snap.stanford.edu/data/soc-pokec-relationships.txt.gz"
PROF_URL = "https://snap.stanford.edu/data/soc-pokec-profiles.txt.gz"

DATA_DIR = "data"
REL_PATH = os.path.join(DATA_DIR, "soc-pokec-relationships.txt.gz")
PROF_PATH = os.path.join(DATA_DIR, "soc-pokec-profiles.txt.gz")
NODES_OUT = os.path.join(DATA_DIR, "nodes_sample.csv")
EDGES_OUT = os.path.join(DATA_DIR, "edges_sample.csv")

LIMIT_NODES = 15000

# Download raw data from Stanford SNAP
def download_file(url, path):
    if os.path.exists(path):
        return
    print(f"Downloading {url}...")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    urllib.request.urlretrieve(url, path)

# Extract a dense subgraph from raw data using BFS
def sample_subgraph():
    print("Sampling subgraph...")
    adj = collections.defaultdict(list)
    
    # Read first 1.5M lines to build initial adjacency list
    with gzip.open(REL_PATH, 'rt', encoding='utf-8') as f:
        for i, line in enumerate(f):
            parts = line.strip().split('\t')
            if len(parts) >= 2:
                u, v = int(parts[0]), int(parts[1])
                adj[u].append(v)
            if i >= 1500000:
                break
                
    # Run BFS starting from the node with highest degree for a connected component
    start = max(adj.keys(), key=lambda k: len(adj[k]))
    visited = {start}
    queue = collections.deque([start])
    
    while queue and len(visited) < LIMIT_NODES:
        curr = queue.popleft()
        for neighbor in adj[curr]:
            if neighbor not in visited:
                visited.add(neighbor)
                queue.append(neighbor)
                if len(visited) >= LIMIT_NODES:
                    break
                    
    # Fallback: grab extra nodes to ensure we hit exactly 15k
    if len(visited) < LIMIT_NODES:
        for node in adj:
            if node not in visited:
                visited.add(node)
                if len(visited) >= LIMIT_NODES:
                    break
                    
    # Filter edges so we only keep connections between our 15k sampled nodes
    edges = []
    with gzip.open(REL_PATH, 'rt', encoding='utf-8') as f:
        for line in f:
            parts = line.strip().split('\t')
            if len(parts) >= 2:
                u, v = int(parts[0]), int(parts[1])
                if u in visited and v in visited:
                    edges.append((u, v))
    return visited, edges

# Parse profiles and write both nodes and edges to CSV
def write_data(selected_nodes, edges):
    print("Extracting profile attributes...")
    profiles = {}
    
    with gzip.open(PROF_PATH, 'rt', encoding='utf-8', errors='ignore') as f:
        for line in f:
            parts = line.strip().split('\t')
            if len(parts) >= 1:
                try:
                    uid = int(parts[0])
                except ValueError:
                    continue
                if uid in selected_nodes:
                    profiles[uid] = {
                        'id': uid,
                        'public': int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else None,
                        'gender': int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else None,
                        'region': parts[4].strip() if len(parts) > 4 else "",
                        'age': int(parts[7]) if len(parts) > 7 and parts[7].isdigit() else None
                    }
                    
    # Ensure all sampled nodes have at least default profile values
    for uid in selected_nodes:
        if uid not in profiles:
            profiles[uid] = {'id': uid, 'public': None, 'gender': None, 'region': '', 'age': None}

    # Save user node attributes
    with open(NODES_OUT, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=['id', 'public', 'gender', 'region', 'age'])
        writer.writeheader()
        for uid in sorted(profiles.keys()):
            writer.writerow(profiles[uid])

    # Save relationship edges
    with open(EDGES_OUT, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['from_id', 'to_id'])
        writer.writerows(edges)

if __name__ == "__main__":
    os.makedirs(DATA_DIR, exist_ok=True)
    download_file(REL_URL, REL_PATH)
    download_file(PROF_URL, PROF_PATH)
    nodes, edges = sample_subgraph()
    write_data(nodes, edges)
    print(f"Subgraph generated: {len(nodes)} nodes, {len(edges)} edges.")
