"""
Three tools exposed to the OpenAI function-calling agent:

  1. retrieve_info   - search KB for similar proposals / matched requirements
  2. update_info     - save the confirmed proposal back into the KB
  3. proposal_engine - gather all info and build the proposal HTML preview
"""

import os
import json
import base64
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
