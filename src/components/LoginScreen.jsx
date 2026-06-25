import React, { useState } from "react";
import { Shield, Lock, AlertTriangle, Loader2, ChevronRight, Sparkles } from "lucide-react";
import { C, ROLES } from "./SmallComponents";

export default function LoginScreen({ onLogin, onDemo, error, loading }) {
  const [tab, setTab] = useState("live"); // 'live' | 'demo'
  const [demoHover, setDemoHover] = useState(null);

  const demoUsersMap = {
    admin: "admin_user",
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
        backgroundImage: `radial-gradient(circle at 10% 20%, rgba(226, 184, 87, 0.03) 0%, transparent 40%), radial-gradient(circle at 90% 80%, rgba(56, 189, 248, 0.03) 0%, transparent 40%)`,
      }}
    >
      <div style={{ width: "100%", maxWidth: "440px" }} className="aegis-fade-in">
        <div style={{ textAlign: "center", marginBottom: "28px" }}>
          <div
            style={{
              display: "inline-flex",
              alignItems: "center",
              justifyContent: "center",
              width: "60px",
              height: "60px",
              borderRadius: "16px",
              background: `rgba(226, 184, 87, 0.08)`,
              border: `1px solid rgba(226, 184, 87, 0.3)`,
              marginBottom: "16px",
              boxShadow: "0 0 20px rgba(226, 184, 87, 0.15)",
            }}
          >
            <Shield size={30} color={C.gold} className="aegis-glow-pulse" />
          </div>
          <h1 className="aegis-display" style={{ fontSize: "32px", fontWeight: 700, margin: 0, letterSpacing: "0.05em", color: C.text }}>
            AEGIS
          </h1>
          <p style={{ color: C.muted, fontSize: "13px", marginTop: "6px" }}>
            Enterprise Intelligence Console
          </p>
        </div>

        {/* Tab Selection */}
        <div
          style={{
            display: "flex",
            gap: "4px",
            marginBottom: "18px",
            background: "rgba(14, 20, 32, 0.6)",
            border: `1px solid ${C.border}`,
            borderRadius: "12px",
            padding: "4px",
            backdropFilter: "blur(8px)",
          }}
        >
          {[
            { key: "live", label: "Live Server API" },
            { key: "demo", label: "Sandbox Demo" },
          ].map((t) => (
            <button
              key={t.key}
              onClick={() => setTab(t.key)}
              className="aegis-btn"
              style={{
                flex: 1,
                padding: "10px 12px",
                borderRadius: "8px",
                border: "none",
                cursor: "pointer",
                background: tab === t.key ? "var(--bg-panel-hover)" : "transparent",
                color: tab === t.key ? C.text : C.muted,
                boxShadow: tab === t.key ? "var(--shadow-sm)" : "none",
              }}
            >
              {t.key === "demo" && <Sparkles size={13} style={{ marginRight: "4px" }} />}
              {t.label}
            </button>
          ))}
        </div>

        {tab === "live" ? (
          <form
            onSubmit={handleLoginSubmit}
            className="aegis-glow-pulse"
            style={{
              background: C.panel,
              border: `1px solid ${C.border}`,
              borderRadius: "16px",
              padding: "24px",
              boxShadow: "var(--shadow-md)",
            }}
          >
            <p style={{ color: C.muted, fontSize: "13px", marginBottom: "20px", lineHeight: 1.5 }}>
              Sign in securely via Auth0 Universal Login. You'll be redirected
              to authenticate and brought back here automatically.
            </p>

            {error && (
              <div
                style={{
                  display: "flex",
                  gap: "8px",
                  alignItems: "flex-start",
                  background: "rgba(239, 68, 68, 0.08)",
                  border: `1px solid rgba(239, 68, 68, 0.3)`,
                  borderRadius: "8px",
                  padding: "10px 12px",
                  marginBottom: "16px",
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
              style={{ width: "100%", padding: "12px", fontSize: "14px" }}
            >
              {loading ? (
                <Loader2 size={16} className="aegis-spin" />
              ) : (
                <Lock size={15} />
              )}
              {loading ? "Redirecting…" : "Sign in with Auth0"}
            </button>

            <div
              style={{
                marginTop: "16px",
                fontSize: "10.5px",
                color: C.muted,
                textAlign: "center",
                lineHeight: "1.4",
              }}
            >
              Authentication and roles are managed in your Auth0 tenant.
            </div>
          </form>
        ) : (
          <div
            style={{
              background: C.panel,
              border: `1px solid ${C.border}`,
              borderRadius: "16px",
              padding: "12px",
              boxShadow: "var(--shadow-md)",
            }}
          >
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
                  padding: "14px 16px",
                  borderRadius: "12px",
                  border: `1px solid ${demoHover === key ? `${role.accent}55` : "transparent"}`,
                  background: demoHover === key ? "var(--bg-panel-hover)" : "transparent",
                  cursor: "pointer",
                  color: C.text,
                  marginBottom: "4px",
                }}
              >
                <div style={{ display: "flex", alignItems: "center", gap: "14px" }}>
                  <div
                    style={{
                      width: "36px",
                      height: "36px",
                      borderRadius: "10px",
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      background: `${role.accent}14`,
                      border: `1px solid ${role.accent}40`,
                    }}
                  >
                    <Shield size={17} color={role.accent} />
                  </div>
                  <div>
                    <div style={{ fontSize: "14px", fontWeight: 600 }}>{role.label}</div>
                    <div className="aegis-mono" style={{ fontSize: "11px", color: C.muted, marginTop: "1px" }}>
                      User: {demoUsersMap[key] || `${key}_user`}
                    </div>
                  </div>
                </div>
                <ChevronRight size={16} color={C.muted} />
              </button>
            ))}
            <div style={{ padding: "12px 16px 4px", fontSize: "11.5px", color: C.muted, textAlign: "center" }}>
              Runs fully in-browser with localized mocks — no backend required.
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
