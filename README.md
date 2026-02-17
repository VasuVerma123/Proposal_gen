# AI Document Assistant - Multi-Step Agent Chatbot with Dynamic PDF

A full-stack chatbot application featuring a split UI with real-time PDF generation. Built with **FastAPI**, **OpenAI GPT-4**, and a modern dark-themed frontend.

## Architecture

The app uses a **multi-step agent pipeline**:

```
User Chat → Agent 1 (Research) → Agent 2 (PDF) → Dynamic Preview
                ↑                                        ↓
                └──── User requests modifications ←──────┘
```

### Agent 1: Research Agent
- Gathers information from multiple sources (Wikipedia, web search)
- Asks clarifying questions to collect all required data
- Structures information into a document-ready format

### Agent 2: PDF Agent
- Generates professional PDFs using ReportLab
- Handles modification requests (add sections, edit content, change structure)
- Regenerates PDF in real-time after each change

## Features

- **Split UI**: Chat panel (left) + PDF preview (right) with resizable divider
- **Real-time PDF updates**: PDF refreshes automatically when you request changes
- **Multi-source research**: Agent gathers info from Wikipedia and web APIs
- **Download support**: Download generated PDFs directly
- **Session management**: Each conversation maintains its own state
- **Modern dark theme**: Beautiful, responsive UI

## Setup

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure OpenAI API key

Create a `.env` file in the project root:

```
OPENAI_API_KEY=sk-your-openai-api-key-here
```

### 3. Run the application

```bash
python app.py
```

Or with uvicorn directly:

```bash
uvicorn app:app --host 0.0.0.0 --port 8000 --reload
```

### 4. Open in browser

Navigate to: [http://localhost:8000](http://localhost:8000)

## Usage

1. **Start a conversation** - Tell the assistant what document you want (e.g., "Create a project proposal for a mobile app")
2. **Answer questions** - The Research Agent will ask for details it needs
3. **PDF is generated** - Once enough info is gathered, a PDF appears on the right
4. **Request changes** - Chat to modify the document ("Add a budget section", "Change the title", etc.)
5. **Download** - Click the download button to save your PDF

## Project Structure

```
Demo/
├── app.py                  # FastAPI main application
├── agents/
│   ├── __init__.py
│   ├── research_agent.py   # Agent 1: Information gathering
│   └── pdf_agent.py        # Agent 2: PDF generation & modification
├── templates/
│   └── index.html          # Main HTML template
├── static/
│   ├── style.css           # UI styles (dark theme)
│   └── app.js              # Frontend JavaScript
├── generated_pdfs/         # Output directory for PDFs
├── requirements.txt        # Python dependencies
├── .env                    # API key configuration (create this)
└── README.md
```

## Tech Stack

- **Backend**: Python, FastAPI, Uvicorn
- **AI**: OpenAI GPT-4
- **PDF**: ReportLab
- **Frontend**: Vanilla HTML/CSS/JS
- **Fonts**: Inter (Google Fonts), Font Awesome icons
