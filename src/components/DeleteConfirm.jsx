import React from "react";
import { AlertTriangle, Loader2 } from "lucide-react";
import { C } from "./SmallComponents";

export default function DeleteConfirm({ doc, onClose, onConfirm, busy }) {
  if (!doc) return null;
  
  return (
    <div className="aegis-modal-overlay">
      <div className="aegis-modal-content" style={{ maxWidth: "420px", background: "rgba(15, 23, 42, 0.75)" }}>
        <div style={{ display: "flex", alignItems: "center", gap: "12px", marginBottom: "14px" }}>
          <div
            style={{
              width: "36px",
              height: "36px",
              borderRadius: "8px",
              background: "rgba(244, 63, 94, 0.06)",
              border: "1px solid rgba(244, 63, 94, 0.25)",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
            }}
          >
            <AlertTriangle size={16} color={C.danger} />
          </div>
          <h3 className="aegis-display" style={{ margin: 0, fontSize: "16px", fontWeight: 700, color: C.text }}>
            Remove from Ingestion Index?
          </h3>
        </div>

        <p style={{ fontSize: "13px", color: C.muted, marginBottom: "20px", lineHeight: "1.55" }}>
          The document <span className="aegis-mono" style={{ color: C.text, fontWeight: 600, wordBreak: "break-all" }}>{doc.name}</span> will be permanently removed from local filesystem directories and all parsed search vector chunks will be flushed from the database. This action is irreversible.
        </p>

        <div
          style={{
            display: "flex",
            justifyContent: "flex-end",
            gap: "10px",
            borderTop: `1px solid rgba(255, 255, 255, 0.06)`,
            paddingTop: "16px",
          }}
        >
          <button
            onClick={onClose}
            className="aegis-btn"
            style={{ color: C.muted, background: "transparent", borderColor: "transparent" }}
          >
            Cancel
          </button>
          <button
            disabled={busy}
            onClick={onConfirm}
            className="aegis-btn aegis-btn-danger"
            style={{ borderRadius: "10px" }}
          >
            {busy ? (
              <>
                <Loader2 size={14} className="aegis-spin" /> Purging Index…
              </>
            ) : (
              "Purge Document"
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
