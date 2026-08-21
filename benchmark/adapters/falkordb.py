import os
from falkordb import FalkorDB
from benchmark.adapters.base import DatabaseAdapter

class FalkorDBAdapter(DatabaseAdapter):
    """
    Adapter for self-hosted local FalkorDB instance.
    Uses FalkorDB GraphBLAS matrix engine.
    """
    def __init__(self):
        self.host = os.getenv("FALKORDB_HOST", "localhost")
        self.port = int(os.getenv("FALKORDB_PORT", 6379))
        self.password = os.getenv("FALKORDB_PASSWORD", None)
        self.client = None
        self.graph = None

    def connect(self):
        self.client = FalkorDB(host=self.host, port=self.port, password=self.password)
        self.graph = self.client.select_graph("pokec")

    def close(self):
        # falkordb client doesn't need explicit close, but we release references
        self.client = None
        self.graph = None

    def health_check(self) -> bool:
        try:
            # Check if redis ping responds
            return self.client.connection.ping()
        except Exception:
            return False

    def clear_data(self):
        try:
            self.graph.delete()
        except Exception:
            pass
        # Re-select the graph to ensure keys are initialized cleanly
        self.graph = self.client.select_graph("pokec")

    def create_indexes(self):
        try:
            self.graph.query("CREATE INDEX FOR (u:User) ON (u.id)")
        except Exception:
            pass

    def load_nodes(self, nodes):
        query = "UNWIND $batch AS r CREATE (:User {id: r.id, public: r.public, gender: r.gender, region: r.region, age: r.age})"
        for i in range(0, len(nodes), 1000):
            self.graph.query(query, {'batch': nodes[i:i+1000]})

    def load_relationships(self, edges):
        query = "UNWIND $batch AS r MATCH (u:User) WHERE u.id = r.from_id MATCH (v:User) WHERE v.id = r.to_id CREATE (u)-[:FRIEND]->(v)"
        for i in range(0, len(edges), 1000):
            self.graph.query(query, {'batch': edges[i:i+1000]})

    def point_lookup(self, node_id) -> list:
        query = "MATCH (u:User {id: $id}) RETURN u.age, u.gender, u.region"
        res = self.graph.query(query, {'id': node_id})
        return res.result_set[0] if res.result_set else None

    def filtered_lookup(self, age, gender) -> int:
        query = "MATCH (u:User) WHERE u.age = $age AND u.gender = $gender RETURN count(u)"
        res = self.graph.query(query, {'age': age, 'gender': gender})
        return res.result_set[0][0] if res.result_set else 0

    def hop_traversal(self, node_id, hops) -> int:
        if hops == 1:
            query = "MATCH (u:User {id: $id})-[:FRIEND]->(v) RETURN count(v)"
        elif hops == 2:
            query = "MATCH (u:User {id: $id})-[:FRIEND]->()-[:FRIEND]->(v) RETURN count(distinct v)"
        elif hops == 3:
            query = "MATCH (u:User {id: $id})-[:FRIEND]->()-[:FRIEND]->()-[:FRIEND]->(v) RETURN count(distinct v)"
        else:
            raise ValueError("Supported hops are 1, 2, or 3")
            
        res = self.graph.query(query, {'id': node_id})
        return res.result_set[0][0] if res.result_set else 0

    def run_aggregation(self) -> list:
        query = "MATCH (u:User) RETURN u.age, count(u)"
        res = self.graph.query(query)
        return res.result_set

    def write_operation(self, new_id, existing_id):
        query = (
            "CREATE (n:User {id: $new_id, public: 1, gender: 1, region: 'test', age: 30}) "
            "WITH n MATCH (u:User {id: $existing_id}) "
            "CREATE (u)-[:FRIEND]->(n)"
        )
        self.graph.query(query, {'new_id': new_id, 'existing_id': existing_id})
