import React from "react";
import { AlertTriangle, LogOut, Shield } from "lucide-react";
import { C } from "./SmallComponents";

export default function UnprovisionedScreen({ username, onLogout }) {
  return (
    <div
      style={{
        minHeight: "100vh",
        background: C.bg,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: "24px",
        position: "relative",
        overflow: "hidden",
      }}
    >
      {/* Background neon glow spots for glassmorphic contrast */}
      <div
        style={{
          position: "absolute",
          width: "400px",
          height: "400px",
          background: "radial-gradient(circle, rgba(245, 158, 11, 0.08) 0%, transparent 70%)",
          top: "20%",
          left: "20%",
          pointerEvents: "none",
          zIndex: 1,
        }}
      />
      
      <div style={{ width: "100%", maxWidth: "460px", zIndex: 10 }} className="aegis-fade-in">
        {/* Branding header */}
        <div style={{ textAlign: "center", marginBottom: "28px" }}>
          <div
            style={{
              display: "inline-flex",
              alignItems: "center",
              justifyContent: "center",
              width: "64px",
              height: "64px",
              borderRadius: "18px",
              background: `rgba(245, 158, 11, 0.06)`,
              border: `1px solid rgba(245, 158, 11, 0.25)`,
              marginBottom: "16px",
              boxShadow: "0 8px 24px rgba(245, 158, 11, 0.08)",
            }}
          >
            <Shield size={28} color={C.gold} className="aegis-glow-pulse" />
          </div>
          <h1 className="aegis-display" style={{ fontSize: "30px", fontWeight: 700, margin: 0, letterSpacing: "0.06em", color: C.text }}>
            AEGIS
          </h1>
          <p style={{ color: C.muted, fontSize: "12.5px", marginTop: "4px", fontWeight: 500, letterSpacing: "0.02em" }}>
            Enterprise Intelligence Console
          </p>
        </div>

        {/* Info card */}
        <div
          className="aegis-glass-panel"
          style={{
            padding: "32px",
            border: `1px solid rgba(255, 255, 255, 0.06)`,
            background: "rgba(15, 23, 42, 0.35)",
            backdropFilter: "blur(20px)",
            WebkitBackdropFilter: "blur(20px)",
            borderRadius: "16px",
            boxShadow: "0 20px 40px rgba(0, 0, 0, 0.4)",
            textAlign: "center",
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            gap: "20px",
          }}
        >
          <div
            style={{
              width: "48px",
              height: "48px",
              borderRadius: "50%",
              background: "rgba(245, 158, 11, 0.1)",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              border: `1px solid rgba(245, 158, 11, 0.2)`,
            }}
          >
            <AlertTriangle size={22} color={C.gold} />
          </div>

          <div>
            <h2
              className="aegis-display"
              style={{
                fontSize: "19px",
                fontWeight: 700,
                color: C.text,
                margin: "0 0 10px 0",
              }}
            >
              Account Pending Setup
            </h2>
            <p
              style={{
                fontSize: "13.5px",
                color: C.muted,
                lineHeight: "1.6",
                margin: 0,
              }}
            >
              Your account (<strong>{username}</strong>) has been successfully authenticated, but it is not linked to any organization yet.
            </p>
          </div>

          <div
            style={{
              width: "100%",
              height: "1px",
              background: `linear-gradient(to right, transparent, rgba(255, 255, 255, 0.08), transparent)`,
            }}
          />

          <p
            style={{
              fontSize: "12.5px",
              color: C.muted,
              margin: 0,
              lineHeight: "1.5",
            }}
          >
            Please contact your system administrator to assign your profile to an organization tenant before proceeding.
          </p>

          <button
            onClick={onLogout}
            className="aegis-btn"
            style={{
              marginTop: "8px",
              display: "flex",
              alignItems: "center",
              gap: "8px",
              padding: "10px 20px",
              borderRadius: "10px",
              border: `1px solid rgba(255, 255, 255, 0.08)`,
              background: "rgba(255, 255, 255, 0.04)",
              color: C.text,
              cursor: "pointer",
              fontSize: "13px",
              fontWeight: 600,
              transition: "all 0.2s ease",
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.background = "rgba(255, 255, 255, 0.08)";
              e.currentTarget.style.border = `1px solid rgba(255, 255, 255, 0.15)`;
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.background = "rgba(255, 255, 255, 0.04)";
              e.currentTarget.style.border = `1px solid rgba(255, 255, 255, 0.08)`;
            }}
          >
            <LogOut size={14} />
            Sign out
          </button>
        </div>
      </div>
    </div>
  );
}
