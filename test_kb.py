"""
Upload all PDFs from the Files/ folder into Neo4j as Proposal nodes
using the BuildKBAgent, with embeddings and auto-linking.
"""

import os
import sys
import math
import time

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, ".")

from dotenv import load_dotenv
load_dotenv()

from PyPDF2 import PdfReader
from agents.build_kb_agent import BuildKBAgent

FILES_DIR = "Files"

MAX_TEXT_CHARS = 6000

PROPOSALS = [
    {
        "file": "MF_Proposal_Aviation.pdf",
        "id": "PROP-AVIATION-001",
        "sector": "Aviation",
        "company": "Metafore",
        "sent_to": "SkyBridge Airways",
    },
    {
        "file": "MF_Proposal_Banking.pdf",
        "id": "PROP-BANKING-001",
        "sector": "Banking",
        "company": "Metafore",
        "sent_to": "Apex Financial Group",
    },
    {
        "file": "MF_Proposal_Insurance.pdf",
        "id": "PROP-INSURANCE-001",
        "sector": "Insurance",
        "company": "Metafore",
        "sent_to": "ShieldLife Insurance Co.",
    },
    {
        "file": "MF_Proposal_Pharma.pdf",
        "id": "PROP-PHARMA-001",
        "sector": "Pharmaceutical",
        "company": "Metafore",
        "sent_to": "NovaCure Therapeutics",
    },
    {
        "file": "MF_Proposal_Retail_and_E-Commerce.pdf",
        "id": "PROP-RETAIL-001",
        "sector": "Retail & E-Commerce",
        "company": "Metafore",
        "sent_to": "Zenith Retail Group",
    },
    {
        "file": "MF_Proposal_Telecom.pdf",
        "id": "PROP-TELECOM-001",
        "sector": "Telecom",
        "company": "Metafore",
        "sent_to": "GlobalNet Communications",
    },
]


def extract_pdf_text(path: str) -> str:
    """Read all pages of a PDF and return combined text, truncated for embeddings."""
    reader = PdfReader(path)
    pages = []
    for page in reader.pages:
        text = page.extract_text()
        if text:
            pages.append(text.strip())
    full_text = "\n\n".join(pages)
    truncated = full_text[:MAX_TEXT_CHARS]
    print(f"    Pages: {len(reader.pages)}, Chars: {len(full_text)} -> {len(truncated)} (used for embedding)")
    return truncated


def separator(title: str):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


def main():
    # ── Step 1: Initialize KB Agent & verify Neo4j ───────────────
    separator("Step 1: Connect to Neo4j")

    api_key = os.getenv("OPENAI_API_KEY", "")
    if not api_key:
        print("  [FAIL] OPENAI_API_KEY not set in .env")
        sys.exit(1)

    kb = BuildKBAgent(api_key=api_key)

    if not kb.verify_connection():
        print("  [FAIL] Cannot connect to Neo4j. Check .env credentials.")
        kb.close()
        sys.exit(1)
    print("  [OK] Neo4j connected")

    # ── Step 2: Upload each PDF as a Proposal ────────────────────
    separator(f"Step 2: Upload {len(PROPOSALS)} PDFs as Proposals")

    success_count = 0
    fail_count = 0

    for i, prop in enumerate(PROPOSALS, 1):
        pdf_path = os.path.join(FILES_DIR, prop["file"])
        print(f"\n  [{i}/{len(PROPOSALS)}] {prop['file']}")
        print(f"    ID: {prop['id']}  |  Sector: {prop['sector']}  |  Sent to: {prop['sent_to']}")

        if not os.path.exists(pdf_path):
            print(f"    [SKIP] File not found: {pdf_path}")
            fail_count += 1
            continue

        try:
            pdf_text = extract_pdf_text(pdf_path)

            proposal_data = {
                "id": prop["id"],
                "sector": prop["sector"],
                "company": prop["company"],
                "sent_to": prop["sent_to"],
                "text": pdf_text,
            }

            start = time.time()
            result_msg = kb._add_proposal(proposal_data)
            elapsed = time.time() - start

            print(f"    [OK] {result_msg}  ({elapsed:.1f}s)")
            success_count += 1

        except Exception as e:
            print(f"    [FAIL] {e}")
            fail_count += 1

    # ── Step 3: Verify — List all KB items ───────────────────────
    separator("Step 3: Verify — List all KB items")

    try:
        list_result = kb._list_all()
        for line in list_result.split("\n"):
            print(f"  {line}")
    except Exception as e:
        print(f"  [FAIL] {e}")

    # ── Step 4: Check similarity links ───────────────────────────
    separator("Step 4: Check auto-linked relationships")

    try:
        with kb.driver.session(database=kb.db) as s:
            similar = s.run(
                "MATCH (a:Proposal)-[r:MATCHED_TO]-(b) "
                "RETURN a.id AS from_id, type(r) AS rel, b.id AS to_id"
            ).data()

            if similar:
                print(f"  Found {len(similar)} relationship(s):")
                for r in similar:
                    print(f"    {r['from_id']} --[{r['rel']}]--> {r['to_id']}")
            else:
                print("  No MATCHED_TO relationships yet (add RFPs to trigger cross-matching).")

            similar_to = s.run(
                "MATCH (a)-[r:SIMILAR_TO]-(b) "
                "RETURN a.id AS from_id, type(r) AS rel, b.id AS to_id"
            ).data()

            if similar_to:
                print(f"\n  Found {len(similar_to)} SIMILAR_TO relationship(s):")
                for r in similar_to:
                    print(f"    {r['from_id']} --[{r['rel']}]--> {r['to_id']}")

    except Exception as e:
        print(f"  [FAIL] {e}")

    # ── Summary ──────────────────────────────────────────────────
    separator("Summary")
    print(f"  Uploaded: {success_count}/{len(PROPOSALS)}")
    print(f"  Failed:   {fail_count}/{len(PROPOSALS)}")

    kb.close()
    print(f"\n  Neo4j connection closed. Done!\n")


if __name__ == "__main__":
    main()
