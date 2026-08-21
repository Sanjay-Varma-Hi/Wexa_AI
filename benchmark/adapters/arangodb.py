import os
from arango import ArangoClient
from benchmark.adapters.base import DatabaseAdapter

class ArangoDBAdapter(DatabaseAdapter):
    """
    Adapter for self-hosted local ArangoDB multi-model document store.
    """
    def __init__(self):
        self.uri = os.getenv("ARANGODB_URI", "http://localhost:8529")
        self.user = os.getenv("ARANGODB_USER", "root")
        self.password = os.getenv("ARANGODB_PASSWORD", "rootpassword")
        self.client = None
        self.db = None

    def connect(self):
        self.client = ArangoClient(hosts=self.uri)
        # Create database 'pokec' if it doesn't already exist using system connection
        sys_db = self.client.db('_system', username=self.user, password=self.password)
        if not sys_db.has_database('pokec'):
            sys_db.create_database('pokec')
        self.db = self.client.db('pokec', username=self.user, password=self.password)

    def close(self):
        self.client = None
        self.db = None

    def health_check(self) -> bool:
        try:
            # Query version to verify engine is live and responding
            self.db.version()
            return True
        except Exception:
            return False

    def clear_data(self):
        for col in ['Friend', 'User']:
            if self.db.has_collection(col):
                self.db.delete_collection(col)
        self.db.create_collection('User')
        self.db.create_collection('Friend', edge=True)
        # Create standard hash index on user ID field immediately to ensure clean state has indexes
        self.db.collection('User').add_hash_index(fields=['id'], unique=True)

    def create_indexes(self):
        # Index on User(id) is created during collection initialization in clear_data
        try:
            self.db.collection('User').add_hash_index(fields=['id'], unique=True)
        except Exception:
            pass

    def load_nodes(self, nodes):
        user_coll = self.db.collection('User')
        for i in range(0, len(nodes), 1000):
            batch = nodes[i:i+1000]
            payload = [
                {
                    '_key': str(r['id']), 
                    'id': r['id'], 
                    'public': r['public'], 
                    'gender': r['gender'], 
                    'region': r['region'], 
                    'age': r['age']
                } 
                for r in batch
            ]
            user_coll.insert_many(payload)

    def load_relationships(self, edges):
        friend_coll = self.db.collection('Friend')
        for i in range(0, len(edges), 1000):
            batch = edges[i:i+1000]
            payload = [
                {
                    '_from': f"User/{r['from_id']}", 
                    '_to': f"User/{r['to_id']}"
                } 
                for r in batch
            ]
            friend_coll.insert_many(payload)

    def point_lookup(self, node_id) -> list:
        query = "FOR u IN User FILTER u.id == @id RETURN [u.age, u.gender, u.region]"
        cursor = self.db.aql.execute(query, bind_vars={'id': node_id})
        return cursor.next() if not cursor.empty() else None

    def filtered_lookup(self, age, gender) -> int:
        query = "RETURN LENGTH(FOR u IN User FILTER u.age == @age AND u.gender == @gender RETURN u)"
        cursor = self.db.aql.execute(query, bind_vars={'age': age, 'gender': gender})
        return cursor.next()

    def hop_traversal(self, node_id, hops) -> int:
        query = f"RETURN LENGTH(FOR v IN {hops}..{hops} OUTBOUND CONCAT('User/', @id) Friend RETURN DISTINCT v._key)"
        cursor = self.db.aql.execute(query, bind_vars={'id': str(node_id)})
        return cursor.next()

    def run_aggregation(self) -> list:
        query = "FOR u IN User COLLECT age = u.age WITH COUNT INTO count RETURN [age, count]"
        cursor = self.db.aql.execute(query)
        return list(cursor)

    def write_operation(self, new_id, existing_id):
        query = (
            "INSERT {_key: TO_STRING(@new_id), id: @new_id, public: 1, gender: 1, region: 'test', age: 30} INTO User "
            "INSERT {_from: CONCAT('User/', @existing_id), _to: CONCAT('User/', TO_STRING(@new_id))} INTO Friend"
        )
        self.db.aql.execute(query, bind_vars={'new_id': new_id, 'existing_id': str(existing_id)})
