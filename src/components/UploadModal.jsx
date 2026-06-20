import React, { useState, useRef } from "react";
import { Upload, X, FileText, ClipboardList, Loader2, AlertTriangle } from "lucide-react";
import { C, categoryInfo } from "./SmallComponents";

export default function UploadModal({ onClose, onCreate, allowedCategories, busy }) {
  const [tab, setTab] = useState("file"); // 'file' | 'text'
  const [category, setCategory] = useState(allowedCategories[0] || "public_policies");

  // File upload state
  const [selectedFile, setSelectedFile] = useState(null);
  const [dragActive, setDragActive] = useState(false);
  const fileInputRef = useRef(null);

  // Text editor state
  const [textName, setTextName] = useState("");
  const [textContent, setTextContent] = useState("");

  const [error, setError] = useState(null);

  const handleDrag = (e) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.type === "dragenter" || e.type === "dragover") setDragActive(true);
    else if (e.type === "dragleave") setDragActive(false);
  };

  const handleDrop = (e) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(false);
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      validateAndSetFile(e.dataTransfer.files[0]);
    }
  };

  const handleFileChange = (e) => {
    if (e.target.files && e.target.files[0]) validateAndSetFile(e.target.files[0]);
  };

  const validateAndSetFile = (file) => {
    setError(null);
    const name = file.name.toLowerCase();
    const allowed = [".txt", ".pdf", ".docx", ".md", ".log", ".csv", ".xlsx", ".xls", ".json", ".png", ".jpg", ".jpeg"];
    if (!allowed.some((ext) => name.endsWith(ext))) {
      setError("Unsupported file type. Allowed: PDF, Word, Excel, CSV, JSON, TXT, Images.");
      return;
    }
    if (file.size > 10 * 1024 * 1024) {
      setError("File exceeds the 10 MB size limit.");
      return;
    }
    setSelectedFile(file);
    setTextName(file.name);
  };

  const handleSubmit = () => {
    setError(null);
    if (tab === "file") {
      if (!selectedFile) { setError("Please select a file."); return; }
      onCreate({ isRawText: false, file: selectedFile, category, name: selectedFile.name });
    } else {
      if (!textName.trim()) { setError("Please enter a file name."); return; }
      if (!textContent.trim()) { setError("Please enter document content."); return; }
      let filename = textName.trim();
      if (!filename.includes(".")) filename += ".txt";
      onCreate({ isRawText: true, name: filename, category, content: textContent.trim() });
    }
  };

  const canSubmit = tab === "file" ? !!selectedFile : (!!textName.trim() && !!textContent.trim());

  return (
    <div className="aegis-modal-overlay" onDragEnter={handleDrag}>
      <div className="aegis-modal-content" style={{ maxWidth: "520px" }}>
        {/* Header */}
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "20px" }}>
          <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
            <div style={{ width: "36px", height: "36px", borderRadius: "8px", background: "rgba(226,184,87,0.08)", border: "1px solid rgba(226,184,87,0.3)", display: "flex", alignItems: "center", justifyContent: "center" }}>
              <Upload size={18} color={C.gold} />
            </div>
            <h3 className="aegis-display" style={{ margin: 0, fontSize: "18px", color: C.text, fontWeight: 700 }}>
              Ingest Enterprise Data
            </h3>
          </div>
          <button onClick={onClose} className="aegis-btn" style={{ padding: "6px", background: "transparent", border: "none", color: C.muted }}>
            <X size={20} />
          </button>
        </div>

        {/* Tab selection */}
        <div style={{ display: "flex", gap: "4px", marginBottom: "18px", background: "rgba(6,9,14,0.4)", border: `1px solid ${C.border}`, borderRadius: "10px", padding: "3px" }}>
          {[{ key: "file", label: "Upload File", icon: Upload }, { key: "text", label: "Paste Text", icon: ClipboardList }].map((t) => {
            const Icon = t.icon;
            return (
              <button key={t.key} onClick={() => { setTab(t.key); setError(null); }} className="aegis-btn"
                style={{ flex: 1, padding: "8px 12px", borderRadius: "7px", border: "none", cursor: "pointer", fontSize: "12.5px", background: tab === t.key ? "var(--bg-panel-hover)" : "transparent", color: tab === t.key ? C.text : C.muted }}>
                <Icon size={13} /> {t.label}
              </button>
            );
          })}
        </div>

        {/* Error banner */}
        {error && (
          <div style={{ display: "flex", gap: "8px", background: "rgba(239,68,68,0.08)", border: "1px solid rgba(239,68,68,0.3)", borderRadius: "8px", padding: "10px 12px", marginBottom: "16px", fontSize: "12px", color: C.danger }}>
            <AlertTriangle size={15} style={{ flexShrink: 0, marginTop: "1px" }} /> {error}
          </div>
        )}

        {/* Tab content */}
        {tab === "file" ? (
          <div style={{ marginBottom: "20px" }}>
            <input type="file" ref={fileInputRef} onChange={handleFileChange} style={{ display: "none" }}
              accept=".txt,.pdf,.docx,.md,.log,.csv,.xlsx,.xls,.json,.png,.jpg,.jpeg" />
            <div className={`aegis-dropzone${dragActive ? " active" : ""}`}
              onDragEnter={handleDrag} onDragOver={handleDrag} onDragLeave={handleDrag} onDrop={handleDrop}
              onClick={() => fileInputRef.current.click()} style={{ minHeight: "150px", justifyContent: "center" }}>
              {selectedFile ? (
                <>
                  <FileText size={36} color={C.teal} />
                  <div style={{ fontWeight: 600, fontSize: "14px", color: C.text, wordBreak: "break-all" }}>{selectedFile.name}</div>
                  <div className="aegis-mono" style={{ fontSize: "11px", color: C.muted }}>
                    {(selectedFile.size / 1024).toFixed(0)} KB · Click to change
                  </div>
                </>
              ) : (
                <>
                  <Upload size={32} color={C.muted} style={{ opacity: 0.5 }} />
                  <div style={{ fontWeight: 500, fontSize: "13.5px", color: C.text }}>
                    Drag & Drop, or <span style={{ color: C.gold, textDecoration: "underline" }}>Browse</span>
                  </div>
                  <div style={{ fontSize: "11px", color: C.muted }}>PDF, Word, Excel, CSV, JSON, Images · Max 10 MB</div>
                </>
              )}
            </div>
          </div>
        ) : (
          <div style={{ marginBottom: "16px" }}>
            <label style={{ fontSize: "11.5px", color: C.muted, fontWeight: 500, display: "block", marginBottom: "4px" }}>Virtual File Name</label>
            <input className="aegis-input" type="text" value={textName} onChange={(e) => setTextName(e.target.value)}
              placeholder="e.g. policy_memo.txt" style={{ marginBottom: "14px" }} />
            <label style={{ fontSize: "11.5px", color: C.muted, fontWeight: 500, display: "block", marginBottom: "4px" }}>Document Content</label>
            <textarea className="aegis-textarea aegis-scroll" rows={6} value={textContent}
              onChange={(e) => setTextContent(e.target.value)}
              placeholder="Paste the document text to be parsed, chunked, and vectorized into the search index..."
              style={{ resize: "vertical", width: "100%" }} />
          </div>
        )}

        {/* Data source category */}
        <div style={{ marginBottom: "20px" }}>
          <label style={{ fontSize: "11.5px", color: C.muted, fontWeight: 500, display: "block", marginBottom: "6px" }}>RAG Target Data Source</label>
          <select className="aegis-select" value={category} onChange={(e) => setCategory(e.target.value)}>
            {allowedCategories.map((c) => (
              <option key={c} value={c}>{categoryInfo(c).label} [{categoryInfo(c).classification}]</option>
            ))}
          </select>
        </div>

        {/* Actions */}
        <div style={{ display: "flex", justifyContent: "flex-end", gap: "10px", borderTop: `1px solid ${C.borderSoft}`, paddingTop: "16px" }}>
          <button onClick={onClose} className="aegis-btn" style={{ color: C.muted, background: "transparent" }}>Cancel</button>
          <button disabled={busy || !canSubmit} onClick={handleSubmit} className="aegis-btn aegis-btn-primary">
            {busy ? <><Loader2 size={14} className="aegis-spin" /> Embedding…</> : <><Upload size={14} /> Add to Vault</>}
          </button>
        </div>
      </div>
    </div>
  );
}
