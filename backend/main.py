"""
FastAPI backend for the AI Proposal Generator.
"""

import os
import sys
import json
import base64
from io import BytesIO
from contextlib import asynccontextmanager

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv

# Ensure backend dir is on path
sys.path.insert(0, os.path.dirname(__file__))

load_dotenv()

from db import get_driver, setup_schema, close_driver, run_query
from agent import ProposalAgent
from agents.build_kb_agent import BuildKBAgent
from PyPDF2 import PdfReader

# ── Global state ─────────────────────────────────────────────────

_agents: dict[str, ProposalAgent] = {}  # session_id -> agent
_kb: BuildKBAgent | None = None
_logo_store: dict[str, str] = {}  # session_id -> data URI
_runtime_api_key: str | None = None  # set via /api/set-key


def _get_api_key() -> str:
    return _runtime_api_key or os.getenv("OPENAI_API_KEY", "")


def _get_kb() -> BuildKBAgent:
    global _kb
    if _kb is None:
        _kb = BuildKBAgent(api_key=_get_api_key())
    return _kb


# ── Lifespan ─────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    print("[main] Starting up...")
    try:
        get_driver()
        setup_schema()
        print("[main] Neo4j ready")
    except Exception as e:
        print(f"[main] Neo4j startup warning: {e}")
    yield
    # Shutdown
    close_driver()
    if _kb:
        _kb.close()
    print("[main] Shut down")


# ── App ──────────────────────────────────────────────────────────

app = FastAPI(title="AI Proposal Generator", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Request / Response models ────────────────────────────────────

class ChatRequest(BaseModel):
    message: str
    session_id: str = "default"


class ChatResponse(BaseModel):
    reply: str
    preview_html: str | None = None
    proposal_markdown: str | None = None
    tool_calls: list[str] = []


class ExportRequest(BaseModel):
    markdown: str


# ── Endpoints ────────────────────────────────────────────────────

@app.get("/")
def root():
    return {"status": "ok", "app": "AI Proposal Generator"}


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/neo4j-status")
def neo4j_status():
    try:
        driver = get_driver()
        driver.verify_connectivity()
        return {"connected": True}
    except Exception as e:
        return {"connected": False, "error": str(e)}


# ── API Key management ───────────────────────────────────────────

class SetKeyRequest(BaseModel):
    api_key: str


@app.get("/api/key-status")
def key_status():
    key = _get_api_key()
    return {"has_key": bool(key), "masked": f"{key[:8]}...{key[-4:]}" if len(key) > 12 else ""}


@app.post("/api/set-key")
def set_key(req: SetKeyRequest):
    global _runtime_api_key, _agents, _kb
    _runtime_api_key = req.api_key.strip()
    os.environ["OPENAI_API_KEY"] = _runtime_api_key
    # Reset agents so they pick up the new key
    _agents = {}
    if _kb:
        _kb.close()
        _kb = None
    return {"status": "ok", "masked": f"{_runtime_api_key[:8]}...{_runtime_api_key[-4:]}"}


# ── Chat ─────────────────────────────────────────────────────────

@app.post("/api/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    api_key = _get_api_key()
    if not api_key:
        raise HTTPException(status_code=400, detail="No API key set. Go to Settings and enter your OpenAI API key.")

    sid = req.session_id

    # Create agent for this session if needed
    if sid not in _agents:
        _agents[sid] = ProposalAgent(api_key=api_key)

    agent = _agents[sid]

    try:
        result = agent.chat(req.message)
        return ChatResponse(
            reply=result["reply"],
            preview_html=result.get("preview_html"),
            proposal_markdown=result.get("proposal_markdown"),
            tool_calls=result.get("tool_calls", []),
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/reset")
def reset_chat(session_id: str = "default"):
    if session_id in _agents:
        _agents[session_id].reset()
    return {"status": "reset"}


# ── Logo upload ──────────────────────────────────────────────────

@app.post("/api/upload-logo")
async def upload_logo(
    file: UploadFile = File(...),
    session_id: str = Form("default"),
):
    contents = await file.read()
    mime = file.content_type or "image/png"
    data_uri = f"data:{mime};base64,{base64.b64encode(contents).decode()}"
    _logo_store[session_id] = data_uri
    return {"status": "ok", "size": len(contents)}


# ── Document ingestion ───────────────────────────────────────────

@app.post("/api/ingest/proposal")
async def ingest_proposal(
    file: UploadFile = File(...),
    sector: str = Form("General"),
    company: str = Form(""),
    sent_to: str = Form(""),
):
    text = await _extract_pdf_text(file)
    kb = _get_kb()
    result = kb._add_proposal({
        "sector": sector,
        "company": company,
        "sent_to": sent_to,
        "text": text[:6000],
    })
    return {"status": "ok", "detail": result}


@app.post("/api/ingest/rfp")
async def ingest_rfp(
    file: UploadFile = File(...),
    sector: str = Form("General"),
    company: str = Form(""),
):
    text = await _extract_pdf_text(file)
    kb = _get_kb()
    result = kb._add_rfp({
        "sector": sector,
        "company": company,
        "text": text[:6000],
    })
    return {"status": "ok", "detail": result}


@app.post("/api/ingest/asset")
async def ingest_asset(
    file: UploadFile = File(...),
    sector: str = Form("General"),
    company: str = Form(""),
):
    text = await _extract_pdf_text(file)
    kb = _get_kb()
    result = kb._add_asset({
        "sector": sector,
        "company": company,
        "text": text[:6000],
    })
    return {"status": "ok", "detail": result}


# ── KB listing ───────────────────────────────────────────────────

@app.get("/api/documents")
def list_documents():
    try:
        kb = _get_kb()
        proposals = run_query(
            "MATCH (p:Proposal) "
            "OPTIONAL MATCH (p)-[:HAS_CHUNK]->(c) "
            "RETURN p.id AS id, p.sector AS sector, p.company AS company, "
            "       p.sent_to AS sent_to, count(c) AS chunks ORDER BY p.id"
        )
        rfps = run_query(
            "MATCH (r:RFP) "
            "OPTIONAL MATCH (r)-[:HAS_CHUNK]->(c) "
            "RETURN r.id AS id, r.sector AS sector, r.company AS company, "
            "       count(c) AS chunks ORDER BY r.id"
        )
        assets = run_query(
            "MATCH (a:Asset) "
            "OPTIONAL MATCH (a)-[:HAS_CHUNK]->(c) "
            "RETURN a.id AS id, a.sector AS sector, a.company AS company, "
            "       count(c) AS chunks ORDER BY a.id"
        )
        return {"proposals": proposals, "rfps": rfps, "assets": assets}
    except Exception as e:
        return {"proposals": [], "rfps": [], "assets": [], "error": str(e)}


# ── Export as PDF / DOCX via Thesys ──────────────────────────────

@app.post("/api/export/pdf")
def export_pdf(req: ExportRequest):
    """Generate a styled PDF from the proposal markdown using thesis_tool."""
    from thesis_tool import save_as_pdf
    import tempfile

    md = req.markdown
    if not md or not md.strip():
        raise HTTPException(status_code=400, detail="No markdown content provided.")

    try:
        # Generate PDF directly from the original markdown
        # (Thesys C1 API returns structured JSON, not markdown — so we skip it)
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
        tmp.close()
        save_as_pdf(md, tmp.name)

        pdf_bytes = open(tmp.name, "rb").read()
        os.unlink(tmp.name)

        return StreamingResponse(
            BytesIO(pdf_bytes),
            media_type="application/pdf",
            headers={"Content-Disposition": "attachment; filename=proposal.pdf"},
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"PDF generation failed: {e}")


@app.post("/api/export/docx")
def export_docx(req: ExportRequest):
    """Generate a styled DOCX from the proposal markdown using thesis_tool."""
    from thesis_tool import save_as_docx
    import tempfile

    md = req.markdown
    if not md or not md.strip():
        raise HTTPException(status_code=400, detail="No markdown content provided.")

    try:
        # Generate DOCX directly from the original markdown
        # (Thesys C1 API returns structured JSON, not markdown — so we skip it)
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".docx")
        tmp.close()
        save_as_docx(md, tmp.name)

        docx_bytes = open(tmp.name, "rb").read()
        os.unlink(tmp.name)

        return StreamingResponse(
            BytesIO(docx_bytes),
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={"Content-Disposition": "attachment; filename=proposal.docx"},
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DOCX generation failed: {e}")


# ── Helpers ──────────────────────────────────────────────────────

async def _extract_pdf_text(file: UploadFile) -> str:
    """Extract text from an uploaded PDF."""
    import io
    contents = await file.read()
    reader = PdfReader(io.BytesIO(contents))
    pages = []
    for page in reader.pages:
        text = page.extract_text()
        if text:
            pages.append(text.strip())
    return "\n\n".join(pages)
