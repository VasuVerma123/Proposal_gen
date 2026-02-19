"""
Four tools exposed to the OpenAI function-calling agent:

  1. retrieve_info   - search KB for similar proposals / matched requirements
  2. analyze_rfp     - break RFP into requirements & search KB per-requirement
  3. update_info     - save the confirmed proposal back into the KB
  4. proposal_engine - gather all info and build the proposal HTML preview
"""

import os
import json
import base64
from openai import OpenAI
from agents.build_kb_agent import BuildKBAgent
from pdf_builder import build_proposal_html, sections_from_markdown

# ── Lazy singleton for the KB agent ─────────────────────────────

_kb: BuildKBAgent | None = None


def _get_kb() -> BuildKBAgent:
    global _kb
    if _kb is None:
        _kb = BuildKBAgent(api_key=os.getenv("OPENAI_API_KEY", ""))
    return _kb


# ── Tool definitions (OpenAI function-calling schema) ────────────

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "retrieve_info",
            "description": (
                "Search the knowledge base for proposals, RFPs, and assets "
                "that are similar to the user's requirements. Returns matched "
                "proposals and relevant content from the knowledge base."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query describing what the user needs (e.g. sector, industry, requirements).",
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "Number of results to return (default 5).",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "analyze_rfp",
            "description": (
                "Analyze an RFP (Request for Proposal) by breaking it into individual "
                "requirements and searching the knowledge base for each one. Returns a "
                "detailed breakdown of which requirements have matching proposals/templates "
                "in our KB and which ones are new. Use this when the user provides RFP text, "
                "requirements, or describes what their proposal should cover."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "rfp_text": {
                        "type": "string",
                        "description": (
                            "The full RFP text or requirements description provided by the user. "
                            "This can be the raw RFP content, a list of requirements, or a "
                            "description of what the proposal should address."
                        ),
                    },
                    "sector": {
                        "type": "string",
                        "description": "Industry sector (e.g. Telecom, Banking, Insurance).",
                    },
                },
                "required": ["rfp_text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_info",
            "description": (
                "Save the final confirmed proposal into the knowledge base "
                "so it can be reused as a template for future proposals."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "proposal_id": {
                        "type": "string",
                        "description": "Unique ID for the proposal.",
                    },
                    "sector": {
                        "type": "string",
                        "description": "Industry sector of the proposal.",
                    },
                    "company": {
                        "type": "string",
                        "description": "Company that created the proposal.",
                    },
                    "sent_to": {
                        "type": "string",
                        "description": "Client the proposal is for.",
                    },
                    "text": {
                        "type": "string",
                        "description": "Full text content of the proposal.",
                    },
                },
                "required": ["sector", "company", "sent_to", "text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "proposal_engine",
            "description": (
                "Generate a professional proposal preview. Takes company info, "
                "client info, sector, RFP requirements, and optionally a template "
                "from the knowledge base, and produces styled proposal HTML."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "company_name": {
                        "type": "string",
                        "description": "Name of the proposing company.",
                    },
                    "client_name": {
                        "type": "string",
                        "description": "Name of the client / RFP issuer.",
                    },
                    "sector": {
                        "type": "string",
                        "description": "Industry sector.",
                    },
                    "proposal_markdown": {
                        "type": "string",
                        "description": (
                            "The full proposal content in Markdown format with "
                            "## headings for each section. Sections like Executive Summary, "
                            "Scope of Work, Approach, Timeline, Pricing, etc."
                        ),
                    },
                },
                "required": ["company_name", "client_name", "sector", "proposal_markdown"],
            },
        },
    },
]


# ── Tool implementations ─────────────────────────────────────────

def retrieve_info(query: str, top_k: int = 5) -> str:
    """Search KB for similar proposals and matched requirements."""
    kb = _get_kb()
    results = kb.search_similar(query, top_k=top_k)

    if not results:
        return json.dumps({
            "found": 0,
            "message": "No matching proposals or templates found in the knowledge base.",
            "results": [],
        })

    formatted = []
    for r in results:
        parent = r.get("parent", {})
        formatted.append({
            "type": parent.get("_label", "Unknown"),
            "id": parent.get("id", ""),
            "sector": parent.get("sector", ""),
            "company": parent.get("company", ""),
            "sent_to": parent.get("sent_to", ""),
            "score": round(r.get("score", 0), 4),
            "matched_text": (r.get("chunk_text", ""))[:500],
        })

    return json.dumps({
        "found": len(formatted),
        "message": f"Found {len(formatted)} matching item(s) in the knowledge base.",
        "results": formatted,
    })


def analyze_rfp(rfp_text: str, sector: str | None = None) -> str:
    """
    Break an RFP into individual requirements and search the KG for each one.

    Pipeline:
      1. GPT parses the RFP text into distinct, atomic requirements.
      2. Each requirement is embedded and vector-searched against all KG chunks
         (ProposalChunk, RFPChunk, AssetChunk).
      3. Results are structured per-requirement with matched KB items + scores.
    """
    api_key = os.getenv("OPENAI_API_KEY", "")
    client = OpenAI(api_key=api_key)
    kb = _get_kb()

    # ── Step 1: Parse RFP into requirements using GPT ─────────────
    parse_prompt = (
        "You are an RFP analyst. Extract every distinct requirement from the "
        "following RFP or requirements description. Return valid JSON with a "
        "single key \"requirements\" containing an array of objects. Each object "
        "must have:\n"
        "  - \"id\": string like \"R1\", \"R2\", etc.\n"
        "  - \"title\": short 5-10 word title\n"
        "  - \"description\": 1-2 sentence detailed description\n"
        "  - \"category\": one of [\"functional\", \"technical\", \"operational\", "
        "\"compliance\", \"commercial\", \"support\"]\n\n"
        "Be thorough. Extract EVERY requirement, even implicit ones. "
        "If the text mentions a sector or industry, extract domain-specific "
        "requirements too."
    )

    try:
        parse_response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": parse_prompt},
                {"role": "user", "content": rfp_text},
            ],
            response_format={"type": "json_object"},
            temperature=0.2,
        )
        parsed = json.loads(parse_response.choices[0].message.content)
        requirements = parsed.get("requirements", [])
    except Exception as e:
        return json.dumps({"error": f"Failed to parse RFP: {e}"})

    if not requirements:
        return json.dumps({
            "error": "Could not extract any requirements from the provided text.",
            "total_requirements": 0,
        })

    # ── Step 2: Search KG for each requirement ────────────────────
    results = []
    for req in requirements:
        search_query = f"{req.get('title', '')}: {req.get('description', '')}"
        if sector:
            search_query = f"[{sector}] {search_query}"

        try:
            matches = kb.search_similar(search_query, top_k=3)
        except Exception:
            matches = []

        formatted_matches = []
        for m in matches:
            parent = m.get("parent", {})
            score = round(m.get("score", 0), 4)
            # Only include matches with a meaningful similarity score
            if score >= 0.65:
                formatted_matches.append({
                    "type": parent.get("_label", "Unknown"),
                    "id": parent.get("id", ""),
                    "sector": parent.get("sector", ""),
                    "company": parent.get("company", ""),
                    "score": score,
                    "matched_text": (m.get("chunk_text", ""))[:400],
                })

        coverage = "full" if formatted_matches else "none"
        if formatted_matches:
            best_score = max(m["score"] for m in formatted_matches)
            if best_score >= 0.85:
                coverage = "strong"
            elif best_score >= 0.75:
                coverage = "partial"
            else:
                coverage = "weak"

        results.append({
            "requirement_id": req.get("id", ""),
            "title": req.get("title", ""),
            "description": req.get("description", ""),
            "category": req.get("category", ""),
            "coverage": coverage,
            "kb_matches": formatted_matches,
        })

    # ── Step 3: Summary ───────────────────────────────────────────
    total = len(results)
    strong = sum(1 for r in results if r["coverage"] == "strong")
    partial = sum(1 for r in results if r["coverage"] == "partial")
    weak = sum(1 for r in results if r["coverage"] == "weak")
    none_ = sum(1 for r in results if r["coverage"] == "none")

    summary = {
        "total_requirements": total,
        "coverage_summary": {
            "strong_match": strong,
            "partial_match": partial,
            "weak_match": weak,
            "no_match": none_,
        },
        "coverage_pct": round((strong + partial) / total * 100, 1) if total else 0,
        "requirements": results,
        "recommendation": (
            f"Found {strong + partial} of {total} requirements with KB coverage. "
            + (f"{none_} requirement(s) will need fresh content." if none_ else "All requirements have some KB coverage!")
        ),
    }

    return json.dumps(summary)


def update_info(
    sector: str,
    company: str,
    sent_to: str,
    text: str,
    proposal_id: str | None = None,
) -> str:
    """Save confirmed proposal back to KB."""
    kb = _get_kb()
    data = {
        "sector": sector,
        "company": company,
        "sent_to": sent_to,
        "text": text,
    }
    if proposal_id:
        data["id"] = proposal_id

    result = kb._add_proposal(data)
    return json.dumps({"status": "saved", "detail": result})


def proposal_engine(
    company_name: str,
    client_name: str,
    sector: str,
    proposal_markdown: str,
) -> str:
    """Build styled proposal HTML from markdown content."""
    sections = sections_from_markdown(proposal_markdown)
    html = build_proposal_html(
        company_name=company_name,
        client_name=client_name,
        sector=sector,
        sections=sections,
        logo_data_uri=None,
    )
    return json.dumps({
        "status": "preview_ready",
        "html": html,
        "markdown": proposal_markdown,
        "sections_count": len(sections),
    })


# ── Dispatcher (called by the agent loop) ────────────────────────

TOOL_MAP = {
    "retrieve_info": retrieve_info,
    "analyze_rfp": analyze_rfp,
    "update_info": update_info,
    "proposal_engine": proposal_engine,
}


def execute_tool(name: str, arguments: dict) -> str:
    """Execute a tool by name with the given arguments."""
    fn = TOOL_MAP.get(name)
    if fn is None:
        return json.dumps({"error": f"Unknown tool: {name}"})
    try:
        return fn(**arguments)
    except Exception as e:
        return json.dumps({"error": str(e)})
