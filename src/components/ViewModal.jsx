import React from "react";
import { X, FileText, Loader2, KeyRound } from "lucide-react";
import { C, categoryInfo, ClassificationBadge, maskSensitive } from "./SmallComponents";

export default function ViewModal({ doc, onClose, loading }) {
  if (!doc) return null;
  const cat = categoryInfo(doc.category);
  
  return (
    <div className="aegis-modal-overlay">
      <div className="aegis-modal-content aegis-scroll" style={{ maxWidth: "600px", maxHeight: "85vh", overflowY: "auto", background: "rgba(15, 23, 42, 0.75)" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "14px" }}>
          <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
            <div
              style={{
                width: "40px",
                height: "40px",
                borderRadius: "8px",
                background: "rgba(6, 182, 212, 0.06)",
                border: "1px solid rgba(6, 182, 212, 0.25)",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
              }}
            >
              <FileText size={18} color={C.teal} />
            </div>
            <div>
              <div className="aegis-display" style={{ fontSize: "16px", fontWeight: 700, color: C.text }}>
                {doc.name}
              </div>
              <div className="aegis-mono" style={{ fontSize: "11px", color: C.muted, marginTop: "2px" }}>
                {doc.id} {doc.date ? ` · Ingested ${doc.date}` : ""} {doc.size ? ` · Size: ${doc.size}` : ""}
              </div>
            </div>
          </div>
          <button
            onClick={onClose}
            className="aegis-btn"
            style={{ padding: "6px", background: "transparent", border: "none", color: C.muted }}
          >
            <X size={18} />
          </button>
        </div>

        <div style={{ display: "flex", gap: "8px", marginBottom: "18px" }}>
          <ClassificationBadge classification={cat.classification} />
          <span
            className="aegis-mono"
            style={{
              fontSize: "10px",
              padding: "3px 8px",
              borderRadius: "6px",
              border: `1px solid rgba(255, 255, 255, 0.06)`,
              color: C.muted,
              background: "rgba(255, 255, 255, 0.02)",
              fontWeight: 600,
            }}
          >
            {cat.label.toUpperCase()}
          </span>
        </div>

        {loading ? (
          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              gap: "10px",
              color: C.muted,
              fontSize: "13px",
              padding: "40px 0",
              background: "rgba(0, 0, 0, 0.2)",
              borderRadius: "10px",
              border: `1px solid rgba(255, 255, 255, 0.04)`,
            }}
          >
            <Loader2 size={16} className="aegis-spin" color={C.gold} /> Parsing index contents…
          </div>
        ) : (
          <div
            className="aegis-scroll"
            style={{
              fontSize: "13.5px",
              lineHeight: 1.7,
              background: "rgba(0, 0, 0, 0.25)",
              border: `1px solid rgba(255, 255, 255, 0.06)`,
              borderRadius: "10px",
              padding: "16px",
              whiteSpace: "pre-wrap",
              wordBreak: "break-word",
              color: C.text,
              maxHeight: "420px",
              overflowY: "auto",
            }}
          >
            {maskSensitive(doc.content || "No text description available.")}
          </div>
        )}

        <div
          style={{
            marginTop: "16px",
            display: "flex",
            alignItems: "center",
            gap: "8px",
            fontSize: "11px",
            color: C.muted,
            borderTop: `1px solid rgba(255, 255, 255, 0.06)`,
            paddingTop: "14px",
          }}
        >
          <KeyRound size={13} color={C.gold} />
          <span>Security Notice: Sensitive database fields (passwords, tokens, PII) are dynamically masked.</span>
        </div>
      </div>
    </div>
  );
}
