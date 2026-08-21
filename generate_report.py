import os
import json
import csv
import matplotlib.pyplot as plt
import numpy as np

RAW_DIR = "results/raw"
CHARTS_DIR = "charts"
SUMMARY_CSV = "results/summary.csv"

def generate_reports():
    print("[INFO] Phase 6: Reading raw benchmark JSON logs...")
    raw_files = [f for f in os.listdir(RAW_DIR) if f.endswith(".json")]
    
    results = {}
    for rf in raw_files:
        path = os.path.join(RAW_DIR, rf)
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            results[data["database"]] = data
            
    if not results:
        print("[WARNING] No raw results files found. Skipping report generation.")
        return
        
    os.makedirs(CHARTS_DIR, exist_ok=True)
    os.makedirs(os.path.dirname(SUMMARY_CSV), exist_ok=True)
    
    # 1. Output summary.csv
    print("[INFO] Writing results summary.csv...")
    with open(SUMMARY_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "Database", "Version", "Ingest Nodes/s", "Ingest Edges/s", "Ingest Time (s)",
            "1-Hop p50 (ms)", "1-Hop p95 (ms)", "2-Hop p50 (ms)", "2-Hop p95 (ms)",
            "3-Hop p50 (ms)", "3-Hop p95 (ms)", "Point Lookup p50 (ms)", "Point Lookup p95 (ms)",
            "Filtered Lookup p50 (ms)", "Filtered Lookup p95 (ms)", "Aggregation p50 (ms)", "Aggregation p95 (ms)",
            "C=1 QPS", "C=10 QPS", "C=40 QPS"
        ])
        for db, data in results.items():
            ing = data["ingestion"]
            wl = data["workloads"]
            cc = data["concurrency_sweeps"]
            writer.writerow([
                db,
                data.get("database_version", "Unknown"),
                f"{ing.get('nodes_per_sec', 0):.2f}",
                f"{ing.get('edges_per_sec', 0):.2f}",
                f"{ing.get('total_time_s', 0):.2f}",
                f"{wl.get('1-hop', {}).get('p50', 0):.2f}",
                f"{wl.get('1-hop', {}).get('p95', 0):.2f}",
                f"{wl.get('2-hop', {}).get('p50', 0):.2f}",
                f"{wl.get('2-hop', {}).get('p95', 0):.2f}",
                f"{wl.get('3-hop', {}).get('p50', 0):.2f}",
                f"{wl.get('3-hop', {}).get('p95', 0):.2f}",
                f"{wl.get('point_lookup', {}).get('p50', 0):.2f}",
                f"{wl.get('point_lookup', {}).get('p95', 0):.2f}",
                f"{wl.get('filtered_lookup', {}).get('p50', 0):.2f}",
                f"{wl.get('filtered_lookup', {}).get('p95', 0):.2f}",
                f"{wl.get('aggregation', {}).get('p50', 0):.2f}",
                f"{wl.get('aggregation', {}).get('p95', 0):.2f}",
                f"{cc.get('1', {}).get('qps', 0):.2f}",
                f"{cc.get('10', {}).get('qps', 0):.2f}",
                f"{cc.get('40', {}).get('qps', 0):.2f}"
            ])
            
    # 2. Plot traversals latency comparison
    print("[INFO] Generating latency comparison charts...")
    dbs = list(results.keys())
    hops = ['1-hop', '2-hop', '3-hop']
    x = np.arange(len(hops))
    width = 0.15
    
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))
    
    for i, db in enumerate(dbs):
        wl = results[db]["workloads"]
        p50s = [wl.get(h, {}).get("p50", 0) for h in hops]
        p95s = [wl.get(h, {}).get("p95", 0) for h in hops]
        offset = (i - len(dbs)/2) * width + width/2
        
        ax1.bar(x + offset, p50s, width, label=db)
        ax2.bar(x + offset, p95s, width, label=db)
        
    ax1.set_title("p50 Hop Traversal Latency (Log-Scale)")
    ax1.set_xticks(x)
    ax1.set_xticklabels(hops)
    ax1.set_ylabel("Latency (ms)")
    ax1.set_yscale('log')
    ax1.grid(True, linestyle="--", alpha=0.3)
    
    ax2.set_title("p95 Hop Traversal Latency (Log-Scale)")
    ax2.set_xticks(x)
    ax2.set_xticklabels(hops)
    ax2.set_ylabel("Latency (ms)")
    ax2.set_yscale('log')
    ax2.grid(True, linestyle="--", alpha=0.3)
    
    plt.legend(bbox_to_anchor=(1.05, 1), loc='upper left')
    plt.tight_layout()
    plt.savefig(os.path.join(CHARTS_DIR, "latency_comparison.png"), dpi=300, bbox_inches='tight')
    plt.close()
    
    # 3. Plot mixed concurrent throughput comparison
    print("[INFO] Generating mixed throughput comparison charts...")
    plt.figure(figsize=(8, 5))
    concurrencies = [1, 10, 40]
    
    for db in dbs:
        cc = results[db]["concurrency_sweeps"]
        qps_vals = [cc.get(str(c), {}).get("qps", 0) for c in concurrencies]
        plt.plot(concurrencies, qps_vals, marker='o', linewidth=2, label=db)
        
    plt.title("Mixed Concurrent Workload Throughput (90% Read / 10% Write)")
    plt.xlabel("Concurrency Level (Client Threads)")
    plt.ylabel("Throughput (Queries Per Second)")
    plt.xticks(concurrencies)
    plt.grid(True, linestyle="--", alpha=0.5)
    plt.legend()
    plt.tight_layout()
    plt.savefig(os.path.join(CHARTS_DIR, "throughput_comparison.png"), dpi=300)
    plt.close()
    
    # 4. Generate results matrix in console
    print("\n" + "="*80 + "\nBENCHMARK RESULTS MATRIX SUMMARY\n" + "="*80)
    headers = [
        "Database", "Ingest(s)", "1-Hop p50", "2-Hop p50", "3-Hop p50", 
        "Point p50", "Filt p50", "Agg p50", "QPS (C=1/10/40)", "Error Rate (C=40)"
    ]
    print("| " + " | ".join(headers) + " |")
    print("|" + "|".join(["---" for _ in headers]) + "|")
    
    for db, data in results.items():
        ing = data["ingestion"]
        wl = data["workloads"]
        cc = data["concurrency_sweeps"]
        
        row = [
            db,
            f"{ing.get('total_time_s', 0):.2f}s",
            f"{wl.get('1-hop', {}).get('p50', 0):.2f}ms",
            f"{wl.get('2-hop', {}).get('p50', 0):.2f}ms",
            f"{wl.get('3-hop', {}).get('p50', 0):.2f}ms",
            f"{wl.get('point_lookup', {}).get('p50', 0):.2f}ms",
            f"{wl.get('filtered_lookup', {}).get('p50', 0):.2f}ms",
            f"{wl.get('aggregation', {}).get('p50', 0):.2f}ms",
            f"{cc.get('1', {}).get('qps', 0):.1f}/{cc.get('10', {}).get('qps', 0):.1f}/{cc.get('40', {}).get('qps', 0):.1f}",
            f"{cc.get('40', {}).get('error_rate', 0)*100:.1f}%"
        ]
        print("| " + " | ".join(row) + " |")
    print("="*80 + "\n")

if __name__ == "__main__":
    generate_reports()
