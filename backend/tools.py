"""
Five tools exposed to the OpenAI function-calling agent:

  1. retrieve_info    – search KB for similar proposals / matched requirements
  2. analyze_rfp      – break RFP into requirements & search KB per-requirement
  3. proposal_engine  – generate full proposal (all sections) from markdown
  4. edit_section     – surgically update a single section by ID
  5. update_info      – save the confirmed proposal back into the KB
"""

import os
import json
from openai import OpenAI
from agents.build_kb_agent import BuildKBAgent
from proposal_template import parse_markdown_to_sections

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
                        "description": "The search query describing what the user needs.",
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
                "Analyze an RFP by breaking it into individual requirements and "
                "searching the knowledge base for each one. Returns a detailed "
                "breakdown of which requirements have matching proposals/templates."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "rfp_text": {
                        "type": "string",
                        "description": "The full RFP text or requirements description.",
                    },
                    "sector": {
                        "type": "string",
                        "description": "Industry sector (e.g. Telecom, Banking).",
                    },
                },
                "required": ["rfp_text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "proposal_engine",
            "description": (
                "Generate the FULL proposal content for ALL sections. Write the "
                "proposal_markdown using section headings that match the template "
                "IDs, e.g.:\n"
                "  # 0. Cover & Administrative Information\n"
                "  ## 0.1 Cover Page\n"
                "  (content)\n"
                "  # 1. Executive Summary\n"
                "  ## 1.1 Client Context\n"
                "  (content)\n"
                "Use this tool to generate the initial proposal or regenerate "
                "all sections at once."
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
                            "The FULL proposal in Markdown. Use headings with "
                            "section numbers: # 0. Title, ## 0.1 SubTitle, "
                            "### 2.2.1 SubSubTitle. Write content for every "
                            "major section (0 through 7)."
                        ),
                    },
                },
                "required": ["company_name", "client_name", "sector", "proposal_markdown"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_section",
            "description": (
                "Edit a SINGLE section of the proposal by its ID. Use this when "
                "the user asks to rewrite, expand, condense, or change a specific "
                "section (e.g. 'edit section 2.4.3', 'rewrite 1.1', 'expand 5.3')."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "section_id": {
                        "type": "string",
                        "description": "The section ID to edit (e.g. '1.1', '2.4.3', '5.3').",
                    },
                    "content": {
                        "type": "string",
                        "description": "The new markdown content for this section.",
                    },
                },
                "required": ["section_id", "content"],
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
    """Break an RFP into individual requirements and search the KG for each."""
    api_key = os.getenv("OPENAI_API_KEY", "")
    client = OpenAI(api_key=api_key)
    kb = _get_kb()

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
        "Be thorough. Extract EVERY requirement, even implicit ones."
    )

    try:
        resp = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": parse_prompt},
                {"role": "user", "content": rfp_text},
            ],
            response_format={"type": "json_object"},
            temperature=0.2,
        )
        parsed = json.loads(resp.choices[0].message.content)
        requirements = parsed.get("requirements", [])
    except Exception as e:
        return json.dumps({"error": f"Failed to parse RFP: {e}"})

    if not requirements:
        return json.dumps({"error": "Could not extract any requirements.", "total_requirements": 0})

    results = []
    for req in requirements:
        search_q = f"{req.get('title', '')}: {req.get('description', '')}"
        if sector:
            search_q = f"[{sector}] {search_q}"

        try:
            matches = kb.search_similar(search_q, top_k=3)
        except Exception:
            matches = []

        fmt = []
        for m in matches:
            parent = m.get("parent", {})
            score = round(m.get("score", 0), 4)
            if score >= 0.65:
                fmt.append({
                    "type": parent.get("_label", "Unknown"),
                    "id": parent.get("id", ""),
                    "sector": parent.get("sector", ""),
                    "score": score,
                    "matched_text": (m.get("chunk_text", ""))[:400],
                })

        coverage = "none"
        if fmt:
            best = max(m["score"] for m in fmt)
            coverage = "strong" if best >= 0.85 else "partial" if best >= 0.75 else "weak"

        results.append({
            "requirement_id": req.get("id", ""),
            "title": req.get("title", ""),
            "description": req.get("description", ""),
            "category": req.get("category", ""),
            "coverage": coverage,
            "kb_matches": fmt,
        })

    total = len(results)
    strong = sum(1 for r in results if r["coverage"] == "strong")
    partial = sum(1 for r in results if r["coverage"] == "partial")
    weak = sum(1 for r in results if r["coverage"] == "weak")
    none_ = sum(1 for r in results if r["coverage"] == "none")

    return json.dumps({
        "total_requirements": total,
        "coverage_summary": {"strong_match": strong, "partial_match": partial, "weak_match": weak, "no_match": none_},
        "coverage_pct": round((strong + partial) / total * 100, 1) if total else 0,
        "requirements": results,
        "recommendation": (
            f"Found {strong + partial} of {total} requirements with KB coverage. "
            + (f"{none_} requirement(s) will need fresh content." if none_ else "All requirements have some KB coverage!")
        ),
    })


def proposal_engine(
    company_name: str,
    client_name: str,
    sector: str,
    proposal_markdown: str,
) -> str:
    """Parse proposal markdown into sections and return structured data."""
    sections = parse_markdown_to_sections(proposal_markdown)
    return json.dumps({
        "status": "preview_ready",
        "metadata": {
            "company_name": company_name,
            "client_name": client_name,
            "sector": sector,
        },
        "sections": sections,
        "markdown": proposal_markdown,
    })


def edit_section(section_id: str, content: str) -> str:
    """Update a single section. The agent loop applies the change."""
    return json.dumps({
        "status": "section_updated",
        "section_id": section_id,
        "content": content,
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
    data = {"sector": sector, "company": company, "sent_to": sent_to, "text": text}
    if proposal_id:
        data["id"] = proposal_id
    result = kb._add_proposal(data)
    return json.dumps({"status": "saved", "detail": result})


# ── Dispatcher ────────────────────────────────────────────────────

TOOL_MAP = {
    "retrieve_info": retrieve_info,
    "analyze_rfp": analyze_rfp,
    "proposal_engine": proposal_engine,
    "edit_section": edit_section,
    "update_info": update_info,
}


def execute_tool(name: str, arguments: dict) -> str:
    fn = TOOL_MAP.get(name)
    if fn is None:
        return json.dumps({"error": f"Unknown tool: {name}"})
    try:
        return fn(**arguments)
    except Exception as e:
        return json.dumps({"error": str(e)})
