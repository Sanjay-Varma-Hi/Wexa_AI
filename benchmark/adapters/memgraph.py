import os
from neo4j import GraphDatabase
from benchmark.adapters.base import DatabaseAdapter

class MemgraphAdapter(DatabaseAdapter):
    """
    Adapter for self-hosted local Memgraph instance.
    """
    def __init__(self):
        self.uri = os.getenv("MEMGRAPH_URI", "bolt://localhost:7687")
        self.driver = None

    def connect(self):
        # Memgraph defaults to empty username and password in this benchmark setup
        self.driver = GraphDatabase.driver(self.uri)

    def close(self):
        if self.driver:
            self.driver.close()

    def health_check(self) -> bool:
        try:
            with self.driver.session() as session:
                result = session.run("RETURN 1 AS val")
                single = result.single()
                return single and single["val"] == 1
        except Exception:
            return False

    def clear_data(self):
        with self.driver.session() as session:
            # Batch edge deletions to ensure memory safety
            while True:
                res = session.run("MATCH ()-[r:FRIEND]->() WITH r LIMIT 10000 DELETE r RETURN count(r)")
                val = res.single()[0]
                if val == 0:
                    break
            # Batch node deletions
            while True:
                res = session.run("MATCH (n) WITH n LIMIT 10000 DELETE n RETURN count(n)")
                val = res.single()[0]
                if val == 0:
                    break
            try:
                session.run("DROP CONSTRAINT ON (u:User) ASSERT u.id IS UNIQUE").consume()
            except Exception:
                pass

    def create_indexes(self):
        with self.driver.session() as session:
            try:
                session.run("CREATE CONSTRAINT ON (u:User) ASSERT u.id IS UNIQUE").consume()
            except Exception:
                pass
            try:
                session.run("CREATE INDEX ON :User(id)").consume()
            except Exception:
                pass

    def load_nodes(self, nodes):
        query = "UNWIND $batch AS r CREATE (:User {id: r.id, public: r.public, gender: r.gender, region: r.region, age: r.age})"
        with self.driver.session() as session:
            for i in range(0, len(nodes), 1000):
                session.run(query, batch=nodes[i:i+1000]).consume()

    def load_relationships(self, edges):
        # Optimization: Memgraph requires explicit WHERE filtering on User ID index
        # rather than inline property matches inside UNWIND to avoid O(N) full scans.
        query = "UNWIND $batch AS r MATCH (u:User) WHERE u.id = r.from_id MATCH (v:User) WHERE v.id = r.to_id CREATE (u)-[:FRIEND]->(v)"
        with self.driver.session() as session:
            for i in range(0, len(edges), 1000):
                session.run(query, batch=edges[i:i+1000]).consume()

    def point_lookup(self, node_id) -> list:
        query = "MATCH (u:User {id: $id}) RETURN u.age, u.gender, u.region"
        with self.driver.session() as session:
            rec = session.run(query, id=node_id).single()
            return rec.values() if rec else None

    def filtered_lookup(self, age, gender) -> int:
        query = "MATCH (u:User) WHERE u.age = $age AND u.gender = $gender RETURN count(u)"
        with self.driver.session() as session:
            return session.run(query, age=age, gender=gender).single()[0]

    def hop_traversal(self, node_id, hops) -> int:
        if hops == 1:
            query = "MATCH (u:User {id: $id})-[:FRIEND]->(v) RETURN count(v)"
        elif hops == 2:
            query = "MATCH (u:User {id: $id})-[:FRIEND]->()-[:FRIEND]->(v) RETURN count(distinct v)"
        elif hops == 3:
            query = "MATCH (u:User {id: $id})-[:FRIEND]->()-[:FRIEND]->()-[:FRIEND]->(v) RETURN count(distinct v)"
        else:
            raise ValueError("Supported hops are 1, 2, or 3")
            
        with self.driver.session() as session:
            return session.run(query, id=node_id).single()[0]

    def run_aggregation(self) -> list:
        query = "MATCH (u:User) RETURN u.age, count(u)"
        with self.driver.session() as session:
            return [rec.values() for rec in session.run(query)]

    def write_operation(self, new_id, existing_id):
        query = (
            "CREATE (n:User {id: $new_id, public: 1, gender: 1, region: 'test', age: 30}) "
            "WITH n MATCH (u:User {id: $existing_id}) "
            "CREATE (u)-[:FRIEND]->(n)"
        )
        with self.driver.session() as session:
            session.run(query, new_id=new_id, existing_id=existing_id).consume()
