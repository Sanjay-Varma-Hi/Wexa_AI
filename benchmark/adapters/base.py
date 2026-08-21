from abc import ABC, abstractmethod

class DatabaseAdapter(ABC):
    """
    Abstract Base Class for all database adapters used in the benchmark suite.
    Enforces equivalent implementations for database connectivity, ingestion,
    read, traversal, aggregation, write, and health check workloads.
    """
    
    @abstractmethod
    def connect(self):
        """Establish connection or session to the target database."""
        pass

    @abstractmethod
    def close(self):
        """Close connections and release resources."""
        pass

    @abstractmethod
    def health_check(self) -> bool:
        """Execute a simple query to verify database readiness."""
        pass

    @abstractmethod
    def clear_data(self):
        """Reset the database to a clean state by removing all nodes and edges."""
        pass

    @abstractmethod
    def create_indexes(self):
        """Create indices/constraints on User(id)."""
        pass

    @abstractmethod
    def load_nodes(self, nodes):
        """Bulk ingest nodes/profiles in chunks."""
        pass

    @abstractmethod
    def load_relationships(self, edges):
        """Bulk ingest directed edge relationships in chunks."""
        pass

    @abstractmethod
    def point_lookup(self, node_id) -> list:
        """Lookup specific profile fields (age, gender, region) by user_id."""
        pass

    @abstractmethod
    def filtered_lookup(self, age, gender) -> int:
        """Count users matching a specific property filter predicate (age AND gender)."""
        pass

    @abstractmethod
    def hop_traversal(self, node_id, hops) -> int:
        """Calculate the count of reachable neighbors at exactly N-hops away."""
        pass

    @abstractmethod
    def run_aggregation(self) -> list:
        """Group users by age and return count groupings."""
        pass

    @abstractmethod
    def write_operation(self, new_id, existing_id):
        """Create a new node and link it to an existing node (for mixed workload write)."""
        pass
