"""
Neo4j driver management with retry logic for Aura free-tier.
"""

import os
import time
from neo4j import GraphDatabase
from neo4j.exceptions import ServiceUnavailable, SessionExpired

_driver = None


def get_driver():
    """Return (or create) a Neo4j driver, with SSL fallback."""
    global _driver
    if _driver is not None:
        return _driver

    uri = os.getenv("NEO4J_URI", "")
    user = os.getenv("NEO4J_USERNAME", "neo4j")
    pwd = os.getenv("NEO4J_PASSWORD", "")
    db = os.getenv("NEO4J_DATABASE", "neo4j")

    # Try neo4j+s:// first, fall back to neo4j+ssc:// if SSL cert fails
    for scheme in [uri, uri.replace("neo4j+s://", "neo4j+ssc://")]:
        try:
            d = GraphDatabase.driver(scheme, auth=(user, pwd))
            d.verify_connectivity()
            _driver = d
            print(f"[db] Connected via {scheme}")
            return _driver
        except Exception as e:
            print(f"[db] Failed {scheme}: {e}")

    raise RuntimeError("Cannot connect to Neo4j with any URI scheme")


def _reset_driver():
    """Force-close and clear the cached driver."""
    global _driver
    if _driver:
        try:
            _driver.close()
        except Exception:
            pass
    _driver = None


def run_query(cypher: str, params: dict | None = None, db: str | None = None):
    """Execute a Cypher query with automatic retry on stale connections."""
    database = db or os.getenv("NEO4J_DATABASE", "neo4j")
    for attempt in range(3):
        try:
            driver = get_driver()
            with driver.session(database=database) as session:
                result = session.run(cypher, parameters=params or {})
                return [record.data() for record in result]
        except (ServiceUnavailable, SessionExpired, ConnectionResetError, OSError) as e:
            print(f"[db] Query retry {attempt+1}/3: {e}")
            _reset_driver()
            time.sleep(1)
    raise RuntimeError("Neo4j query failed after 3 retries")


def run_query_single(cypher: str, params: dict | None = None, db: str | None = None):
    """Execute a Cypher query and return first record (or None)."""
    rows = run_query(cypher, params, db)
    return rows[0] if rows else None


# ── Schema setup ─────────────────────────────────────────────────

CONSTRAINTS = [
    "CREATE CONSTRAINT IF NOT EXISTS FOR (r:RFP)      ON (r.id) IS UNIQUE",
    "CREATE CONSTRAINT IF NOT EXISTS FOR (p:Proposal)  ON (p.id) IS UNIQUE",
    "CREATE CONSTRAINT IF NOT EXISTS FOR (a:Asset)     ON (a.id) IS UNIQUE",
]

PROPERTY_INDEXES = [
    "CREATE INDEX IF NOT EXISTS FOR (r:RFP)      ON (r.sector)",
    "CREATE INDEX IF NOT EXISTS FOR (p:Proposal)  ON (p.sector)",
    "CREATE INDEX IF NOT EXISTS FOR (a:Asset)     ON (a.sector)",
]

VECTOR_INDEXES = [
    {
        "name": "rfp_chunk_embedding",
        "label": "RFPChunk",
        "property": "embedding",
        "dimensions": 1536,
    },
    {
        "name": "proposal_chunk_embedding",
        "label": "ProposalChunk",
        "property": "embedding",
        "dimensions": 1536,
    },
    {
        "name": "asset_chunk_embedding",
        "label": "AssetChunk",
        "property": "embedding",
        "dimensions": 1536,
    },
]


def setup_schema():
    """Create all constraints, indexes, and vector indexes."""
    for c in CONSTRAINTS:
        try:
            run_query(c)
        except Exception as e:
            print(f"[schema] constraint skip: {e}")

    for idx in PROPERTY_INDEXES:
        try:
            run_query(idx)
        except Exception as e:
            print(f"[schema] index skip: {e}")

    for vi in VECTOR_INDEXES:
        cypher = (
            f"CREATE VECTOR INDEX `{vi['name']}` IF NOT EXISTS "
            f"FOR (n:{vi['label']}) ON (n.{vi['property']}) "
            f"OPTIONS {{indexConfig: {{`vector.dimensions`: {vi['dimensions']}, "
            f"`vector.similarity_function`: 'cosine'}}}}"
        )
        try:
            run_query(cypher)
        except Exception as e:
            print(f"[schema] vector index skip: {e}")

    print("[schema] Setup complete")


def close_driver():
    """Cleanly close the driver."""
    global _driver
    if _driver:
        _driver.close()
        _driver = None
