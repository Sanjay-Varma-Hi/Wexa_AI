import os
import sys
import time
import socket
import subprocess
from dotenv import load_dotenv

# Ensure environment variables are loaded
load_dotenv()

NODES_CSV = "data/nodes_sample.csv"
EDGES_CSV = "data/edges_sample.csv"

# Target local database readiness checks
REQUIRED_LOCAL_PORTS = {
    "ArangoDB": ("localhost", 8529),
    "FalkorDB": ("localhost", 6379),
    "Memgraph": ("localhost", 7687),
    "Neo4j": ("localhost", 7473)
}

def verify_credentials():
    print("[INFO] Phase 1: Verifying environment credentials...")
    if not os.path.exists(".env"):
        print("[ERROR] .env file not found. Copy .env.template to .env and fill in variables.")
        sys.exit(1)
        
    cognodb_uri = os.getenv("COGNODB_URI")
    cognodb_pw = os.getenv("COGNODB_PASSWORD")
    
    if not cognodb_uri or not cognodb_pw:
        print("[ERROR] CognoDB credentials missing in .env. Both COGNODB_URI and COGNODB_PASSWORD are required.")
        sys.exit(1)
        
    print("[INFO] Credentials validation passed.")

def check_docker_containers():
    print("[INFO] Phase 2: Starting and checking local Docker databases...")
    try:
        # Stop existing containers and prune volumes to guarantee clean start state
        print("[INFO] Executing 'docker compose down -v'...")
        subprocess.run(["docker", "compose", "down", "-v"], check=True)
        # Trigger docker compose up
        print("[INFO] Executing 'docker compose up -d'...")
        subprocess.run(["docker", "compose", "up", "-d"], check=True)
    except Exception as e:
        print(f"[ERROR] Failed to start Docker Compose containers: {e}")
        sys.exit(1)
        
    # Poll ports until they are actively responding (readiness checks with backoff)
    print("[INFO] Waiting for local databases to become healthy and ready...")
    for name, (host, port) in REQUIRED_LOCAL_PORTS.items():
        retries = 30
        connected = False
        backoff = 2.0
        
        print(f"[INFO] Probing connection to {name} on {host}:{port}...")
        for i in range(retries):
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(2.0)
                s.connect((host, port))
                s.close()
                connected = True
                print(f"[INFO] {name} is ready.")
                break
            except (ConnectionRefusedError, socket.timeout):
                time.sleep(backoff)
                
        if not connected:
            print(f"[ERROR] Database {name} failed to become ready on port {port} after 60 seconds.")
            print("[INFO] Ensure Docker is running and run 'docker compose ps' to diagnose.")
            sys.exit(1)

def ensure_dataset():
    print("[INFO] Phase 3: Validating dataset availability...")
    if not os.path.exists(NODES_CSV) or not os.path.exists(EDGES_CSV):
        print("[INFO] Sampled CSV files missing. Invoking preprocess.py to generate dataset...")
        try:
            # Run preprocess.py using the current Python environment
            subprocess.run([sys.executable, "preprocess.py"], check=True)
        except Exception as e:
            print(f"[ERROR] Failed executing preprocess.py: {e}")
            sys.exit(1)
    else:
        print("[INFO] Dataset sampled files nodes_sample.csv and edges_sample.csv verified.")

def run_suite():
    print("[INFO] Phase 4: Starting benchmark execution...")
    try:
        # Import and run the benchmark runner main
        from benchmark.runner import main as run_runner
        run_runner()
    except Exception as e:
        print(f"[ERROR] Benchmark runner failed: {e}")
        sys.exit(1)

def build_report():
    print("[INFO] Phase 5: Generating results report and charts...")
    try:
        subprocess.run([sys.executable, "generate_report.py"], check=True)
    except Exception as e:
        print(f"[ERROR] Report generation failed: {e}")
        sys.exit(1)

def main():
    print("="*60 + "\nCOGNDB & GRAPH DB CLOUD BENCHMARK SUITE RUNNER\n" + "="*60)
    verify_credentials()
    check_docker_containers()
    ensure_dataset()
    run_suite()
    build_report()
    print("[INFO] Benchmark execution finished successfully.")
    print("="*60)

if __name__ == "__main__":
    main()
