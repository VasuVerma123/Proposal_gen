"""
Check all nodes, relationships, and similarity scores in the Neo4j knowledge base.
"""

import os
import sys
import math

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, ".")

from dotenv import load_dotenv
load_dotenv()

from neo4j import GraphDatabase

EMBED_MODEL = "text-embedding-3-small"


def cosine(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    return dot / (na * nb) if na and nb else 0.0


def separator(title):
    print(f"\n{'='*70}")
    print(f"  {title}")
    print(f"{'='*70}")


def main():
    uri = os.getenv("NEO4J_URI", "").replace("neo4j+s://", "neo4j+ssc://")
    driver = GraphDatabase.driver(
        uri,
        auth=(os.getenv("NEO4J_USERNAME", "neo4j"), os.getenv("NEO4J_PASSWORD", "")),
    )
    db = os.getenv("NEO4J_DATABASE", "neo4j")

    driver.verify_connectivity()
    print("[OK] Connected to Neo4j")

    with driver.session(database=db) as s:

        # ── 1. All Nodes ─────────────────────────────────────────
        separator("1. All Nodes in Knowledge Base")

        rfps = s.run(
            "MATCH (r:RFP) "
            "RETURN r.id AS id, r.sector AS sector, r.company AS company, "
            "       r.source AS source, r.text IS NOT NULL AS has_text, "
            "       r.embedding IS NOT NULL AS has_emb"
        ).data()

        proposals = s.run(
            "MATCH (p:Proposal) "
            "RETURN p.id AS id, p.sector AS sector, p.company AS company, "
            "       p.sent_to AS sent_to, p.text IS NOT NULL AS has_text, "
            "       p.embedding IS NOT NULL AS has_emb"
        ).data()

        if rfps:
            print(f"\n  RFPs ({len(rfps)}):")
            print(f"  {'ID':<25} {'Sector':<22} {'Company':<18} {'Source':<18} {'Emb'}")
            print(f"  {'-'*25} {'-'*22} {'-'*18} {'-'*18} {'-'*5}")
            for r in rfps:
                print(f"  {r['id']:<25} {r['sector'] or '':<22} {r['company'] or '':<18} {r['source'] or '':<18} {'yes' if r['has_emb'] else 'no'}")
        else:
            print("\n  RFPs: (none)")

        if proposals:
            print(f"\n  Proposals ({len(proposals)}):")
            print(f"  {'ID':<25} {'Sector':<22} {'Company':<18} {'Sent To':<22} {'Emb'}")
            print(f"  {'-'*25} {'-'*22} {'-'*18} {'-'*22} {'-'*5}")
            for p in proposals:
                print(f"  {p['id']:<25} {p['sector'] or '':<22} {p['company'] or '':<18} {p['sent_to'] or '':<22} {'yes' if p['has_emb'] else 'no'}")
        else:
            print("\n  Proposals: (none)")

        # ── 2. Existing Relationships ────────────────────────────
        separator("2. Existing Relationships")

        rels = s.run(
            "MATCH (a)-[r]->(b) "
            "RETURN labels(a)[0] AS from_label, a.id AS from_id, "
            "       type(r) AS rel_type, "
            "       labels(b)[0] AS to_label, b.id AS to_id"
        ).data()

        if rels:
            print(f"\n  Found {len(rels)} relationship(s):\n")
            print(f"  {'From':<30} {'Rel':<15} {'To'}")
            print(f"  {'-'*30} {'-'*15} {'-'*30}")
            for r in rels:
                from_str = f"{r['from_label']}:{r['from_id']}"
                to_str = f"{r['to_label']}:{r['to_id']}"
                print(f"  {from_str:<30} {r['rel_type']:<15} {to_str}")
        else:
            print("\n  No relationships found.")

        # ── 3. Cosine Similarity Matrix (Proposals) ──────────────
        separator("3. Cosine Similarity Between All Proposals")

        emb_data = s.run(
            "MATCH (p:Proposal) WHERE p.embedding IS NOT NULL "
            "RETURN p.id AS id, p.embedding AS emb ORDER BY p.id"
        ).data()

        if len(emb_data) >= 2:
            ids = [e["id"] for e in emb_data]
            embs = [e["emb"] for e in emb_data]

            max_id_len = max(len(i) for i in ids)
            header = " " * (max_id_len + 4) + "  ".join(f"{i[:12]:>12}" for i in ids)
            print(f"\n{header}")

            for i, id_a in enumerate(ids):
                row = f"  {id_a:<{max_id_len}}  "
                for j, id_b in enumerate(ids):
                    sim = cosine(embs[i], embs[j])
                    if i == j:
                        row += f"{'  ---':>14}"
                    elif sim >= 0.70:
                        row += f"  {sim:>10.4f} *"
                    else:
                        row += f"  {sim:>10.4f}  "
                print(row)

            print(f"\n  * = above similarity threshold (0.70)")
        else:
            print("\n  Need at least 2 proposals with embeddings to compute similarity.")

        # ── 4. Cosine Similarity: RFPs vs Proposals ──────────────
        separator("4. Cosine Similarity: RFPs vs Proposals")

        rfp_embs = s.run(
            "MATCH (r:RFP) WHERE r.embedding IS NOT NULL "
            "RETURN r.id AS id, r.embedding AS emb ORDER BY r.id"
        ).data()

        prop_embs = s.run(
            "MATCH (p:Proposal) WHERE p.embedding IS NOT NULL "
            "RETURN p.id AS id, p.embedding AS emb ORDER BY p.id"
        ).data()

        if rfp_embs and prop_embs:
            prop_ids = [e["id"] for e in prop_embs]
            max_id_len = max(len(i) for i in [e["id"] for e in rfp_embs])
            header = " " * (max_id_len + 4) + "  ".join(f"{i[:12]:>12}" for i in prop_ids)
            print(f"\n  RFP \\ Proposal")
            print(f"{header}")

            for rfp in rfp_embs:
                row = f"  {rfp['id']:<{max_id_len}}  "
                for prop in prop_embs:
                    sim = cosine(rfp["emb"], prop["emb"])
                    if sim >= 0.70:
                        row += f"  {sim:>10.4f} *"
                    else:
                        row += f"  {sim:>10.4f}  "
                print(row)

            print(f"\n  * = above similarity threshold (0.70)")
        else:
            print("\n  No RFP-Proposal pairs with embeddings to compare.")
            if not rfp_embs:
                print("  (No RFP nodes found — add RFPs to enable cross-matching)")

        # ── 5. Node & Relationship Counts ────────────────────────
        separator("5. Summary Counts")

        counts = s.run(
            "MATCH (n) RETURN labels(n)[0] AS label, count(n) AS cnt"
        ).data()

        rel_counts = s.run(
            "MATCH ()-[r]->() RETURN type(r) AS rel, count(r) AS cnt"
        ).data()

        print(f"\n  Node counts:")
        for c in counts:
            print(f"    {c['label']}: {c['cnt']}")

        if rel_counts:
            print(f"\n  Relationship counts:")
            for r in rel_counts:
                print(f"    {r['rel']}: {r['cnt']}")
        else:
            print(f"\n  Relationship counts: (none)")

    driver.close()
    print(f"\n  Done!\n")


if __name__ == "__main__":
    main()
