"""
Proposal template structure — defines all sections and their hierarchy.

Every proposal follows this standard structure.  Sections are stored as a flat
list with ``level`` indicating depth, which makes JSON serialization and
section-by-ID lookups trivial.
"""

import re
import copy

# ── Section definitions ──────────────────────────────────────────────────

SECTIONS = [
    # 0. Cover & Administrative Information
    {"id": "0",   "title": "Cover & Administrative Information", "level": 0, "tag": "COVER"},
    {"id": "0.1", "title": "Cover Page",        "level": 1},
    {"id": "0.2", "title": "Legal Information",  "level": 1},
    {"id": "0.3", "title": "Revision History",   "level": 1},
    {"id": "0.4", "title": "Table of Contents",  "level": 1},

    # 1. Executive Summary
    {"id": "1",   "title": "Executive Summary",             "level": 0, "tag": "ES"},
    {"id": "1.1", "title": "Client Context",                "level": 1},
    {"id": "1.2", "title": "Proposed Solution Overview",    "level": 1},
    {"id": "1.3", "title": "Business Value Proposition",    "level": 1},
    {"id": "1.4", "title": "Commercial Overview Snapshot",  "level": 1},
    {"id": "1.5", "title": "Strategic Differentiators",     "level": 1},

    # 2. CtrlAgent Platform Overview
    {"id": "2",     "title": "CtrlAgent Platform Overview",      "level": 0, "tag": "PLATFORM"},
    {"id": "2.1",   "title": "Platform Positioning",             "level": 1},
    {"id": "2.2",   "title": "Agentic Lifecycle Framework",      "level": 1},
    {"id": "2.2.1", "title": "Create",                           "level": 2},
    {"id": "2.2.2", "title": "Anchor",                           "level": 2},
    {"id": "2.2.3", "title": "Unify",                            "level": 2},
    {"id": "2.2.4", "title": "Orchestrate",                      "level": 2},
    {"id": "2.2.5", "title": "Control",                          "level": 2},
    {"id": "2.2.6", "title": "Interact",                         "level": 2},
    {"id": "2.2.7", "title": "Sense",                            "level": 2},
    {"id": "2.2.8", "title": "Augment",                          "level": 2},
    {"id": "2.2.9", "title": "Evolve",                           "level": 2},
    {"id": "2.3",   "title": "Enterprise Architecture Foundation", "level": 1},
    {"id": "2.3.1", "title": "Governance & Compliance",          "level": 2},
    {"id": "2.3.2", "title": "Deterministic Controls",           "level": 2},
    {"id": "2.3.3", "title": "Security Architecture",            "level": 2},
    {"id": "2.3.4", "title": "Scalability Model",                "level": 2},
    {"id": "2.4",   "title": "Core Capabilities",                "level": 1},
    {"id": "2.4.1", "title": "Multi-Agent Orchestration",        "level": 2},
    {"id": "2.4.2", "title": "Conversational Intelligence",      "level": 2},
    {"id": "2.4.3", "title": "Autonomous Process Agents",        "level": 2},
    {"id": "2.4.4", "title": "Policy-Bound Reasoning",           "level": 2},
    {"id": "2.4.5", "title": "Continuous Learning",              "level": 2},
    {"id": "2.4.6", "title": "Stateful Conversations",           "level": 2},
    {"id": "2.4.7", "title": "Sentiment Awareness",              "level": 2},
    {"id": "2.4.8", "title": "Event-Driven Execution",           "level": 2},
    {"id": "2.4.9", "title": "Hyper-Personalization",             "level": 2},
    {"id": "2.4.10","title": "Pulse Console",                    "level": 2},
    {"id": "2.4.11","title": "Governance & Observability",       "level": 2},
    {"id": "2.4.12","title": "Business Impact Metrics",          "level": 2},

    # 3. Scope of Work
    {"id": "3",       "title": "Scope of Work",                  "level": 0, "tag": "SOW"},
    {"id": "3.1",     "title": "Business Objectives",            "level": 1},
    {"id": "3.1.1",   "title": "Customer Engagement",            "level": 2},
    {"id": "3.1.2",   "title": "Regulatory Compliance",          "level": 2},
    {"id": "3.1.3",   "title": "Automation & Resolution",        "level": 2},
    {"id": "3.1.4",   "title": "Enterprise Search Enablement",   "level": 2},
    {"id": "3.1.5",   "title": "CX Analytics",                   "level": 2},
    {"id": "3.1.6",   "title": "AI Governance Alignment",        "level": 2},
    {"id": "3.2",     "title": "Functional Scope",               "level": 1},
    {"id": "3.2.1",   "title": "Inbound Customer Care",          "level": 2},
    {"id": "3.2.1.1", "title": "Accounts",                       "level": 3},
    {"id": "3.2.1.2", "title": "Deposits",                       "level": 3},
    {"id": "3.2.1.3", "title": "Loans",                          "level": 3},
    {"id": "3.2.1.4", "title": "Credit Cards",                   "level": 3},
    {"id": "3.2.1.5", "title": "Transactions",                   "level": 3},
    {"id": "3.2.1.6", "title": "Statements",                     "level": 3},
    {"id": "3.2.1.7", "title": "Inquiries",                      "level": 3},
    {"id": "3.2.2",   "title": "Non-Financial Operations",       "level": 2},
    {"id": "3.2.2.1", "title": "Customer Profile Management",    "level": 3},
    {"id": "3.2.2.2", "title": "Branch & ATM Locations",         "level": 3},
    {"id": "3.2.2.3", "title": "Product Information",            "level": 3},
    {"id": "3.2.2.4", "title": "General FAQs",                   "level": 3},

    # 4. Response to Requirements
    {"id": "4",   "title": "Response to Requirements",  "level": 0, "tag": "RFP"},
    {"id": "4.1", "title": "Requirements Summary",      "level": 1},
    {"id": "4.2", "title": "Detailed Response Matrix",  "level": 1},
    {"id": "4.3", "title": "Compliance Mapping",         "level": 1},

    # 5. Solution Deployment
    {"id": "5",     "title": "Solution Deployment",          "level": 0, "tag": "DEPLOY"},
    {"id": "5.1",   "title": "Methodology",                 "level": 1},
    {"id": "5.1.1", "title": "Discovery",                    "level": 2},
    {"id": "5.1.2", "title": "Design",                       "level": 2},
    {"id": "5.1.3", "title": "Build",                        "level": 2},
    {"id": "5.1.4", "title": "Test",                         "level": 2},
    {"id": "5.1.5", "title": "Deploy",                       "level": 2},
    {"id": "5.1.6", "title": "Optimize",                     "level": 2},
    {"id": "5.2",   "title": "Deployment Model",            "level": 1},
    {"id": "5.2.1", "title": "Cloud",                        "level": 2},
    {"id": "5.2.2", "title": "On-Premise",                   "level": 2},
    {"id": "5.2.3", "title": "Hybrid",                       "level": 2},
    {"id": "5.2.4", "title": "BYOK / BYOM",                  "level": 2},
    {"id": "5.3",   "title": "Integration Architecture",    "level": 1},
    {"id": "5.3.1", "title": "Core Banking Systems",         "level": 2},
    {"id": "5.3.2", "title": "CRM Systems",                  "level": 2},
    {"id": "5.3.3", "title": "Knowledge Platforms",           "level": 2},
    {"id": "5.3.4", "title": "External APIs",                "level": 2},
    {"id": "5.4",   "title": "Knowledge & Policy Configuration", "level": 1},
    {"id": "5.4.1", "title": "SOP Anchoring",                "level": 2},
    {"id": "5.4.2", "title": "Compliance Embedding",         "level": 2},
    {"id": "5.4.3", "title": "Decision Controls",            "level": 2},
    {"id": "5.5",   "title": "Assumptions & Dependencies",  "level": 1},
    {"id": "5.6",   "title": "Roles & Responsibilities",    "level": 1},
    {"id": "5.6.1", "title": "Metafore Responsibilities",    "level": 2},
    {"id": "5.6.2", "title": "Client Responsibilities",      "level": 2},
    {"id": "5.7",   "title": "Project Plan",                "level": 1},
    {"id": "5.7.1", "title": "Phases",                       "level": 2},
    {"id": "5.7.2", "title": "Milestones",                   "level": 2},
    {"id": "5.7.3", "title": "Deliverables",                 "level": 2},
    {"id": "5.8",   "title": "Governance Framework",        "level": 1},
    {"id": "5.8.1", "title": "Communication Model",          "level": 2},
    {"id": "5.8.2", "title": "Escalation Model",             "level": 2},
    {"id": "5.8.3", "title": "Change Management",            "level": 2},
    {"id": "5.8.4", "title": "Reporting Framework",           "level": 2},
    {"id": "5.9",   "title": "Training & Enablement",       "level": 1},
    {"id": "5.9.1", "title": "Admin Training",               "level": 2},
    {"id": "5.9.2", "title": "Business User Training",       "level": 2},
    {"id": "5.9.3", "title": "Ongoing Enablement",           "level": 2},

    # 6. Commercial Proposal
    {"id": "6",     "title": "Commercial Proposal",   "level": 0, "tag": "COMMERCIAL"},
    {"id": "6.1",   "title": "Pricing Structure",     "level": 1},
    {"id": "6.1.1", "title": "Platform Fees",          "level": 2},
    {"id": "6.1.2", "title": "Implementation Fees",    "level": 2},
    {"id": "6.1.3", "title": "Optional Add-ons",       "level": 2},
    {"id": "6.1.4", "title": "Scaling Model",          "level": 2},
    {"id": "6.2",   "title": "Terms & Conditions",    "level": 1},
    {"id": "6.2.1", "title": "Term",                   "level": 2},
    {"id": "6.2.2", "title": "Payment Terms",          "level": 2},
    {"id": "6.2.3", "title": "Renewal Model",          "level": 2},
    {"id": "6.2.4", "title": "Commercial Assumptions", "level": 2},

    # 7. Contractual Framework
    {"id": "7",   "title": "Contractual Framework",         "level": 0, "tag": "LEGAL"},
    {"id": "7.1", "title": "Pilot/MVP Agreement Structure", "level": 1},
    {"id": "7.2", "title": "Production Transition Model",   "level": 1},
    {"id": "7.3", "title": "Governance During Pilot",       "level": 1},
    {"id": "7.4", "title": "Acceptance Criteria",           "level": 1},
]


# ── Factory ──────────────────────────────────────────────────────────────

def new_proposal(company_name: str = "", client_name: str = "", sector: str = "") -> dict:
    """Return a fresh proposal structure with every section empty."""
    sections = []
    for s in SECTIONS:
        sec = dict(s)          # shallow copy
        sec["content"] = ""
        sec["status"]  = "empty"
        sections.append(sec)

    return {
        "metadata": {
            "company_name": company_name,
            "client_name": client_name,
            "sector": sector,
        },
        "sections": sections,
    }


# ── Markdown ↔ sections helpers ──────────────────────────────────────────

_HEADING_RE = re.compile(
    r"^(#{1,5})\s+(\d+(?:\.\d+)*)\s*\.?\s*(.*)", re.MULTILINE
)


def parse_markdown_to_sections(markdown_text: str) -> dict[str, str]:
    """
    Parse a proposal markdown document into a dict mapping section_id → content.

    Expects headings like:
        # 0. Cover & Administrative Information
        ## 0.1 Cover Page
        ### 2.2.1 Create
    """
    matches = list(_HEADING_RE.finditer(markdown_text))
    sections: dict[str, str] = {}

    for i, m in enumerate(matches):
        section_id = m.group(2)
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(markdown_text)
        content = markdown_text[start:end].strip()
        if content:
            sections[section_id] = content

    return sections


def update_sections(proposal_data: dict, sections_content: dict[str, str]) -> dict:
    """Merge new content into the proposal's section list."""
    for sec in proposal_data["sections"]:
        if sec["id"] in sections_content:
            text = sections_content[sec["id"]]
            sec["content"] = text
            sec["status"] = "draft" if text else "empty"
    return proposal_data


def build_full_markdown(proposal_data: dict) -> str:
    """Combine every non-empty section into one Markdown document."""
    lines: list[str] = []
    for s in proposal_data["sections"]:
        if not s["content"]:
            continue
        heading = "#" * (s["level"] + 1)
        lines.append(f"{heading} {s['id']}. {s['title']}")
        lines.append("")
        lines.append(s["content"])
        lines.append("")
    return "\n".join(lines)


def build_preview_html(proposal_data: dict) -> str:
    """Generate a self-contained HTML preview from all sections."""
    import markdown as md_lib

    full_md = build_full_markdown(proposal_data)
    if not full_md.strip():
        return ""

    body = md_lib.markdown(full_md, extensions=["tables", "fenced_code"])
    meta = proposal_data.get("metadata", {})

    return (
        '<!DOCTYPE html><html><head><meta charset="UTF-8"/><style>'
        "@page { size: A4; margin: 2cm; }"
        "body { font-family: 'Segoe UI', Helvetica, Arial, sans-serif;"
        "       color: #1a1a2e; line-height: 1.7; padding: 40px;"
        "       max-width: 800px; margin: 0 auto; }"
        "h1 { color: #0f3460; font-size: 24px; border-bottom: 3px solid #e94560;"
        "     padding-bottom: 8px; margin-top: 32px; }"
        "h2 { color: #0f3460; font-size: 19px; border-bottom: 1px solid #ddd;"
        "     padding-bottom: 4px; margin-top: 24px; }"
        "h3 { color: #16213e; font-size: 15px; margin-top: 18px; }"
        "h4 { color: #16213e; font-size: 14px; margin-top: 14px; }"
        "h5 { color: #16213e; font-size: 13px; margin-top: 12px; }"
        "hr  { border: none; border-top: 1px solid #ddd; margin: 24px 0; }"
        "ul, ol { padding-left: 24px; }"
        "li  { margin-bottom: 4px; }"
        "table { width: 100%; border-collapse: collapse; margin: 12px 0; }"
        "th { background: #0f3460; color: #fff; padding: 8px 12px; text-align: left; }"
        "td { padding: 8px 12px; border-bottom: 1px solid #eee; }"
        "strong { color: #0f3460; }"
        "p { margin: 8px 0; }"
        f"</style></head><body>{body}</body></html>"
    )


def get_section_ids_summary() -> str:
    """Return a compact text listing of every section ID + title for the LLM prompt."""
    lines: list[str] = []
    for s in SECTIONS:
        indent = "  " * s["level"]
        tag = f" [{s['tag']}]" if s.get("tag") else ""
        lines.append(f"{indent}{s['id']}. {s['title']}{tag}")
    return "\n".join(lines)
