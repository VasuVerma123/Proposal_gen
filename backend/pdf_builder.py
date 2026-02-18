"""
Build a proposal preview as styled HTML (rendered in an iframe on the frontend).
"""

import base64
import datetime as _dt

PROPOSAL_CSS = """
body {
    font-family: 'Segoe UI', Arial, sans-serif;
    margin: 0; padding: 0;
    color: #1e293b;
    background: #fff;
}
.cover {
    background: linear-gradient(135deg, #1e3a5f 0%, #2563eb 100%);
    color: #fff;
    padding: 60px 48px 48px;
    min-height: 320px;
    display: flex;
    flex-direction: column;
    justify-content: flex-end;
}
.cover .logo { max-height: 60px; margin-bottom: 24px; }
.cover h1 { font-size: 32px; margin: 0 0 8px; font-weight: 700; }
.cover .subtitle { font-size: 16px; opacity: 0.85; }
.cover .meta { margin-top: 24px; font-size: 13px; opacity: 0.7; }
.section {
    padding: 32px 48px;
}
.section h2 {
    font-size: 22px; color: #1e3a5f;
    border-bottom: 2px solid #2563eb;
    padding-bottom: 6px; margin-bottom: 16px;
}
.section p, .section li {
    font-size: 14px; line-height: 1.7;
}
ul { padding-left: 20px; }
table {
    width: 100%; border-collapse: collapse; margin: 12px 0;
}
th, td {
    border: 1px solid #cbd5e1; padding: 8px 12px;
    font-size: 13px; text-align: left;
}
th { background: #f1f5f9; font-weight: 600; }
.footer {
    text-align: center; padding: 16px;
    font-size: 11px; color: #94a3b8;
    border-top: 1px solid #e2e8f0;
}
"""


def build_proposal_html(
    company_name: str,
    client_name: str,
    sector: str,
    sections: list[dict],
    logo_data_uri: str | None = None,
) -> str:
    """
    Build a full proposal HTML document.

    Parameters
    ----------
    company_name : str  – The proposing company's name.
    client_name  : str  – The client / RFP issuer.
    sector       : str  – Industry sector.
    sections     : list[dict]  – Each dict has keys 'title' and 'body' (HTML string).
    logo_data_uri : str | None – A data:image/... URI for the logo.

    Returns
    -------
    str – complete HTML document.
    """
    today = _dt.date.today().strftime("%B %d, %Y")
    logo_html = ""
    if logo_data_uri:
        logo_html = f'<img class="logo" src="{logo_data_uri}" alt="logo" />'

    section_html = ""
    for sec in sections:
        section_html += (
            f'<div class="section">'
            f'<h2>{sec["title"]}</h2>'
            f'{sec["body"]}'
            f'</div>'
        )

    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><style>{PROPOSAL_CSS}</style></head>
<body>
  <div class="cover">
    {logo_html}
    <h1>Proposal for {client_name}</h1>
    <div class="subtitle">{sector} Industry Solution</div>
    <div class="meta">Prepared by {company_name} &mdash; {today}</div>
  </div>
  {section_html}
  <div class="footer">&copy; {_dt.date.today().year} {company_name}. Confidential.</div>
</body>
</html>"""


def sections_from_markdown(md_text: str) -> list[dict]:
    """
    Convert markdown-ish text (with ## headings) into a list of
    {title, body} section dicts with simple HTML conversion.
    """
    import re
    sections: list[dict] = []
    current_title = "Overview"
    current_body_lines: list[str] = []

    for line in md_text.split("\n"):
        heading_match = re.match(r"^#{1,3}\s+(.+)$", line)
        if heading_match:
            # flush previous section
            if current_body_lines:
                sections.append({
                    "title": current_title,
                    "body": _lines_to_html(current_body_lines),
                })
            current_title = heading_match.group(1).strip()
            current_body_lines = []
        else:
            current_body_lines.append(line)

    # flush last section
    if current_body_lines:
        sections.append({
            "title": current_title,
            "body": _lines_to_html(current_body_lines),
        })

    return sections


def _lines_to_html(lines: list[str]) -> str:
    """Very lightweight markdown-to-HTML for proposal sections."""
    import re
    html_parts: list[str] = []
    in_ul = False
    for line in lines:
        stripped = line.strip()
        if not stripped:
            if in_ul:
                html_parts.append("</ul>")
                in_ul = False
            continue
        # bullet
        if re.match(r"^[-*]\s", stripped):
            if not in_ul:
                html_parts.append("<ul>")
                in_ul = True
            html_parts.append(f"<li>{stripped[2:]}</li>")
        else:
            if in_ul:
                html_parts.append("</ul>")
                in_ul = False
            # bold
            stripped = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", stripped)
            html_parts.append(f"<p>{stripped}</p>")
    if in_ul:
        html_parts.append("</ul>")
    return "\n".join(html_parts)
