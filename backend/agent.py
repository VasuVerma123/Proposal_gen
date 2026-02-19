"""
Agent loop — drives OpenAI function-calling to orchestrate tools.

The ProposalAgent keeps a structured proposal (JSON) that persists across
chat turns.  Every API response returns the full proposal_data so the
frontend can always render the section outline.
"""

import os
import json
from openai import OpenAI
from tools import TOOL_DEFINITIONS, execute_tool
from proposal_template import (
    new_proposal,
    update_sections,
    build_full_markdown,
    build_preview_html,
    get_section_ids_summary,
)

SECTION_OUTLINE = get_section_ids_summary()

SYSTEM_PROMPT = f"""\
You are **ProposalBot**, an AI assistant that creates professional business proposals.

The right panel of the UI ALWAYS shows the proposal outline.  Users can see
which sections are filled and which are empty.  They can ask you to:
  - "generate the entire proposal"
  - "edit section 2.4.3"
  - "rewrite 1.1 with more detail about the client"
  - "condense section 5 to 300 words"

## Proposal Section Structure
{SECTION_OUTLINE}

## Your Tools

| Tool | When to use |
|------|-------------|
| `analyze_rfp` | When the user provides RFP text or requirements — break into individual requirements and search KB for each |
| `retrieve_info` | Secondary KB search for overall matching templates |
| `proposal_engine` | Generate the FULL proposal (all sections). Write markdown with section headings like `# 0. Title`, `## 0.1 SubTitle`, `### 2.2.1 Item` |
| `edit_section` | Edit a SINGLE section by ID. Provide `section_id` and `content` |
| `update_info` | Save the final proposal to KB when user confirms |

## Workflow

1. **Gather info** — Company name, client name, sector, RFP requirements.
2. **Analyze** — `analyze_rfp` to decompose requirements, then `retrieve_info` for templates.
3. **Generate** — `proposal_engine` with full markdown using section headings.
   Write content for sections 0 through 7.  At minimum, cover all level-0
   and level-1 sections.  Level-2+ subsections can be brief or left for later.
4. **Edit** — When user asks to change a specific section, use `edit_section`.
5. **Save** — When user confirms, `update_info` to save to KB.

## Heading Format for proposal_engine

When you write `proposal_markdown`, use these exact heading patterns so the
parser can map content to the correct section:

```
# 0. Cover & Administrative Information
## 0.1 Cover Page
(content here)
## 0.2 Legal Information
(content here)
# 1. Executive Summary
## 1.1 Client Context
(content here)
```

## Important Rules
- ALWAYS use `analyze_rfp` when user provides RFP text.
- When generating, address EVERY level-0 and level-1 section.
- For `edit_section`, only pass the section content (no heading needed).
- Tell the user they can see the outline on the right and ask to edit any section.
- Mention PDF/DOCX download buttons after generating.
- If the user says "hi", introduce yourself and ask what proposal they need.
"""


class ProposalAgent:
    """Multi-turn conversation manager with structured proposal state."""

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY", "")
        self.client = OpenAI(api_key=self.api_key)
        self.conversation: list[dict] = [
            {"role": "system", "content": SYSTEM_PROMPT}
        ]
        self.proposal_data = new_proposal()

    def chat(self, user_message: str) -> dict:
        """
        Process one user message.

        Returns dict with:
            reply           : str
            preview_html    : str | None
            proposal_markdown : str | None
            proposal_data   : dict          -- full structured proposal JSON
            tool_calls      : list[str]
        """
        self.conversation.append({"role": "user", "content": user_message})

        preview_html = None
        proposal_markdown = None
        tool_names_used: list[str] = []
        max_iterations = 10

        for _ in range(max_iterations):
            response = self.client.chat.completions.create(
                model="gpt-4o",
                messages=self.conversation,
                tools=TOOL_DEFINITIONS,
                tool_choice="auto",
                temperature=0.4,
            )

            msg = response.choices[0].message

            if not msg.tool_calls:
                text = msg.content or ""
                self.conversation.append({"role": "assistant", "content": text})

                # Build latest preview from current proposal state
                if any(s["content"] for s in self.proposal_data["sections"]):
                    preview_html = build_preview_html(self.proposal_data)
                    proposal_markdown = build_full_markdown(self.proposal_data)

                return {
                    "reply": text,
                    "preview_html": preview_html,
                    "proposal_markdown": proposal_markdown,
                    "proposal_data": self.proposal_data,
                    "tool_calls": tool_names_used,
                }

            # Process tool calls
            self.conversation.append(msg.model_dump())

            for tc in msg.tool_calls:
                fn_name = tc.function.name
                try:
                    fn_args = json.loads(tc.function.arguments)
                except json.JSONDecodeError:
                    fn_args = {}

                tool_names_used.append(fn_name)
                result_str = execute_tool(fn_name, fn_args)

                # ── Apply side-effects to proposal state ──────────
                if fn_name == "proposal_engine":
                    try:
                        data = json.loads(result_str)
                        if data.get("status") == "preview_ready":
                            # Update metadata
                            meta = data.get("metadata", {})
                            if meta:
                                self.proposal_data["metadata"].update(meta)
                            # Update sections from parsed markdown
                            sections = data.get("sections", {})
                            if sections:
                                update_sections(self.proposal_data, sections)
                    except Exception:
                        pass

                elif fn_name == "edit_section":
                    try:
                        data = json.loads(result_str)
                        if data.get("status") == "section_updated":
                            sid = data.get("section_id")
                            content = data.get("content", "")
                            if sid:
                                update_sections(self.proposal_data, {sid: content})
                    except Exception:
                        pass

                self.conversation.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result_str,
                })

        # Fallback
        if any(s["content"] for s in self.proposal_data["sections"]):
            preview_html = build_preview_html(self.proposal_data)
            proposal_markdown = build_full_markdown(self.proposal_data)

        return {
            "reply": "I've processed your request. Check the outline on the right.",
            "preview_html": preview_html,
            "proposal_markdown": proposal_markdown,
            "proposal_data": self.proposal_data,
            "tool_calls": tool_names_used,
        }

    def reset(self):
        """Clear conversation and proposal."""
        self.conversation = [
            {"role": "system", "content": SYSTEM_PROMPT}
        ]
        self.proposal_data = new_proposal()
