# AI Proposal Generator

A full-stack AI-powered proposal generator with a split-screen UI. The left panel is a chat interface where users describe what they need; the right panel shows a **live preview** of the generated proposal document that updates dynamically as the conversation progresses.

The system uses **OpenAI GPT-4o** with function-calling (tool use) and a **Neo4j Aura** knowledge base to search for existing proposal templates, match RFP requirements, and generate professional styled proposals.

---

## Project Structure

```
Proposal_gen/
├── backend/                  # FastAPI Python backend
│   ├── .env                  # API keys & Neo4j credentials (git-ignored)
│   ├── requirements.txt      # Python dependencies
│   ├── main.py               # FastAPI application & endpoints
│   ├── db.py                 # Neo4j driver & schema management
│   ├── agent.py              # OpenAI agent loop with function-calling
│   ├── tools.py              # Three AI tools: retrieve_info, update_info, proposal_engine
│   ├── pdf_builder.py        # Proposal HTML renderer
│   ├── embeddings.py         # OpenAI embedding helper
│   ├── chunker.py            # Token-based text chunker
│   ├── upload_proposals.py   # Bulk PDF uploader script
│   └── agents/
│       ├── __init__.py
│       └── build_kb_agent.py # Knowledge-base agent (Neo4j CRUD + vector search)
├── frontend/                 # React + Vite frontend
│   ├── index.html
│   ├── package.json
│   ├── vite.config.js
│   └── src/
│       ├── main.jsx          # React entry point
│       ├── App.jsx           # Main component — split-screen UI
│       ├── App.css           # Dark-themed styling
│       └── index.css         # Global CSS reset
├── Files/                    # Place proposal PDFs here for bulk upload
├── .gitignore
└── README.md
```

---

## Backend File-by-File Explanation

### `backend/main.py` — FastAPI Application

The central entry point for the backend server. Responsibilities:

- **Lifespan management**: On startup, connects to Neo4j and sets up the database schema (constraints, indexes, vector indexes). On shutdown, cleanly closes connections.
- **CORS middleware**: Allows the frontend (any origin) to communicate with the backend.
- **Endpoints**:
  - `GET /` — Health check, returns app name.
  - `GET /api/health` — Simple health probe.
  - `GET /api/neo4j-status` — Tests Neo4j connectivity and returns `{connected: true/false}`.
  - `GET /api/key-status` — Returns whether an OpenAI API key is set (masked).
  - `POST /api/set-key` — Accepts a new OpenAI API key at runtime, resets all agent sessions so they use the new key.
  - `POST /api/chat` — Main chat endpoint. Accepts `{message, session_id}`, routes through the `ProposalAgent` (which may call tools), and returns `{reply, preview_html, tool_calls}`.
  - `POST /api/reset` — Clears the conversation history for a given session.
  - `POST /api/upload-logo` — Accepts an image file and stores it as a base64 data-URI for logo embedding in proposals.
  - `POST /api/ingest/proposal` — Uploads a proposal PDF, extracts text, and ingests it into Neo4j with embeddings.
  - `POST /api/ingest/rfp` — Same as above but for RFP documents.
  - `POST /api/ingest/asset` — Same as above but for asset documents.
  - `GET /api/documents` — Lists all Proposals, RFPs, and Assets currently stored in Neo4j with their chunk counts.

---

### `backend/db.py` — Neo4j Driver & Schema Management

Manages the Neo4j database connection with production-grade resilience:

- **`get_driver()`** — Creates a singleton Neo4j driver. Tries `neo4j+s://` first (full SSL verification), and falls back to `neo4j+ssc://` (skip certificate check) if the first fails — necessary for some Neo4j Aura free-tier environments.
- **`_reset_driver()`** — Force-closes and clears the cached driver, used when stale connections are detected.
- **`run_query(cypher, params)`** — Executes a Cypher query with **automatic retry** (up to 3 attempts). On `ServiceUnavailable`, `SessionExpired`, `ConnectionResetError`, or `OSError`, it resets the driver and retries. Returns a list of record dicts.
- **`run_query_single(cypher, params)`** — Same as `run_query` but returns only the first record or `None`.
- **Schema definitions** — Declares:
  - Uniqueness constraints on `RFP.id`, `Proposal.id`, `Asset.id`.
  - Property indexes on `.sector` for fast sector-based lookups.
  - Vector indexes (1536 dimensions, cosine similarity) on `ProposalChunk.embedding`, `RFPChunk.embedding`, `AssetChunk.embedding` for semantic search.
- **`setup_schema()`** — Creates all constraints, indexes, and vector indexes idempotently (uses `IF NOT EXISTS`).
- **`close_driver()`** — Cleanly closes the driver on shutdown.

---

### `backend/agent.py` — OpenAI Agent Loop

Implements the multi-turn conversation orchestrator using OpenAI's function-calling API:

- **`ProposalAgent` class** — Holds conversation history and an OpenAI client.
  - **System prompt** — Instructs GPT-4o to act as "ProposalBot" with a defined workflow:
    1. Gather requirements (company, client, sector, RFP details).
    2. Search the knowledge base using `retrieve_info`.
    3. Generate a proposal using `proposal_engine`.
    4. Iterate based on user feedback.
    5. Save the final proposal using `update_info`.
  - **`chat(user_message)`** — The main loop:
    1. Appends the user message to conversation history.
    2. Calls OpenAI with the conversation + tool definitions.
    3. If the model returns tool calls, executes them via `tools.execute_tool()` and feeds results back.
    4. Repeats until the model returns a text response (up to 10 iterations for safety).
    5. If `proposal_engine` was called, captures the generated HTML for the preview panel.
    6. Returns `{reply, preview_html, tool_calls}`.
  - **`reset()`** — Clears conversation history for a fresh start.

---

### `backend/tools.py` — Three AI Tools

Defines the three tools the agent can invoke, plus their OpenAI function-calling schemas:

#### Tool 1: `retrieve_info`
- **Purpose**: Search the Neo4j knowledge base for proposals, RFPs, and assets that match the user's requirements.
- **Input**: `query` (search text), `top_k` (number of results, default 5).
- **Process**: Calls `BuildKBAgent.search_similar()` which embeds the query and runs vector similarity search across all chunk indexes (`proposal_chunk_embedding`, `rfp_chunk_embedding`, `asset_chunk_embedding`).
- **Output**: JSON with matched items including type, ID, sector, company, similarity score, and a snippet of matched text.

#### Tool 2: `update_info`
- **Purpose**: Save a confirmed/finalized proposal back into the knowledge base for future reuse.
- **Input**: `sector`, `company`, `sent_to`, `text`, and optionally `proposal_id`.
- **Process**: Calls `BuildKBAgent._add_proposal()` which merges the proposal node, chunks the text, generates embeddings, stores chunks, creates similarity edges, and rolls up parent-level relationships.
- **Output**: JSON confirmation with status and detail message.

#### Tool 3: `proposal_engine`
- **Purpose**: Generate a styled proposal HTML preview from structured content.
- **Input**: `company_name`, `client_name`, `sector`, `proposal_markdown` (full proposal in Markdown with `##` headings).
- **Process**: Parses the Markdown into sections using `pdf_builder.sections_from_markdown()`, then builds a complete HTML document with `pdf_builder.build_proposal_html()` featuring a styled cover page, section layouts, and footer.
- **Output**: JSON with `{status: "preview_ready", html: "...", sections_count: N}`. The HTML is captured by the agent and sent to the frontend for live preview.

Also includes:
- **`TOOL_DEFINITIONS`** — The OpenAI function-calling schema array passed to the chat completions API.
- **`execute_tool(name, arguments)`** — Dispatcher that routes tool calls to the correct function with error handling.

---

### `backend/pdf_builder.py` — Proposal HTML Renderer

Generates professional-looking HTML proposals:

- **`build_proposal_html(company_name, client_name, sector, sections, logo_data_uri)`** — Builds a complete HTML document with:
  - A gradient cover page (blue) with company logo, proposal title, sector, and date.
  - Multiple content sections with styled headings, paragraphs, lists, and tables.
  - A footer with copyright notice.
  - Embedded CSS for professional typography and layout.
- **`sections_from_markdown(md_text)`** — Parses markdown text with `##` headings into a list of `{title, body}` dicts. Each heading starts a new section; body content is converted to HTML.
- **`_lines_to_html(lines)`** — Lightweight Markdown-to-HTML converter that handles paragraphs, bullet lists (`- ` and `* `), bold (`**text**`), and blank lines.

---

### `backend/embeddings.py` — OpenAI Embedding Helper

Thin wrapper around OpenAI's embedding API:

- **`get_embeddings(texts, api_key)`** — Sends a batch of text strings to the `text-embedding-3-small` model (1536 dimensions) and returns the embedding vectors.
- **`get_embedding(text, api_key)`** — Convenience wrapper for a single text string.

---

### `backend/chunker.py` — Token-Based Text Chunker

Splits long text into manageable overlapping chunks for embedding:

- **`chunk_text(text, chunk_size=800, overlap=100)`** — Uses `tiktoken` (GPT-4o tokenizer) to:
  1. Encode the text into tokens.
  2. Split into windows of 800 tokens with 100-token overlap.
  3. Decode each window back to text.
  
  The overlap ensures no information is lost at chunk boundaries.

---

### `backend/agents/__init__.py`

Empty init file — makes `agents/` a Python package so `build_kb_agent` can be imported.

---

### `backend/agents/build_kb_agent.py` — Knowledge-Base Agent

The core class that manages all Neo4j knowledge-base operations:

- **`BuildKBAgent(api_key)`** — Constructor:
  - Connects to Neo4j with SSL fallback (same as `db.py`).
  - Bootstraps the schema (constraints, property indexes, vector indexes).

- **Ingestion pipeline** (`_ingest` method):
  1. **Merge parent node** — Creates or updates the parent node (`:Proposal`, `:RFP`, or `:Asset`) with metadata (ID, sector, company, etc.).
  2. **Chunk text** — Splits the document text into overlapping token chunks.
  3. **Embed chunks** — Generates OpenAI embeddings for each chunk.
  4. **Store chunk nodes** — Creates chunk nodes (`:ProposalChunk`, `:RFPChunk`, `:AssetChunk`) with text and embedding, linked via `:HAS_CHUNK` edges.
  5. **Cross-link via vector similarity** — Queries each vector index to find similar chunks from other documents, creates `:SIMILAR_TO` edges with similarity scores.
  6. **Roll up parent edges** — Aggregates chunk-level similarities into parent-level `:MATCHED_TO` edges.

- **Public ingest methods**: `_add_proposal(data)`, `_add_rfp(data)`, `_add_asset(data)`.

- **`search_similar(query_text, top_k)`** — Vector search across all chunk types:
  1. Embeds the query text.
  2. Queries all three vector indexes.
  3. Joins chunks back to their parent nodes.
  4. Returns deduplicated, score-sorted results with parent metadata and matched text.

- **`_list_all()`** — Returns a formatted listing of all KB items with chunk counts.

- **`verify_connection()`** / **`close()`** — Connection management helpers.

---

### `backend/upload_proposals.py` — Bulk PDF Uploader

A standalone script for batch-uploading proposal PDFs into the knowledge base:

- Reads PDFs from the `Files/` directory.
- Defines a list of proposals with metadata (file name, ID, sector, company, recipient).
- For each PDF:
  1. Extracts text using `PyPDF2` (truncated to 6000 chars for embedding efficiency).
  2. Calls `BuildKBAgent._add_proposal()` to ingest into Neo4j.
- After upload, lists all KB items and checks for auto-generated similarity relationships.
- Run with: `python upload_proposals.py` (from the `backend/` directory with venv activated).

---

### `backend/requirements.txt` — Python Dependencies

| Package            | Purpose                                      |
|--------------------|----------------------------------------------|
| `fastapi`          | Web framework for the API server             |
| `uvicorn`          | ASGI server to run FastAPI                   |
| `openai`           | OpenAI API client (GPT-4o + embeddings)      |
| `python-dotenv`    | Load `.env` file into environment variables  |
| `pydantic`         | Data validation for request/response models  |
| `neo4j`            | Official Neo4j Python driver                 |
| `pypdf2`           | PDF text extraction                          |
| `tiktoken`         | OpenAI tokenizer for text chunking           |
| `python-multipart` | File upload support in FastAPI               |
| `jinja2`           | Template engine (FastAPI dependency)         |

---

## Frontend Overview

| File              | Purpose                                                    |
|-------------------|------------------------------------------------------------|
| `App.jsx`         | Main component: split-screen with chat (left) and live proposal preview (right). Handles message sending, tool-call indicators, KB document management, PDF uploads, and a settings modal for API key management. |
| `App.css`         | Dark-themed styling with gradient accents, chat bubbles, typing animation, modal, responsive layout. |
| `main.jsx`        | React entry point — renders `<App />` into `#root`.       |
| `index.css`       | Global CSS reset.                                          |
| `vite.config.js`  | Vite config with React plugin and API proxy to backend.    |

---

## How to Run

### Prerequisites
- Python 3.10+
- Node.js 18+
- Neo4j Aura instance (free tier works)
- OpenAI API key

### Backend
```bash
cd Proposal_gen
python -m venv venv
.\venv\Scripts\Activate.ps1    # Windows
pip install -r backend/requirements.txt
cd backend
# Create .env with your credentials (see .env.example)
python -m uvicorn main:app --reload --port 8000
```

### Frontend
```bash
cd Proposal_gen/frontend
npm install
npm run dev
```

### Bulk Upload Proposals
```bash
cd Proposal_gen/backend
# Place PDFs in ../Files/ directory
python upload_proposals.py
```

---

## Environment Variables (`.env`)

```
OPENAI_API_KEY=sk-proj-...
NEO4J_URI=neo4j+s://xxxxx.databases.neo4j.io
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=your_password
NEO4J_DATABASE=neo4j
```

---

## Architecture Flow

```
User types message
       │
       ▼
  Frontend (React)
       │  POST /api/chat
       ▼
  FastAPI (main.py)
       │
       ▼
  ProposalAgent (agent.py)
       │  OpenAI GPT-4o with tools
       ▼
  ┌─────────────────────────────────┐
  │  Tool Calls (tools.py)          │
  │                                 │
  │  retrieve_info ──► Neo4j KB     │
  │  proposal_engine ──► HTML build │
  │  update_info ──► Neo4j KB save  │
  └─────────────────────────────────┘
       │
       ▼
  Response: {reply, preview_html, tool_calls}
       │
       ▼
  Frontend renders:
    Left panel  → chat reply
    Right panel → proposal HTML preview (iframe)
```
