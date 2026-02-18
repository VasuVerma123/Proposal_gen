import React, { useState, useRef, useEffect } from "react";
import axios from "axios";
import "./App.css";

const API = "http://localhost:8000";

export default function App() {
  // ── State ──────────────────────────────────────────────
  const [messages, setMessages] = useState([
    {
      role: "assistant",
      content:
        "Hello! I'm **ProposalBot**. I can help you create professional business proposals.\n\nTell me what you need — for example:\n> *\"Create a proposal for the telecom industry\"*\n\nI'll search our knowledge base for matching templates and generate a styled preview for you.",
    },
  ]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [previewHtml, setPreviewHtml] = useState(null);
  const [toolsUsed, setToolsUsed] = useState([]);
  const [neo4jOk, setNeo4jOk] = useState(null);
  const [showUpload, setShowUpload] = useState(false);
  const [kbDocs, setKbDocs] = useState(null);
  const [showSettings, setShowSettings] = useState(false);
  const [apiKeyInput, setApiKeyInput] = useState("");
  const [keyStatus, setKeyStatus] = useState(null);

  const chatEndRef = useRef(null);
  const iframeRef = useRef(null);

  // ── Auto-scroll chat ───────────────────────────────────
  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // ── Check Neo4j + key status on mount ───────────────────
  useEffect(() => {
    axios.get(`${API}/api/neo4j-status`).then((r) => setNeo4jOk(r.data.connected)).catch(() => setNeo4jOk(false));
    axios.get(`${API}/api/key-status`).then((r) => setKeyStatus(r.data)).catch(() => {});
  }, []);

  const saveApiKey = async () => {
    if (!apiKeyInput.trim()) return;
    try {
      const r = await axios.post(`${API}/api/set-key`, { api_key: apiKeyInput.trim() });
      setKeyStatus({ has_key: true, masked: r.data.masked });
      setShowSettings(false);
      setApiKeyInput("");
    } catch (err) {
      alert("Failed to set key: " + (err.response?.data?.detail || err.message));
    }
  };

  // ── Send message ───────────────────────────────────────
  const send = async () => {
    const text = input.trim();
    if (!text || loading) return;

    setMessages((prev) => [...prev, { role: "user", content: text }]);
    setInput("");
    setLoading(true);

    try {
      const res = await axios.post(`${API}/api/chat`, {
        message: text,
        session_id: "default",
      });

      const { reply, preview_html, tool_calls } = res.data;

      setMessages((prev) => [...prev, { role: "assistant", content: reply }]);

      if (preview_html) {
        setPreviewHtml(preview_html);
      }

      if (tool_calls && tool_calls.length > 0) {
        setToolsUsed(tool_calls);
      }
    } catch (err) {
      const errMsg =
        err.response?.data?.detail || err.message || "Something went wrong";
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: `**Error:** ${errMsg}` },
      ]);
    } finally {
      setLoading(false);
    }
  };

  const handleKey = (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  };

  // ── Reset conversation ─────────────────────────────────
  const resetChat = async () => {
    await axios.post(`${API}/api/reset?session_id=default`);
    setMessages([
      {
        role: "assistant",
        content: "Conversation reset. How can I help you with a new proposal?",
      },
    ]);
    setPreviewHtml(null);
    setToolsUsed([]);
  };

  // ── Load KB docs ───────────────────────────────────────
  const loadDocs = async () => {
    try {
      const r = await axios.get(`${API}/api/documents`);
      setKbDocs(r.data);
    } catch {
      setKbDocs({ proposals: [], rfps: [], assets: [], error: "Failed to load" });
    }
  };

  // ── Upload PDF ─────────────────────────────────────────
  const uploadPdf = async (type) => {
    const fileInput = document.createElement("input");
    fileInput.type = "file";
    fileInput.accept = ".pdf";
    fileInput.onchange = async (e) => {
      const file = e.target.files[0];
      if (!file) return;
      const sector = prompt("Enter sector (e.g. Telecom, Banking):", "General");
      const company = prompt("Enter company name:", "");
      const fd = new FormData();
      fd.append("file", file);
      fd.append("sector", sector || "General");
      fd.append("company", company || "");
      if (type === "proposal") {
        const sentTo = prompt("Sent to (client name):", "");
        fd.append("sent_to", sentTo || "");
      }
      try {
        await axios.post(`${API}/api/ingest/${type}`, fd);
        alert(`${type} uploaded successfully!`);
        loadDocs();
      } catch (err) {
        alert(`Upload failed: ${err.message}`);
      }
    };
    fileInput.click();
  };

  // ── Render markdown-ish text ───────────────────────────
  const renderText = (text) => {
    if (!text) return null;
    // Basic markdown: **bold**, *italic*, > blockquote, newlines
    const lines = text.split("\n");
    return lines.map((line, i) => {
      let html = line
        .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
        .replace(/\*(.+?)\*/g, "<em>$1</em>")
        .replace(/`(.+?)`/g, "<code>$1</code>");

      if (line.startsWith("> ")) {
        html = `<blockquote>${html.slice(2)}</blockquote>`;
      }
      if (line.startsWith("- ") || line.startsWith("* ")) {
        html = `<li>${html.slice(2)}</li>`;
      }

      return (
        <span
          key={i}
          dangerouslySetInnerHTML={{ __html: html }}
          style={{ display: "block", minHeight: line === "" ? "8px" : "auto" }}
        />
      );
    });
  };

  // ── Write HTML into iframe ─────────────────────────────
  useEffect(() => {
    if (iframeRef.current && previewHtml) {
      const doc = iframeRef.current.contentDocument;
      doc.open();
      doc.write(previewHtml);
      doc.close();
    }
  }, [previewHtml]);

  // ── Render ─────────────────────────────────────────────
  return (
    <div className="app">
      {/* ── LEFT: Chat Panel ─────────────────────────────── */}
      <div className="chat-panel">
        <div className="chat-header">
          <div className="chat-title">
            <span className="logo-icon">&#9672;</span>
            ProposalBot
          </div>
          <div className="header-actions">
            <span
              className={`status-dot ${neo4jOk ? "green" : "red"}`}
              title={neo4jOk ? "Neo4j connected" : "Neo4j disconnected"}
            />
            <button className="btn-icon" onClick={() => { setShowUpload(!showUpload); if (!kbDocs) loadDocs(); }} title="Knowledge Base">
              &#128218;
            </button>
            <button className="btn-icon" onClick={() => setShowSettings(true)} title="Settings">
              &#9881;
            </button>
            <button className="btn-icon" onClick={resetChat} title="New Chat">
              &#x21bb;
            </button>
          </div>
        </div>

        {/* Upload / KB panel */}
        {showUpload && (
          <div className="kb-panel">
            <div className="kb-actions">
              <button onClick={() => uploadPdf("proposal")}>+ Proposal PDF</button>
              <button onClick={() => uploadPdf("rfp")}>+ RFP PDF</button>
              <button onClick={() => uploadPdf("asset")}>+ Asset PDF</button>
              <button onClick={loadDocs} className="btn-refresh">&#x21bb; Refresh</button>
            </div>
            {kbDocs && (
              <div className="kb-list">
                <div className="kb-section">
                  <strong>Proposals ({kbDocs.proposals?.length || 0})</strong>
                  {kbDocs.proposals?.map((d) => (
                    <div key={d.id} className="kb-item">
                      {d.id} &middot; {d.sector} &middot; {d.chunks} chunks
                    </div>
                  ))}
                </div>
                <div className="kb-section">
                  <strong>RFPs ({kbDocs.rfps?.length || 0})</strong>
                  {kbDocs.rfps?.map((d) => (
                    <div key={d.id} className="kb-item">
                      {d.id} &middot; {d.sector} &middot; {d.chunks} chunks
                    </div>
                  ))}
                </div>
                <div className="kb-section">
                  <strong>Assets ({kbDocs.assets?.length || 0})</strong>
                  {kbDocs.assets?.map((d) => (
                    <div key={d.id} className="kb-item">
                      {d.id} &middot; {d.sector} &middot; {d.chunks} chunks
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        {/* Messages */}
        <div className="chat-messages">
          {messages.map((msg, i) => (
            <div key={i} className={`msg ${msg.role}`}>
              <div className="msg-avatar">
                {msg.role === "user" ? "U" : "P"}
              </div>
              <div className="msg-body">{renderText(msg.content)}</div>
            </div>
          ))}
          {loading && (
            <div className="msg assistant">
              <div className="msg-avatar">P</div>
              <div className="msg-body typing">
                <span></span><span></span><span></span>
              </div>
            </div>
          )}
          <div ref={chatEndRef} />
        </div>

        {/* Tools used indicator */}
        {toolsUsed.length > 0 && (
          <div className="tools-bar">
            Tools used: {toolsUsed.map((t, i) => (
              <span key={i} className="tool-chip">{t}</span>
            ))}
          </div>
        )}

        {/* Input */}
        <div className="chat-input-area">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKey}
            placeholder="Describe the proposal you need..."
            rows={2}
            disabled={loading}
          />
          <button className="send-btn" onClick={send} disabled={loading || !input.trim()}>
            {loading ? "..." : "Send"}
          </button>
        </div>
      </div>

      {/* ── RIGHT: Preview Panel ─────────────────────────── */}
      <div className="preview-panel">
        <div className="preview-header">
          <span>Proposal Preview</span>
          {previewHtml && (
            <button
              className="btn-icon"
              onClick={() => {
                const w = window.open("", "_blank");
                w.document.write(previewHtml);
                w.document.close();
              }}
              title="Open in new tab"
            >
              &#8599;
            </button>
          )}
        </div>
        <div className="preview-content">
          {previewHtml ? (
            <iframe
              ref={iframeRef}
              title="Proposal Preview"
              className="preview-iframe"
            />
          ) : (
            <div className="preview-placeholder">
              <div className="placeholder-icon">&#128196;</div>
              <h3>No proposal yet</h3>
              <p>
                Start chatting on the left to generate a proposal.
                <br />
                The live preview will appear here as it's generated.
              </p>
            </div>
          )}
        </div>
      </div>

      {/* ── Settings Modal ───────────────────────────────── */}
      {showSettings && (
        <div className="modal-overlay" onClick={() => setShowSettings(false)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h3>Settings</h3>
            <div className="modal-field">
              <label>OpenAI API Key</label>
              {keyStatus?.has_key && (
                <div className="key-badge">Current: {keyStatus.masked}</div>
              )}
              <input
                type="password"
                value={apiKeyInput}
                onChange={(e) => setApiKeyInput(e.target.value)}
                placeholder="sk-proj-..."
              />
              <button className="modal-btn" onClick={saveApiKey}>
                Save Key
              </button>
            </div>
            <div className="modal-field">
              <label>Neo4j Status</label>
              <div className="key-badge">
                {neo4jOk ? "Connected" : "Disconnected"}
              </div>
            </div>
            <button className="modal-close" onClick={() => setShowSettings(false)}>
              Close
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
