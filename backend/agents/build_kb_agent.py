"""
BuildKBAgent  --  manages the Neo4j knowledge-base for proposals, RFPs, and assets.

Provides:
  - _add_proposal(data)   : ingest a Proposal node + chunks + embeddings + auto-link
  - _add_rfp(data)         : ingest an RFP node (same pipeline)
  - _add_asset(data)       : ingest an Asset node
  - _list_all()            : return a human-readable listing of every KB item
  - search_similar(text, top_k) : vector-similarity search across all chunk types
  - verify_connection()    : True if Neo4j is reachable
  - close()                : cleanly shut down the driver
"""

import os
import uuid
import datetime as _dt

from neo4j import GraphDatabase
from neo4j.exceptions import ServiceUnavailable

from embeddings import get_embedding, get_embeddings
from chunker import chunk_text


class BuildKBAgent:
    """High-level wrapper around Neo4j for the proposal knowledge-base."""

    # ── Construction / connection ────────────────────────────────

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY", "")
        self.uri = os.getenv("NEO4J_URI", "")
        self.user = os.getenv("NEO4J_USERNAME", "neo4j")
        self.pwd = os.getenv("NEO4J_PASSWORD", "")
        self.db = os.getenv("NEO4J_DATABASE", "neo4j")

        # try neo4j+s first, then neo4j+ssc for SSL issues
        self.driver = None
        for scheme in [self.uri, self.uri.replace("neo4j+s://", "neo4j+ssc://")]:
            try:
                d = GraphDatabase.driver(scheme, auth=(self.user, self.pwd))
                d.verify_connectivity()
                self.driver = d
                print(f"[BuildKBAgent] Connected via {scheme}")
                break
            except Exception as e:
                print(f"[BuildKBAgent] {scheme} failed: {e}")

        if self.driver is None:
            raise RuntimeError("BuildKBAgent cannot connect to Neo4j")

        self._ensure_schema()

    # ── Schema bootstrap ─────────────────────────────────────────

    def _ensure_schema(self):
        stmts = [
            "CREATE CONSTRAINT IF NOT EXISTS FOR (p:Proposal) ON (p.id) IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (r:RFP)      ON (r.id) IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (a:Asset)     ON (a.id) IS UNIQUE",
            "CREATE INDEX IF NOT EXISTS FOR (p:Proposal)  ON (p.sector)",
            "CREATE INDEX IF NOT EXISTS FOR (r:RFP)       ON (r.sector)",
            "CREATE INDEX IF NOT EXISTS FOR (a:Asset)      ON (a.sector)",
        ]
        vector_stmts = [
            (
                "CREATE VECTOR INDEX proposal_chunk_embedding IF NOT EXISTS "
                "FOR (n:ProposalChunk) ON (n.embedding) "
                "OPTIONS {indexConfig: {`vector.dimensions`: 1536, "
                "`vector.similarity_function`: 'cosine'}}"
            ),
            (
                "CREATE VECTOR INDEX rfp_chunk_embedding IF NOT EXISTS "
                "FOR (n:RFPChunk) ON (n.embedding) "
                "OPTIONS {indexConfig: {`vector.dimensions`: 1536, "
                "`vector.similarity_function`: 'cosine'}}"
            ),
            (
                "CREATE VECTOR INDEX asset_chunk_embedding IF NOT EXISTS "
                "FOR (n:AssetChunk) ON (n.embedding) "
                "OPTIONS {indexConfig: {`vector.dimensions`: 1536, "
                "`vector.similarity_function`: 'cosine'}}"
            ),
        ]
        with self.driver.session(database=self.db) as s:
            for st in stmts + vector_stmts:
                try:
                    s.run(st)
                except Exception as e:
                    print(f"[schema] skip: {e}")

    # ── Helpers ──────────────────────────────────────────────────

    @staticmethod
    def _gen_id() -> str:
        return uuid.uuid4().hex[:12]

    @staticmethod
    def _now() -> str:
        return _dt.datetime.utcnow().isoformat()

    def _run(self, cypher, **params):
        with self.driver.session(database=self.db) as s:
            return s.run(cypher, **params).data()

    # ── Ingestion pipeline ───────────────────────────────────────

    def _ingest(self, label: str, chunk_label: str, data: dict) -> str:
        """
        Generic ingest:
          1. Merge parent node
          2. Chunk text
          3. Embed chunks
          4. Store chunk nodes + HAS_CHUNK edges
          5. Vector-similarity cross-link (SIMILAR_TO)
          6. Roll up parent edges (MATCHED_TO)
        """
        node_id = data.get("id") or f"{label.upper()}-{self._gen_id()}"
        now = self._now()

        # 1 ── parent node
        props = {k: v for k, v in data.items() if k != "text"}
        props["id"] = node_id
        props["created_at"] = now
        set_clause = ", ".join(f"n.{k} = ${k}" for k in props)
        self._run(
            f"MERGE (n:{label} {{id: $id}}) SET {set_clause}",
            **props,
        )

        # 2 ── chunk
        text = data.get("text", "")
        if not text:
            return f"{label} {node_id} saved (no text to chunk)"

        chunks = chunk_text(text)
        if not chunks:
            return f"{label} {node_id} saved (empty chunks)"

        # 3 ── embed
        vectors = get_embeddings(chunks, self.api_key)

        # 4 ── store chunks
        for idx, (chunk, vec) in enumerate(zip(chunks, vectors)):
            cid = f"{node_id}-chunk-{idx}"
            self._run(
                f"MERGE (c:{chunk_label} {{id: $cid}}) "
                f"SET c.text = $text, c.embedding = $vec, c.seq = $seq "
                f"WITH c "
                f"MATCH (p:{label} {{id: $pid}}) "
                f"MERGE (p)-[:HAS_CHUNK]->(c)",
                cid=cid, text=chunk, vec=vec, seq=idx, pid=node_id,
            )

        # 5 ── cross-link via vector similarity
        self._cross_link(chunk_label, node_id)

        # 6 ── roll up parent edges
        self._rollup(label, chunk_label, node_id)

        return f"{label} {node_id} ingested ({len(chunks)} chunks)"

    def _cross_link(self, chunk_label: str, parent_id: str):
        """Create SIMILAR_TO edges between this node's chunks and existing similar chunks."""
        # Find all vector indexes we can query
        index_map = {
            "ProposalChunk": "proposal_chunk_embedding",
            "RFPChunk": "rfp_chunk_embedding",
            "AssetChunk": "asset_chunk_embedding",
        }
        for target_label, idx_name in index_map.items():
            try:
                self._run(
                    f"""
                    MATCH (src:{chunk_label})<-[:HAS_CHUNK]-({{id: $pid}})
                    WITH src
                    CALL db.index.vector.queryNodes($idx, 3, src.embedding)
                    YIELD node AS tgt, score
                    WHERE tgt <> src AND score > 0.78
                    MERGE (src)-[r:SIMILAR_TO]-(tgt)
                    SET r.score = score
                    """,
                    pid=parent_id, idx=idx_name,
                )
            except Exception as e:
                # index may not exist yet — skip silently
                if "index" not in str(e).lower():
                    print(f"[cross-link] {e}")

    def _rollup(self, label: str, chunk_label: str, parent_id: str):
        """Aggregate chunk-level SIMILAR_TO into parent-level MATCHED_TO edges."""
        try:
            self._run(
                f"""
                MATCH (p:{label} {{id: $pid}})-[:HAS_CHUNK]->(c:{chunk_label})
                      -[:SIMILAR_TO]-(t)
                      <-[:HAS_CHUNK]-(other)
                WHERE other <> p
                WITH p, other, avg(1) AS strength
                MERGE (p)-[r:MATCHED_TO]-(other)
                SET r.strength = strength
                """,
                pid=parent_id,
            )
        except Exception as e:
            print(f"[rollup] {e}")

    # ── Public ingest helpers ────────────────────────────────────

    def _add_proposal(self, data: dict) -> str:
        return self._ingest("Proposal", "ProposalChunk", data)

    def _add_rfp(self, data: dict) -> str:
        return self._ingest("RFP", "RFPChunk", data)

    def _add_asset(self, data: dict) -> str:
        return self._ingest("Asset", "AssetChunk", data)

    # ── Search ───────────────────────────────────────────────────

    def search_similar(self, query_text: str, top_k: int = 5) -> list[dict]:
        """Vector-search across all chunk types and return parent info."""
        vec = get_embedding(query_text, self.api_key)
        results = []

        index_map = {
            "proposal_chunk_embedding": ("ProposalChunk", "Proposal"),
            "rfp_chunk_embedding": ("RFPChunk", "RFP"),
            "asset_chunk_embedding": ("AssetChunk", "Asset"),
        }

        for idx_name, (chunk_lbl, parent_lbl) in index_map.items():
            try:
                rows = self._run(
                    f"""
                    CALL db.index.vector.queryNodes($idx, $k, $vec)
                    YIELD node AS chunk, score
                    MATCH (parent:{parent_lbl})-[:HAS_CHUNK]->(chunk)
                    RETURN parent {{ .*, _label: '{parent_lbl}' }} AS parent,
                           chunk.text AS chunk_text,
                           score
                    ORDER BY score DESC
                    """,
                    idx=idx_name, k=top_k, vec=vec,
                )
                results.extend(rows)
            except Exception:
                pass  # index might not exist

        # deduplicate & sort
        results.sort(key=lambda r: r.get("score", 0), reverse=True)
        return results[:top_k]

    # ── Listing ──────────────────────────────────────────────────

    def _list_all(self) -> str:
        """Return a human-readable listing of all KB items."""
        lines = []
        for label in ["Proposal", "RFP", "Asset"]:
            rows = self._run(
                f"MATCH (n:{label}) "
                f"OPTIONAL MATCH (n)-[:HAS_CHUNK]->(c) "
                f"RETURN n.id AS id, n.sector AS sector, n.company AS company, "
                f"       n.sent_to AS sent_to, count(c) AS chunks "
                f"ORDER BY n.id"
            )
            lines.append(f"\n--- {label}s ({len(rows)}) ---")
            for r in rows:
                parts = [f"  {r['id']}"]
                if r.get("sector"):
                    parts.append(f"sector={r['sector']}")
                if r.get("company"):
                    parts.append(f"company={r['company']}")
                if r.get("sent_to"):
                    parts.append(f"sent_to={r['sent_to']}")
                parts.append(f"chunks={r['chunks']}")
                lines.append("  |  ".join(parts))
        return "\n".join(lines)

    # ── Lifecycle ────────────────────────────────────────────────

    def verify_connection(self) -> bool:
        try:
            self.driver.verify_connectivity()
            return True
        except Exception:
            return False

    def close(self):
        if self.driver:
            self.driver.close()
            self.driver = None
