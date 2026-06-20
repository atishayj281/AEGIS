import React, { useState, useEffect, useRef } from "react";
import { Search, Plus, Eye, Trash2, AlertTriangle, Loader2, FileSearch, Lock } from "lucide-react";
import { C, ROLES, CATEGORIES, categoryInfo, ClassificationBadge } from "./SmallComponents";
import UploadModal from "./UploadModal";
import ViewModal from "./ViewModal";
import DeleteConfirm from "./DeleteConfirm";

const fallbackApiClient = {
  listDocuments: async (apiBase, token) => {
    const res = await fetch(`${apiBase}/api/v1/documents`, {
      headers: { Authorization: `Bearer ${token}` }
    });
    if (!res.ok) throw new Error("Failed to load documents");
    return res.json();
  },
  getDocument: async (apiBase, token, filename) => {
    const res = await fetch(`${apiBase}/api/v1/documents/${filename}`, {
      headers: { Authorization: `Bearer ${token}` }
    });
    if (!res.ok) throw new Error("Failed to get document");
    return res.json();
  },
  deleteDocument: async (apiBase, token, filename) => {
    const res = await fetch(`${apiBase}/api/v1/documents/${filename}`, {
      method: "DELETE",
      headers: { Authorization: `Bearer ${token}` }
    });
    if (!res.ok) throw new Error("Failed to delete document");
    return res.json();
  },
  uploadDocument: async (apiBase, token, formData) => {
    const res = await fetch(`${apiBase}/api/v1/document/upload`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
      body: formData
    });
    if (!res.ok) throw new Error("Failed to upload document");
    return res.json();
  }
};

export default function DocumentVault({
  live,
  apiBase,
  token,
  roleKey,
  documents,
  setDocuments,
  onAuditEntry,
  onSessionExpired,
  apiClient = fallbackApiClient,
  normalizeDocumentHelper = (d) => d
}) {
  const role = ROLES[roleKey] || ROLES.employee;
  const isAdmin = roleKey === "admin";
  
  const [filter, setFilter] = useState("all");
  const [search, setSearch] = useState("");
  
  const [showUpload, setShowUpload] = useState(false);
  const [viewDoc, setViewDoc] = useState(null);
  const [deleteDoc, setDeleteDoc] = useState(null);
  
  const [loading, setLoading] = useState(live);
  const [loadingDoc, setLoadingDoc] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  // Stable refs so effect deps don't change on every parent render
  const apiClientRef = useRef(apiClient);
  const normalizeRef = useRef(normalizeDocumentHelper);
  const onSessionExpiredRef = useRef(onSessionExpired);
  const setDocumentsRef = useRef(setDocuments);
  apiClientRef.current = apiClient;
  normalizeRef.current = normalizeDocumentHelper;
  onSessionExpiredRef.current = onSessionExpired;
  setDocumentsRef.current = setDocuments;

  // Load documents from live API or use local simulation documents
  // Depends only on live/apiBase/token — never on function identity
  useEffect(() => {
    if (!live) {
      setLoading(false);
      return;
    }
    
    let cancelled = false;
    setLoading(true);
    setError(null);
    
    apiClientRef.current.listDocuments(apiBase, token)
      .then((data) => {
        if (cancelled) return;
        const list = Array.isArray(data) ? data : data.documents || data.items || [];
        setDocumentsRef.current(list.map((d, idx) => normalizeRef.current(d, idx)));
      })
      .catch((err) => {
        if (cancelled) return;
        if (err.status === 401) {
          onSessionExpiredRef.current();
          return;
        }
        setError(err.message || "Failed to load documents from backend.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
      
    return () => {
      cancelled = true;
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [live, apiBase, token]);

  // Determine categories to show in filter list
  const categoryOptions = live ? Object.keys(CATEGORIES) : role.categories;

  // Filter and search
  const visibleDocs = documents
    .filter((d) => live || role.categories.includes(d.category))
    .filter((d) => filter === "all" || d.category === filter)
    .filter((d) => d.name.toLowerCase().includes(search.toLowerCase()));

  // Ingestion submit handler
  const handleCreate = async (payload) => {
    setBusy(true);
    setError(null);
    
    if (!live) {
      // Simulate raw or file upload locally
      const id = `DOC-${100 + documents.length + 1}`;
      const sizeStr = payload.file ? `${(payload.file.size / 1024).toFixed(0)} KB` : "4 KB";
      const doc = {
        id,
        name: payload.name,
        category: payload.category,
        date: new Date().toISOString().slice(0, 10),
        size: sizeStr,
        content: payload.content || "Uploaded simulation document content."
      };
      
      setDocuments((prev) => [doc, ...prev]);
      onAuditEntry({
        user: role.label,
        role: roleKey,
        query: `Ingested local file: "${payload.name}"`,
        result: "ALLOWED",
        source: payload.name
      });
      setShowUpload(false);
      setBusy(false);
      return;
    }

    try {
      const formData = new FormData();
      if (payload.isRawText) {
        // Raw text paste - convert to text Blob/File to match backend Form/UploadFile parameter
        const blob = new Blob([payload.content], { type: "text/plain" });
        const file = new File([blob], payload.name, { type: "text/plain" });
        formData.append("file", file);
      } else {
        formData.append("file", payload.file);
      }
      formData.append("data_source", payload.category);
      await apiClient.uploadDocument(apiBase, token, formData);
      
      // Successfully uploaded! Trigger reloading document list
      const listData = await apiClient.listDocuments(apiBase, token);
      const list = Array.isArray(listData) ? listData : listData.documents || listData.items || [];
      setDocuments(list.map((d, idx) => normalizeDocumentHelper(d, idx)));
      
      onAuditEntry({
        user: role.label,
        role: roleKey,
        query: `Ingested server document: "${payload.name}"`,
        result: "ALLOWED",
        source: payload.name
      });
      
      setShowUpload(false);
    } catch (err) {
      if (err.status === 401) {
        onSessionExpired();
        return;
      }
      setError(err.message || "Failed to ingest document to backend.");
    } finally {
      setBusy(false);
    }
  };

  // Preview details click handler
  const handleView = async (doc) => {
    setViewDoc(doc);
    if (!live) return;
    
    setLoadingDoc(true);
    try {
      const full = await apiClient.getDocument(apiBase, token, doc.id);
      setViewDoc(normalizeDocumentHelper(full, 0));
    } catch (err) {
      if (err.status === 401) {
        onSessionExpired();
        return;
      }
      setError(err.message || "Failed to retrieve full document contents.");
    } finally {
      setLoadingDoc(false);
    }
  };

  // Deletion confirm handler
  const handleDelete = async () => {
    setBusy(true);
    setError(null);
    
    if (!live) {
      setDocuments((prev) => prev.filter((d) => d.id !== deleteDoc.id));
      onAuditEntry({
        user: role.label,
        role: roleKey,
        query: `Deleted local file: "${deleteDoc.name}"`,
        result: "ALLOWED",
        source: deleteDoc.name
      });
      setDeleteDoc(null);
      setBusy(false);
      return;
    }

    try {
      await apiClient.deleteDocument(apiBase, token, deleteDoc.id);
      setDocuments((prev) => prev.filter((d) => d.id !== deleteDoc.id));
      onAuditEntry({
        user: role.label,
        role: roleKey,
        query: `Deleted server file: "${deleteDoc.name}"`,
        result: "ALLOWED",
        source: deleteDoc.name
      });
      setDeleteDoc(null);
    } catch (err) {
      if (err.status === 401) {
        onSessionExpired();
        return;
      }
      setError(err.message || "Failed to delete file from backend index.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div style={{ height: "100%", display: "flex", flexDirection: "column" }} className="aegis-fade-in">
      {/* Header controls bar */}
      <div style={{ padding: "20px 24px 0 24px" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: "12px", marginBottom: "16px" }}>
          <div>
            <h2 className="aegis-display" style={{ margin: 0, fontSize: "20px", fontWeight: 700 }}>
              Ingested Document Vault
            </h2>
            <p style={{ margin: "4px 0 0", fontSize: "12px", color: C.muted }}>
              {loading ? "Catalog loading…" : `${visibleDocs.length} active files registered in search index`}
            </p>
          </div>
          <button
            onClick={() => setShowUpload(true)}
            className="aegis-btn aegis-btn-primary"
            style={{ padding: "10px 18px" }}
          >
            <Plus size={15} /> Ingest Document
          </button>
        </div>

        {error && (
          <div
            style={{
              display: "flex",
              gap: "8px",
              background: "rgba(239, 68, 68, 0.08)",
              border: `1px solid rgba(239, 68, 68, 0.3)`,
              borderRadius: "8px",
              padding: "10px 12px",
              marginBottom: "16px",
              fontSize: "12.5px",
              color: C.danger,
            }}
          >
            <AlertTriangle size={15} style={{ flexShrink: 0, marginTop: "1px" }} />
            <span>{error}</span>
          </div>
        )}

        {/* Search and Filters grid */}
        <div style={{ display: "flex", gap: "10px", flexWrap: "wrap", marginBottom: "16px" }}>
          <div style={{ position: "relative", flex: "1 1 240px" }}>
            <Search size={14} color={C.muted} style={{ position: "absolute", left: "12px", top: "12px" }} />
            <input
              className="aegis-input"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search index database by file name..."
              style={{ padding: "9px 12px 9px 34px" }}
            />
          </div>
          <div style={{ display: "flex", gap: "6px", flexWrap: "wrap", alignItems: "center" }}>
            <button
              onClick={() => setFilter("all")}
              className="aegis-btn"
              style={{
                padding: "8px 12px",
                borderRadius: "20px",
                fontSize: "11.5px",
                borderColor: filter === "all" ? "rgba(226, 184, 87, 0.4)" : C.border,
                background: filter === "all" ? "rgba(226, 184, 87, 0.08)" : "transparent",
                color: filter === "all" ? C.gold : C.muted,
              }}
            >
              All Sources
            </button>
            {categoryOptions.map((c) => (
              <button
                key={c}
                onClick={() => setFilter(c)}
                className="aegis-btn"
                style={{
                  padding: "8px 12px",
                  borderRadius: "20px",
                  fontSize: "11.5px",
                  borderColor: filter === c ? "rgba(226, 184, 87, 0.4)" : C.border,
                  background: filter === c ? "rgba(226, 184, 87, 0.08)" : "transparent",
                  color: filter === c ? C.gold : C.muted,
                }}
              >
                {categoryInfo(c).label}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Grid List Table */}
      <div className="aegis-scroll" style={{ flex: 1, overflowY: "auto", padding: "0 24px 24px 24px" }}>
        {loading ? (
          <div style={{ display: "flex", alignItems: "center", gap: "10px", color: C.muted, fontSize: "13.5px", marginTop: "40px", justifyContent: "center" }}>
            <Loader2 size={16} className="aegis-spin" /> Querying active registry catalog…
          </div>
        ) : visibleDocs.length === 0 ? (
          <div style={{ textAlign: "center", color: C.muted, marginTop: "60px", padding: "20px" }}>
            <FileSearch size={32} style={{ marginBottom: "12px", opacity: 0.5 }} />
            <div style={{ fontSize: "13.5px" }}>No document registry records match filters for your role clearance.</div>
          </div>
        ) : (
          <div className="aegis-table-container">
            <div
              className="aegis-table-header"
              style={{
                display: "grid",
                gridTemplateColumns: "1.5fr 1.2fr 1fr 100px 90px 100px",
                padding: "12px 16px",
                fontSize: "11px",
                color: C.muted,
                fontWeight: 600,
                letterSpacing: "0.05em",
              }}
            >
              <div>FILE NAME</div>
              <div>DATA SOURCE</div>
              <div>CLASSIFICATION</div>
              <div>INGESTED</div>
              <div>SIZE</div>
              <div style={{ textAlign: "right" }}>ACTIONS</div>
            </div>
            
            {visibleDocs.map((d) => {
              const cat = categoryInfo(d.category);
              const Icon = cat.icon;
              return (
                <div
                  key={d.id}
                  className="aegis-row"
                  style={{
                    display: "grid",
                    gridTemplateColumns: "1.5fr 1.2fr 1fr 100px 90px 100px",
                    padding: "12px 16px",
                    borderTop: `1px solid ${C.borderSoft}`,
                    fontSize: "13px",
                    alignItems: "center",
                  }}
                >
                  <div style={{ display: "flex", alignItems: "center", gap: "10px", minWidth: 0 }}>
                    <div style={{ color: C.teal, display: "flex", flexShrink: 0 }}>
                      <Icon size={16} />
                    </div>
                    <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", color: C.text, fontWeight: 500 }}>
                      {d.name}
                    </span>
                  </div>
                  <div style={{ color: C.muted }}>{cat.label}</div>
                  <div>
                    <ClassificationBadge classification={cat.classification} />
                  </div>
                  <div className="aegis-mono" style={{ color: C.muted, fontSize: "11.5px" }}>
                    {d.date || "—"}
                  </div>
                  <div className="aegis-mono" style={{ color: C.muted, fontSize: "11.5px" }}>
                    {d.size || "—"}
                  </div>
                  
                  {/* Actions buttons */}
                  <div style={{ display: "flex", justifyContent: "flex-end", gap: "6px" }}>
                    <button
                      onClick={() => handleView(d)}
                      title="View contents"
                      className="aegis-btn"
                      style={{
                        padding: "6px",
                        background: "transparent",
                        borderColor: C.border,
                        borderRadius: "8px",
                        color: C.muted,
                      }}
                    >
                      <Eye size={13} />
                    </button>
                    
                    <button
                      onClick={() => setDeleteDoc(d)}
                      disabled={!isAdmin}
                      title={isAdmin ? "Delete document" : "Requires Admin privileges"}
                      className="aegis-btn"
                      style={{
                        padding: "6px",
                        background: "transparent",
                        borderColor: C.border,
                        borderRadius: "8px",
                        color: isAdmin ? C.danger : C.dark,
                        cursor: isAdmin ? "pointer" : "not-allowed",
                      }}
                    >
                      {isAdmin ? <Trash2 size={13} /> : <Lock size={12} />}
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* Modals rendering */}
      {showUpload && (
        <UploadModal
          onClose={() => setShowUpload(false)}
          onCreate={handleCreate}
          allowedCategories={categoryOptions}
          busy={busy}
        />
      )}
      {viewDoc && (
        <ViewModal
          doc={viewDoc}
          onClose={() => setViewDoc(null)}
          loading={loadingDoc}
        />
      )}
      {deleteDoc && (
        <DeleteConfirm
          doc={deleteDoc}
          onClose={() => setDeleteDoc(null)}
          onConfirm={handleDelete}
          busy={busy}
        />
      )}
    </div>
  );
}
