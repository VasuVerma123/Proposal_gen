"""
Agent loop — drives OpenAI function-calling to orchestrate the three tools.
"""

import os
import json
from openai import OpenAI
from tools import TOOL_DEFINITIONS, execute_tool

SYSTEM_PROMPT = """\
You are **ProposalBot**, an AI assistant that helps users create professional business proposals.

## Your Workflow
1. **Gather requirements** — Ask the user for:
   - Company name (the proposing company)
   - Client / recipient name
   - Industry sector (e.g. Telecom, Banking, Aviation, Insurance, Pharma, Retail)
   - Key RFP requirements or a summary of what the proposal should cover
   If the user provides everything in one message, skip the questions and proceed.

2. **Analyze the RFP** — As soon as the user provides RFP text or requirements, use the `analyze_rfp` tool. This tool:
   - Breaks the RFP into individual requirements automatically
   - Searches the knowledge base for each requirement separately
   - Returns a coverage report showing which requirements have matching templates/proposals
   Present the analysis to the user clearly — show each requirement, whether it has KB coverage (strong/partial/weak/none), and the overall coverage percentage.

3. **Search for templates** — Use `retrieve_info` to find the best overall template/proposal from the KB to use as a starting point for generation.

4. **Generate the proposal** — Use the `proposal_engine` tool with all gathered info + KB context to produce a styled proposal preview. The proposal should include these sections:
   - Executive Summary
   - Company Overview
   - Understanding of Requirements (address EVERY requirement from the analyze_rfp breakdown)
   - Proposed Solution / Scope of Work
   - Methodology & Approach
   - Project Timeline
   - Team & Expertise
   - Pricing (indicative)
   - Why Choose Us
   - Terms & Conditions

5. **Iterate** — The user can ask for changes. Re-generate using `proposal_engine` with updated content.

6. **Save & Export** — When the user confirms the proposal is final (e.g. "send to KB", "finalize", "looks good"), use `update_info` to save it to the knowledge base. Tell the user they can download the proposal as PDF or DOCX using the download buttons on the preview panel.

## Important Rules
- ALWAYS use `analyze_rfp` when the user provides RFP text or requirements — this is your PRIMARY research tool.
- Use `retrieve_info` as a secondary search to find overall matching templates.
- When presenting the RFP analysis, format it clearly with requirement IDs, titles, and coverage status.
- When using `proposal_engine`, write the `proposal_markdown` as rich Markdown with ## headings.
- Make sure every requirement from the RFP analysis is addressed in the generated proposal.
- Keep chat responses concise and professional.
- When you generate a proposal, tell the user you've created a preview and they can see it on the right panel, and that they can download it as PDF or Word using the buttons.
- If the user says "hi" or greets you, introduce yourself and ask what proposal they need.
- When the user says "send to KB" or "save", call `update_info` and confirm it was saved. Remind them about the PDF/DOCX download buttons.
"""


class ProposalAgent:
    """Manages the multi-turn conversation with tool calling."""

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY", "")
        self.client = OpenAI(api_key=self.api_key)
        self.conversation: list[dict] = [
            {"role": "system", "content": SYSTEM_PROMPT}
        ]

    def chat(self, user_message: str) -> dict:
        """
        Process one user message through the agent loop.

        Returns
        -------
        dict with keys:
            reply      : str   – assistant's text response
            preview_html : str | None – proposal HTML if generated
            tool_calls : list[str]    – names of tools invoked
        """
        self.conversation.append({"role": "user", "content": user_message})

        preview_html = None
        proposal_markdown = None
        tool_names_used: list[str] = []
        max_iterations = 10  # safety limit

        for _ in range(max_iterations):
            response = self.client.chat.completions.create(
                model="gpt-4o",
                messages=self.conversation,
                tools=TOOL_DEFINITIONS,
                tool_choice="auto",
                temperature=0.4,
            )

            msg = response.choices[0].message

            # If no tool calls, we have the final assistant reply
            if not msg.tool_calls:
                assistant_text = msg.content or ""
                self.conversation.append({"role": "assistant", "content": assistant_text})
                return {
                    "reply": assistant_text,
                    "preview_html": preview_html,
                    "proposal_markdown": proposal_markdown,
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

                # If proposal_engine returned HTML + markdown, capture both
                if fn_name == "proposal_engine":
                    try:
                        result_data = json.loads(result_str)
                        if result_data.get("status") == "preview_ready":
                            preview_html = result_data["html"]
                            proposal_markdown = result_data.get("markdown")
                    except Exception:
                        pass

                self.conversation.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result_str,
                })

        # Fallback if we hit max iterations
        return {
            "reply": "I've processed your request. Please check the preview on the right.",
            "preview_html": preview_html,
            "proposal_markdown": proposal_markdown,
            "tool_calls": tool_names_used,
        }

    def reset(self):
        """Clear conversation history."""
        self.conversation = [
            {"role": "system", "content": SYSTEM_PROMPT}
        ]
