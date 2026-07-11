import React, { useState } from "react";
import { Shield, Lock, AlertTriangle, Loader2, ChevronRight, Sparkles } from "lucide-react";
import { C, ROLES } from "./SmallComponents";

export default function LoginScreen({ onLogin, onDemo, error, loading }) {
  const [tab, setTab] = useState("live"); // 'live' | 'demo'
  const [demoHover, setDemoHover] = useState(null);

  const demoUsersMap = {
    admin: "admin_user",
    team_lead: "team_lead",
    compliance_officer: "compliance_officer",
    finance_analyst: "finance_analyst",
    operations_engineer: "ops_engineer",
    employee: "employee_user",
  };

  const handleLoginSubmit = (e) => {
    e.preventDefault();
    onLogin();
  };

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
      <div style={{ position: "absolute", width: "400px", height: "400px", background: "radial-gradient(circle, rgba(99, 102, 241, 0.08) 0%, transparent 70%)", top: "15%", left: "15%", pointerEvents: "none", zIndex: 1 }} />
      <div style={{ position: "absolute", width: "450px", height: "450px", background: "radial-gradient(circle, rgba(245, 158, 11, 0.07) 0%, transparent 70%)", bottom: "10%", right: "15%", pointerEvents: "none", zIndex: 1 }} />

      <div style={{ width: "100%", maxWidth: "440px", zIndex: 10 }} className="aegis-fade-in">
        
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

        {/* Tab Selection */}
        <div
          style={{
            display: "flex",
            gap: "4px",
            marginBottom: "20px",
            background: "rgba(255, 255, 255, 0.02)",
            border: `1px solid rgba(255, 255, 255, 0.06)`,
            borderRadius: "12px",
            padding: "4px",
            backdropFilter: "blur(8px)",
            WebkitBackdropFilter: "blur(8px)",
          }}
        >
          {[
            { key: "live", label: "Live Server API" },
            { key: "demo", label: "Sandbox Simulator" },
          ].map((t) => (
            <button
              key={t.key}
              onClick={() => setTab(t.key)}
              className="aegis-btn"
              style={{
                flex: 1,
                padding: "9px 12px",
                borderRadius: "8px",
                border: "none",
                cursor: "pointer",
                background: tab === t.key ? "rgba(255, 255, 255, 0.06)" : "transparent",
                color: tab === t.key ? C.text : C.muted,
                boxShadow: tab === t.key ? "0 2px 8px rgba(0, 0, 0, 0.15)" : "none",
                fontSize: "12.5px",
                fontWeight: 600,
                transition: "all 0.2s cubic-bezier(0.4, 0, 0.2, 1)",
              }}
            >
              {t.key === "demo" && <Sparkles size={12} style={{ marginRight: "4px" }} />}
              {t.label}
            </button>
          ))}
        </div>

        {/* Form Panel (Glassmorphism card) */}
        {tab === "live" ? (
          <form
            onSubmit={handleLoginSubmit}
            className="aegis-glass-panel"
            style={{
              padding: "28px",
              boxShadow: "0 20px 40px rgba(0, 0, 0, 0.3)",
              background: "rgba(15, 23, 42, 0.5)",
            }}
          >
            <h3 className="aegis-display" style={{ fontSize: "16px", fontWeight: 700, marginBottom: "10px", color: C.text }}>
              Secure SSO Authorization
            </h3>
            <p style={{ color: C.muted, fontSize: "13px", marginBottom: "20px", lineHeight: 1.6 }}>
              Sign in securely via Auth0 Universal Login. You will be redirected
              to authenticate and authorized access permissions will automatically map to your account profile.
            </p>

            {error && (
              <div
                style={{
                  display: "flex",
                  gap: "8px",
                  alignItems: "flex-start",
                  background: "rgba(244, 63, 94, 0.08)",
                  border: `1px solid rgba(244, 63, 94, 0.25)`,
                  borderRadius: "8px",
                  padding: "10px 12px",
                  marginBottom: "18px",
                  fontSize: "12px",
                  color: C.danger,
                }}
              >
                <AlertTriangle size={15} style={{ flexShrink: 0, marginTop: "1px" }} />
                <span>{error}</span>
              </div>
            )}

            <button
              type="submit"
              disabled={loading}
              className="aegis-btn aegis-btn-primary"
              style={{ width: "100%", padding: "12px", fontSize: "13.5px", borderRadius: "10px" }}
            >
              {loading ? (
                <Loader2 size={16} className="aegis-spin" />
              ) : (
                <Lock size={14} />
              )}
              {loading ? "Redirecting to Auth0…" : "Sign in with Auth0"}
            </button>

            <div
              style={{
                marginTop: "18px",
                fontSize: "11px",
                color: C.muted,
                textAlign: "center",
                lineHeight: "1.4",
              }}
            >
              Directory tokens and database isolation boundaries are encrypted.
            </div>
          </form>
        ) : (
          <div
            className="aegis-glass-panel"
            style={{
              padding: "12px",
              boxShadow: "0 20px 40px rgba(0, 0, 0, 0.3)",
              background: "rgba(15, 23, 42, 0.5)",
            }}
          >
            <div style={{ padding: "10px 16px 8px 16px" }}>
              <h3 className="aegis-display" style={{ fontSize: "15px", fontWeight: 700, color: C.text }}>
                Select Sandbox Role Profile
              </h3>
              <p style={{ color: C.muted, fontSize: "11.5px", marginTop: "2px", lineHeight: "1.4" }}>
                Enforce localized data queries, document vaults, and audit logs.
              </p>
            </div>
            
            <div style={{ marginTop: "8px" }}>
              {Object.entries(ROLES).map(([key, role]) => (
                <button
                  key={key}
                  className="aegis-btn aegis-row"
                  onClick={() => onDemo(key)}
                  onMouseEnter={() => setDemoHover(key)}
                  onMouseLeave={() => setDemoHover(null)}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "space-between",
                    width: "100%",
                    padding: "12px 16px",
                    borderRadius: "10px",
                    border: `1px solid ${demoHover === key ? `${role.accent}40` : "transparent"}`,
                    background: demoHover === key ? "rgba(255, 255, 255, 0.04)" : "transparent",
                    cursor: "pointer",
                    color: C.text,
                    marginBottom: "4px",
                    textAlign: "left",
                    transition: "all 0.15s ease-in-out",
                  }}
                >
                  <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
                    <div
                      style={{
                        width: "34px",
                        height: "34px",
                        borderRadius: "9px",
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "center",
                        background: `${role.accent}12`,
                        border: `1px solid ${role.accent}25`,
                      }}
                    >
                      <Shield size={16} color={role.accent} />
                    </div>
                    <div>
                      <div style={{ fontSize: "13.5px", fontWeight: 600 }}>{role.label}</div>
                      <div className="aegis-mono" style={{ fontSize: "10.5px", color: C.muted, marginTop: "1px" }}>
                        ID: {demoUsersMap[key] || `${key}_user`}
                      </div>
                    </div>
                  </div>
                  <ChevronRight size={14} color={C.muted} />
                </button>
              ))}
            </div>
            <div style={{ padding: "12px 16px 4px", fontSize: "11px", color: C.muted, textAlign: "center" }}>
              Runs fully in-browser with mock records — no backend required.
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
