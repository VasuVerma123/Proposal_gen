"""
Standalone test: Extract text from scope.pdf and store it in Neo4j
via the BuildKBAgent as a Proposal node.

Steps:
  1. Extract PDF text with PyPDF2
  2. Connect to Neo4j (verify)
  3. Store as a Proposal node (direct method — reliable)
  4. Verify via LLM-driven LIST_ALL and SEARCH_KB
"""

import os
import sys
import asyncio

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, ".")

from dotenv import load_dotenv
load_dotenv()

from PyPDF2 import PdfReader
from agents.build_kb_agent import BuildKBAgent


PDF_PATH = "scope.pdf"

PROPOSAL_META = {
    "id": "PROP-SCOPE-001",
    "sector": "Telecom",
    "company": "Metafore",
    "sent_to": "XYZ Telecom",
}


def extract_pdf_text(path: str) -> str:
    """Read all pages of a PDF and return combined text."""
    reader = PdfReader(path)
    pages = []
    for page in reader.pages:
        text = page.extract_text()
        if text:
            pages.append(text.strip())
    full_text = "\n\n".join(pages)
    print(f"  Extracted {len(reader.pages)} pages, {len(full_text)} characters")
    return full_text


def separator(title: str):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


async def main():
    # ── Step 1: Extract PDF ──────────────────────────────────────
    separator("Step 1: Extract PDF text")

    if not os.path.exists(PDF_PATH):
        print(f"  [FAIL] File not found: {PDF_PATH}")
        sys.exit(1)

    pdf_text = extract_pdf_text(PDF_PATH)
    preview = pdf_text[:300].replace("\n", " ")
    print(f"  Preview: {preview}...")

    # ── Step 2: Initialize KB Agent & verify Neo4j ───────────────
    separator("Step 2: Connect to Neo4j")

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

    # ── Step 3: Store Proposal directly ──────────────────────────
    separator("Step 3: Store Proposal in Neo4j")

    proposal_data = {**PROPOSAL_META, "text": pdf_text}

    try:
        result_msg = kb._add_proposal(proposal_data)
        print(f"  [OK] {result_msg}")
    except Exception as e:
        print(f"  [FAIL] {e}")
        kb.close()
        sys.exit(1)

    # ── Step 4: Verify — List all KB items ───────────────────────
    separator("Step 4: Verify — List all KB items")

    try:
        list_result = kb._list_all()
        print(f"  {list_result}")
    except Exception as e:
        print(f"  [FAIL] {e}")

    # ── Step 5: Verify — Search by sector ────────────────────────
    separator("Step 5: Search KB for Telecom sector")

    try:
        search_result = kb._search({"sector": "Telecom"})
        print(f"  {search_result}")
    except Exception as e:
        print(f"  [FAIL] {e}")

    # ── Step 6: Verify — Ask agent via LLM conversation ──────────
    separator("Step 6: Ask KB Agent (LLM) to find matches")

    try:
        conversation = [
            {"role": "user", "content": "Find matches for PROP-SCOPE-001"}
        ]
        llm_result = await kb.run(conversation)
        print(f"  Agent says:\n  {llm_result['response']}")
    except Exception as e:
        print(f"  [FAIL] {e}")

    # ── Done ─────────────────────────────────────────────────────
    separator("All steps complete")
    kb.close()
    print("  Neo4j connection closed. Test finished!\n")


if __name__ == "__main__":
    asyncio.run(main())
