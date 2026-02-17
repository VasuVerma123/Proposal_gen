"""
Multi-Step Agent Chatbot with Dynamic PDF Generation
Main FastAPI application.
"""

import os
import uuid
import json
from pathlib import Path
from dotenv import load_dotenv

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from agents.research_agent import ResearchAgent
from agents.pdf_agent import PDFAgent
from agents.build_kb_agent import BuildKBAgent

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(dotenv_path=BASE_DIR / ".env", override=True)

app = FastAPI(title="AI Document Chatbot", version="1.0.0")

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

PDF_OUTPUT_DIR = "generated_pdfs"
os.makedirs(PDF_OUTPUT_DIR, exist_ok=True)


def get_api_key() -> str:
    """Read the API key fresh from env (picks up .env changes on reload)."""
    return os.getenv("OPENAI_API_KEY", "")


def get_agents():
    """Return initialised agents, or raise if no key."""
    key = get_api_key()
    if not key:
        raise HTTPException(
            status_code=500,
            detail="OpenAI API key not configured. Set OPENAI_API_KEY in .env file.",
        )
    return (
        ResearchAgent(api_key=key),
        PDFAgent(api_key=key, output_dir=PDF_OUTPUT_DIR),
        BuildKBAgent(api_key=key),
    )

sessions: dict[str, dict] = {}


def get_or_create_session(session_id: str | None = None) -> tuple[str, dict]:
    """Get existing session or create a new one."""
    if session_id and session_id in sessions:
        return session_id, sessions[session_id]

    new_id = str(uuid.uuid4())[:8]
    sessions[new_id] = {
        "conversation": [],
        "kb_conversation": [],
        "stage": "research",  # "research", "editing", or "kb"
        "document_data": None,
        "pdf_path": None,
    }
    return new_id, sessions[new_id]


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    """Serve the main chat UI."""
    return templates.TemplateResponse("index.html", {"request": request})


@app.post("/api/chat")
async def chat(request: Request):
    """Main chat endpoint - handles the multi-step agent pipeline."""
    research_agent, pdf_agent, kb_agent = get_agents()

    body = await request.json()
    user_message = body.get("message", "").strip()
    session_id = body.get("session_id")

    if not user_message:
        raise HTTPException(status_code=400, detail="Message cannot be empty.")

    session_id, session = get_or_create_session(session_id)

    session["conversation"].append({"role": "user", "content": user_message})

    try:
        if session["stage"] == "research":
            result = await research_agent.run(session["conversation"])

            session["conversation"].append({"role": "assistant", "content": result["response"]})

            response_data = {
                "session_id": session_id,
                "response": result["response"],
                "stage": "research",
                "pdf_url": None,
            }

            if result["ready_for_pdf"] and result["document_data"]:
                session["document_data"] = result["document_data"]
                session["stage"] = "editing"

                pdf_path = await pdf_agent.generate_pdf(result["document_data"], session_id)
                session["pdf_path"] = pdf_path

                response_data["stage"] = "editing"
                response_data["pdf_url"] = f"/api/pdf/{session_id}"
                response_data["response"] = (
                    result["response"]
                    + "\n\nYour PDF has been generated! You can see it on the right. "
                    + "Feel free to ask me to make any changes to the document."
                )

            return JSONResponse(response_data)

        elif session["stage"] == "editing":
            result = await pdf_agent.modify_document(
                current_document=session["document_data"],
                modification_request=user_message,
                conversation_history=session["conversation"],
            )

            session["conversation"].append({"role": "assistant", "content": result["response"]})

            response_data = {
                "session_id": session_id,
                "response": result["response"],
                "stage": "editing",
                "pdf_url": f"/api/pdf/{session_id}",
            }

            if result["modified"] and result["document_data"]:
                session["document_data"] = result["document_data"]

                pdf_path = await pdf_agent.generate_pdf(result["document_data"], session_id)
                session["pdf_path"] = pdf_path

                response_data["pdf_updated"] = True
                response_data["response"] = (
                    result["response"]
                    + "\n\nThe PDF has been updated! Check the preview on the right."
                )

            return JSONResponse(response_data)

        elif session["stage"] == "kb":
            session["kb_conversation"].append({"role": "user", "content": user_message})

            result = await kb_agent.run(session["kb_conversation"])

            session["kb_conversation"].append({"role": "assistant", "content": result["response"]})
            session["conversation"].append({"role": "assistant", "content": result["response"]})

            return JSONResponse({
                "session_id": session_id,
                "response": result["response"],
                "stage": "kb",
                "pdf_url": None,
            })

    except Exception as e:
        session["conversation"].pop()
        raise HTTPException(status_code=500, detail=f"Agent error: {str(e)}")


@app.get("/api/pdf/{session_id}")
async def get_pdf(session_id: str):
    """Serve the generated PDF for a session."""
    pdf_path = os.path.join(PDF_OUTPUT_DIR, f"{session_id}.pdf")
    if not os.path.exists(pdf_path):
        raise HTTPException(status_code=404, detail="PDF not found.")
    return FileResponse(pdf_path, media_type="application/pdf", filename=f"document_{session_id}.pdf")


@app.get("/api/pdf/download/{session_id}")
async def download_pdf(session_id: str):
    """Download the generated PDF."""
    pdf_path = os.path.join(PDF_OUTPUT_DIR, f"{session_id}.pdf")
    if not os.path.exists(pdf_path):
        raise HTTPException(status_code=404, detail="PDF not found.")
    return FileResponse(
        pdf_path,
        media_type="application/pdf",
        filename=f"document_{session_id}.pdf",
        headers={"Content-Disposition": f"attachment; filename=document_{session_id}.pdf"},
    )


@app.post("/api/kb/switch")
async def switch_to_kb(request: Request):
    """Switch a session to Knowledge-Base mode."""
    body = await request.json()
    session_id = body.get("session_id")

    if not session_id or session_id not in sessions:
        session_id, session = get_or_create_session(session_id)
    else:
        session = sessions[session_id]

    session["stage"] = "kb"
    return JSONResponse({
        "session_id": session_id,
        "stage": "kb",
        "message": "Switched to Knowledge-Base mode. You can now store, query, and manage knowledge.",
    })


@app.get("/api/kb/status")
async def kb_status():
    """Check Neo4j connection health."""
    _, _, kb_agent = get_agents()
    connected = kb_agent.verify_connection()
    kb_agent.close()
    return JSONResponse({
        "connected": connected,
        "uri": os.getenv("NEO4J_URI", ""),
        "database": os.getenv("NEO4J_DATABASE", "neo4j"),
    })


@app.post("/api/reset")
async def reset_session(request: Request):
    """Reset a session to start fresh."""
    body = await request.json()
    session_id = body.get("session_id")

    if session_id and session_id in sessions:
        pdf_path = sessions[session_id].get("pdf_path")
        if pdf_path and os.path.exists(pdf_path):
            os.remove(pdf_path)
        del sessions[session_id]

    return JSONResponse({"status": "ok", "message": "Session reset."})


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
