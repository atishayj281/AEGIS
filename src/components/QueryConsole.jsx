import React, { useState, useRef, useEffect, useCallback } from "react";
import { Send, Sparkles, Loader2, AlertTriangle, ShieldOff, Lock, FileText, CheckCircle2, MessageSquarePlus, MessageSquare, PanelLeftClose, PanelLeft, Trash2 } from "lucide-react";
import { C, categoryInfo, ConfidenceBar, maskSensitive, ROLES, INJECTION_PATTERN } from "./SmallComponents";

const DEFAULT_QUERY_RULES = [
  {
    test: /failed login|login attempt|security incident|breach|unauthorized access/i,
    category: "audit_logs",
    confidence: 91,
    docs: ["DOC-003", "DOC-004"],
    answer: [
      "14 failed login attempts recorded in the last 24 hours",
      "9 originated from IP 203.0.113.44",
      "Account 'svc-reporting' was locked after 5 consecutive failures",
      "No successful breach indicators found"
    ]
  },
  {
    test: /compliance|gdpr|retention|regulatory|privacy/i,
    category: "compliance_records",
    confidence: 94,
    docs: ["DOC-001", "DOC-002"],
    answer: [
      "Audit completed on 15-Jan-2026",
      "3 medium-risk findings identified relating to data retention controls",
      "Encryption policy requires updates to meet current regulatory standards",
      "No critical violations detected"
    ]
  },
  {
    test: /cpu|server|infrastructure|threshold|uptime|disk/i,
    category: "system_metrics",
    confidence: 87,
    docs: ["DOC-009", "DOC-008"],
    answer: [
      "3 servers exceeded the 85% CPU threshold last week",
      "web-prod-02 peaked at 97% during nightly batch jobs",
      "Recommended action: scale batch workers or stagger job schedules"
    ]
  },
  {
    test: /invoice|vendor|payment/i,
    category: "invoice_records",
    confidence: 89,
    docs: ["DOC-005"],
    answer: [
      "Vendor ABC Corp has 2 pending invoices totalling $48,250",
      "Invoice #INV-2291 is 12 days overdue"
    ]
  },
  {
    test: /budget/i,
    category: "financial_database",
    confidence: 88,
    docs: ["DOC-006"],
    answer: ["Q2 budget utilization is at 73% against plan"]
  },
  {
    test: /incident|outage|technical report|downtime/i,
    category: "system_metrics",
    confidence: 83,
    docs: ["DOC-008"],
    sensitive: true,
    answer: [
      "Latest infrastructure audit flagged 2 high-severity findings",
      "Outage on 03-Jun-2026 traced to a misconfigured load balancer health check",
      "Remediation deployed; monitoring extended for 14 days",
      "Note: credential values in the source document have been masked below"
    ]
  },
  {
    test: /salary|compensation|payroll|executive pay/i,
    category: "salary_records",
    confidence: 96,
    docs: ["DOC-007"],
    answer: [
      "Executive compensation register located for fiscal year 2026",
      "Includes base salary, bonus structure, and equity grants for senior leadership"
    ]
  },
  {
    test: /remote work|work from home|wfh/i,
    category: "public_policies",
    confidence: 90,
    docs: ["DOC-011"],
    answer: [
      "Employees may work remotely up to 3 days per week with manager approval",
      "Core collaboration hours are 10:00-15:00 local time"
    ]
  }
];

const DEFAULT_QUERY_RULE = {
  category: "public_policies",
  confidence: 74,
  docs: ["DOC-010"],
  answer: [
    "No high-confidence match was found in restricted data sources",
    "Showing general guidance from company policy documentation"
  ]
};

const fallbackApiClient = {
  query: async (apiBase, token, queryText, sessionId = null) => {
    const res = await fetch(`${apiBase}/api/v1/query`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {})
      },
      body: JSON.stringify({ query: queryText, session_id: sessionId })
    });
    if (!res.ok) {
      let msg = `Request failed (${res.status})`;
      try {
        const data = await res.json();
        msg = data.detail || data.message || data.error || msg;
      } catch {}
      const err = new Error(msg);
      err.status = res.status;
      throw err;
    }
    return res.json();
  },
  listSessions: async () => [],
  getSession: async () => ({ session_id: "demo", turns: [] }),
  deleteSession: async () => ({})
};

export default function QueryConsole({
  live,
  apiBase,
  token,
  roleKey,
  documents,
  messages,
  setMessages,
  onAuditEntry,
  onSessionExpired,
  apiClient = fallbackApiClient,
  simulatedQueryRules = DEFAULT_QUERY_RULES,
  simulatedDefaultRule = DEFAULT_QUERY_RULE
}) {
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const scrollRef = useRef(null);
  const role = ROLES[roleKey] || ROLES.employee;

  // -- Session State --
  const [sessionId, setSessionId] = useState(null);
  const [sessions, setSessions] = useState([]);
  const [sidebarOpen, setSidebarOpen] = useState(true);

  const fetchSessions = useCallback(async () => {
    if (!live || !token) return;
    try {
      const data = await apiClient.listSessions(apiBase, token);
      setSessions(Array.isArray(data) ? data : []);
    } catch (e) {
      console.error("Failed to fetch sessions", e);
    }
  }, [live, token, apiBase, apiClient]);

  useEffect(() => {
    fetchSessions();
  }, [fetchSessions]);

  const handleLoadSession = async (id) => {
    if (!live || !token) return;
    try {
      const data = await apiClient.getSession(apiBase, token, id);
      setSessionId(data.session_id);
      const mapped = (data.turns || []).map((t, i) => ({
        id: `hist-${i}`,
        role: t.role === "user" ? "user" : "assistant",
        type: t.role === "user" ? undefined : "answer",
        text: t.content,
        answer: t.role === "user" ? undefined : t.content,
        citations: [],
        category: "general"
      }));
      setMessages(mapped);
    } catch (e) {
      console.error("Failed to load session", e);
    }
  };

  const handleDeleteSession = async (id, e) => {
    e.stopPropagation();
    if (!live || !token) return;
    try {
      await apiClient.deleteSession(apiBase, token, id);
      if (sessionId === id) {
        setSessionId(null);
        setMessages([]);
      }
      fetchSessions();
    } catch (err) {
      console.error("Failed to delete session", err);
    }
  };

  const handleNewChat = () => {
    setSessionId(null);
    setMessages([]);
  };

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, loading]);

  const suggestions = [
    "What are the compliance requirements for customer data retention?",
    "Show all failed login attempts in the last 24 hours.",
    "Which servers exceeded CPU thresholds last week?",
    "List pending invoices for Vendor ABC.",
    "Show executive salary information.",
  ];

  const handleSend = async (text) => {
    const query = (text ?? input).trim();
    if (!query) return;

    const userMsg = { id: Date.now(), role: "user", text: query };
    setMessages((prev) => [...prev, userMsg]);
    setInput("");
    setLoading(true);

    const loadingId = Date.now() + 1;
    setMessages((prev) => [...prev, { id: loadingId, role: "assistant", type: "loading" }]);

    if (live) {
      try {
        const data = await apiClient.query(apiBase, token, query, sessionId);
        if (data.session_id && data.session_id !== sessionId) {
          setSessionId(data.session_id);
          fetchSessions();
        }
        
        // Handle Security Violation (Prompt Injection)
        if (data.blocked || data.violation_type) {
          const reply = {
            id: loadingId,
            role: "assistant",
            type: "blocked",
            text: data.reason || "This request matches a known security violation policy and was blocked."
          };
          setMessages((prev) => prev.map((m) => (m.id === loadingId ? reply : m)));
          onAuditEntry({
            user: usernameFromToken(token) || role.label,
            role: roleKey,
            query,
            result: "BLOCKED",
            source: "—"
          });
        }
        // Handle Access Denied
        else if (data.access_granted === false) {
          const reply = {
            id: loadingId,
            role: "assistant",
            type: "denied",
            category: data.required_permission,
            text: data.message || "You do not have clearance permissions to access the requested data source."
          };
          setMessages((prev) => prev.map((m) => (m.id === loadingId ? reply : m)));
          onAuditEntry({
            user: usernameFromToken(token) || role.label,
            role: roleKey,
            query,
            result: "DENIED",
            source: "—"
          });
        }
        // Handle normal grounded answer
        else {
          const cat = data.category || data.domain || data.intent || "public_policies";
          const citationsArray = (data.citations || data.sources || data.context || []).map(c => {
            if (typeof c === "string") return c;
            return c.source_name || c.name || c.file || "Source Document";
          });
          
          const reply = {
            id: loadingId,
            role: "assistant",
            type: "answer",
            category: cat,
            answer: data.answer || data.response || "No response content.",
            citations: citationsArray,
            confidence: data.confidence ?? 0.95
          };
          setMessages((prev) => prev.map((m) => (m.id === loadingId ? reply : m)));
          onAuditEntry({
            user: usernameFromToken(token) || role.label,
            role: roleKey,
            query,
            result: "ALLOWED",
            source: citationsArray.join(", ") || "—"
          });
        }
      } catch (err) {
        if (err.status === 401) {
          onSessionExpired();
          return;
        }
        
        let errType = "error";
        let errMsg = err.message || "An unexpected error occurred.";
        let errCat = null;
        
        if (err.status === 403) {
          errType = "denied";
          errMsg = err.message || "Access Denied: Restricted clearance resource.";
        } else if (err.status === 400 && /inject|security|blocked/i.test(err.message)) {
          errType = "blocked";
        }
        
        const reply = {
          id: loadingId,
          role: "assistant",
          type: errType,
          text: errMsg,
          category: errCat
        };
        setMessages((prev) => prev.map((m) => (m.id === loadingId ? reply : m)));
        if (errType !== "error") {
          onAuditEntry({
            user: usernameFromToken(token) || role.label,
            role: roleKey,
            query,
            result: errType === "denied" ? "DENIED" : "BLOCKED",
            source: "—"
          });
        }
      } finally {
        setLoading(false);
      }
      return;
    }

    // ---- sandbox offline demo mode ----
    setTimeout(() => {
      if (INJECTION_PATTERN.test(query)) {
        const reply = { id: loadingId, role: "assistant", type: "blocked" };
        setMessages((prev) => prev.map((m) => (m.id === loadingId ? reply : m)));
        onAuditEntry({ user: role.label, role: roleKey, query, result: "BLOCKED", source: "—" });
        setLoading(false);
        return;
      }
      
      const rule = simulatedQueryRules.find((r) => r.test.test(query)) || simulatedDefaultRule;
      const allowed = role.categories.includes(rule.category);
      
      if (!allowed) {
        const reply = { id: loadingId, role: "assistant", type: "denied", category: rule.category };
        setMessages((prev) => prev.map((m) => (m.id === loadingId ? reply : m)));
        onAuditEntry({ user: role.label, role: roleKey, query, result: "DENIED", source: "—" });
        setLoading(false);
        return;
      }
      
      const citedDocs = rule.docs.map((id) => documents.find((d) => d.id === id)).filter(Boolean);
      const citationsArray = citedDocs.map((d) => d.name);
      
      const reply = {
        id: loadingId,
        role: "assistant",
        type: "answer",
        category: rule.category,
        answer: rule.answer,
        citations: citationsArray,
        confidence: rule.confidence ? (rule.confidence > 1.0 ? rule.confidence / 100 : rule.confidence) : 0.85
      };
      
      setMessages((prev) => prev.map((m) => (m.id === loadingId ? reply : m)));
      onAuditEntry({
        user: role.label,
        role: roleKey,
        query,
        result: "ALLOWED",
        source: citationsArray.join(", ") || "—"
      });
      setLoading(false);
    }, 800);
  };

  const usernameFromToken = (tok) => {
    try {
      const payload = tok.split(".")[1];
      const json = atob(payload.replace(/-/g, "+").replace(/_/g, "/"));
      const claims = JSON.parse(json);
      return claims.sub || claims.username;
    } catch {
      return null;
    }
  };

  return (
    <div style={{ display: "flex", height: "100%", overflow: "hidden" }}>
      {/* ── SIDEBAR ── */}
      {sidebarOpen && (
        <div
          style={{
            width: "260px",
            borderRight: `1px solid ${C.border}`,
            background: "rgba(10, 15, 30, 0.45)",
            backdropFilter: "blur(12px)",
            WebkitBackdropFilter: "blur(12px)",
            display: "flex",
            flexDirection: "column",
            flexShrink: 0,
            transition: "width 0.2s"
          }}
        >
          <div style={{ padding: "16px" }}>
            <button
              onClick={handleNewChat}
              className="aegis-btn aegis-btn-primary"
              style={{ width: "100%", padding: "10px", display: "flex", alignItems: "center", justifyContent: "center", gap: "8px", borderRadius: "10px" }}
            >
              <MessageSquarePlus size={15} />
              <span>New Chat</span>
            </button>
          </div>
          <div style={{ padding: "8px 16px", fontSize: "11px", fontWeight: 600, color: C.muted, textTransform: "uppercase", letterSpacing: "0.06em" }}>
            Recent Sessions
          </div>
          <div className="aegis-scroll" style={{ flex: 1, overflowY: "auto", padding: "0 8px 16px 8px" }}>
            {sessions.length === 0 ? (
              <div style={{ padding: "16px", textAlign: "center", color: C.muted, fontSize: "12px", fontStyle: "italic" }}>
                No active sessions
              </div>
            ) : (
              sessions.map(s => (
                <div
                  key={s.session_id}
                  onClick={() => handleLoadSession(s.session_id)}
                  className="aegis-btn"
                  style={{
                    display: "flex", alignItems: "center", justifyContent: "space-between",
                    padding: "9px 12px", margin: "4px", borderRadius: "8px",
                    background: sessionId === s.session_id ? "rgba(255, 255, 255, 0.05)" : "transparent",
                    color: sessionId === s.session_id ? C.text : C.muted,
                    border: sessionId === s.session_id ? `1px solid rgba(255,255,255,0.08)` : "1px solid transparent",
                    cursor: "pointer", fontSize: "12.5px", transition: "all 0.15s ease",
                    textAlign: "left"
                  }}
                >
                  <div style={{ display: "flex", alignItems: "center", gap: "8px", overflow: "hidden", width: "80%" }}>
                    <MessageSquare size={13} style={{ flexShrink: 0 }} color={sessionId === s.session_id ? C.gold : C.muted} />
                    <span style={{ whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                      {s.turns?.[0]?.content || "Empty Session"}
                    </span>
                  </div>
                  <button
                    onClick={(e) => handleDeleteSession(s.session_id, e)}
                    className="aegis-btn"
                    style={{ padding: "4px", color: C.danger, border: "none", background: "transparent" }}
                  >
                    <Trash2 size={12} />
                  </button>
                </div>
              ))
            )}
          </div>
        </div>
      )}

      {/* ── MAIN CHAT AREA ── */}
      <div style={{ flex: 1, display: "flex", flexDirection: "column", position: "relative", minWidth: 0 }}>
        <button
          onClick={() => setSidebarOpen(!sidebarOpen)}
          className="aegis-btn"
          style={{
            position: "absolute",
            top: "16px",
            left: "16px",
            zIndex: 10,
            padding: "8px",
            background: "rgba(15, 23, 42, 0.6)",
            border: `1px solid ${C.border}`,
            borderRadius: "8px",
            color: C.muted,
            backdropFilter: "blur(6px)"
          }}
        >
          {sidebarOpen ? <PanelLeftClose size={15} /> : <PanelLeft size={15} />}
        </button>

        {/* Scrollable messages container */}
        <div
          ref={scrollRef}
          className="aegis-scroll"
          style={{
            flex: 1,
            overflowY: "auto",
            padding: "32px 32px 10px 32px",
            display: "flex",
            flexDirection: "column",
            gap: "20px",
          }}
        >
          {messages.length === 0 && (
            <div style={{ textAlign: "center", marginTop: "60px", padding: "0 20px" }} className="aegis-fade-in">
              <Sparkles size={38} color={C.gold} style={{ marginBottom: "16px", filter: "drop-shadow(0 0 12px rgba(245,158,11,0.3))" }} />
              <h2 className="aegis-display" style={{ fontSize: "21px", fontWeight: 700, color: C.text, marginBottom: "8px" }}>
                Secure RAG Assistant Console
              </h2>
              <p style={{ fontSize: "13px", color: C.muted, marginBottom: "28px", maxWidth: "480px", margin: "0 auto 28px", lineHeight: 1.5 }}>
                Enter search query queries. Answers are strictly verified and compiled based on source clearances for role:{" "}
                <span className="aegis-mono" style={{ color: role.accent, fontWeight: 600 }}>{role.label}</span>.
              </p>
              
              <div className="aegis-suggestion-grid">
                {suggestions.map((s) => (
                  <button
                    key={s}
                    className="aegis-btn aegis-glass-card"
                    onClick={() => handleSend(s)}
                    disabled={loading}
                    style={{
                      textAlign: "left",
                      padding: "14px",
                      fontSize: "12.5px",
                      lineHeight: "1.4",
                      borderRadius: "12px",
                      cursor: "pointer",
                      display: "block",
                      width: "100%"
                    }}
                  >
                    {s}
                  </button>
                ))}
              </div>
            </div>
          )}

          {messages.map((m) => {
            if (m.role === "user") {
              return (
                <div key={m.id} className="aegis-fade-in" style={{ display: "flex", justifyContent: "flex-end" }}>
                  <div
                    style={{
                      maxWidth: "75%",
                      background: "rgba(99, 102, 241, 0.12)",
                      border: `1px solid rgba(99, 102, 241, 0.28)`,
                      borderRadius: "14px 14px 2px 14px",
                      padding: "12px 16px",
                      fontSize: "13.5px",
                      color: C.text,
                      boxShadow: "0 4px 12px rgba(99, 102, 241, 0.05)",
                    }}
                  >
                    {m.text}
                  </div>
                </div>
              );
            }

            if (m.type === "loading") {
              return (
                <div key={m.id} className="aegis-fade-in" style={{ display: "flex", justifyContent: "flex-start" }}>
                  <div
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: "10px",
                      background: "rgba(255, 255, 255, 0.02)",
                      border: `1px solid ${C.border}`,
                      borderRadius: "2px 14px 14px 14px",
                      padding: "12px 18px",
                      color: C.muted,
                      fontSize: "13px",
                      backdropFilter: "blur(6px)",
                    }}
                  >
                    <Loader2 size={14} className="aegis-spin" color={C.gold} /> Grounding references & indexing vectors…
                  </div>
                </div>
              );
            }

            if (m.type === "error") {
              return (
                <div key={m.id} className="aegis-fade-in" style={{ display: "flex", justifyContent: "flex-start" }}>
                  <div
                    style={{
                      maxWidth: "80%",
                      background: "rgba(244, 63, 94, 0.08)",
                      border: `1px solid rgba(244, 63, 94, 0.25)`,
                      borderRadius: "2px 14px 14px 14px",
                      padding: "14px 18px",
                    }}
                  >
                    <div style={{ display: "flex", alignItems: "center", gap: "8px", marginBottom: "6px" }}>
                      <AlertTriangle size={15} color={C.danger} />
                      <span className="aegis-mono" style={{ fontSize: "10.5px", fontWeight: 700, color: C.danger, letterSpacing: "0.06em" }}>
                        REQUEST COMPONENT EXCEPTION
                      </span>
                    </div>
                    <div style={{ fontSize: "13px", color: C.text }}>{m.text}</div>
                  </div>
                </div>
              );
            }

            if (m.type === "blocked") {
              return (
                <div key={m.id} className="aegis-fade-in" style={{ display: "flex", justifyContent: "flex-start" }}>
                  <div
                    style={{
                      maxWidth: "80%",
                      background: "rgba(244, 63, 94, 0.08)",
                      border: `1px solid rgba(244, 63, 94, 0.35)`,
                      borderRadius: "2px 14px 14px 14px",
                      padding: "16px 18px",
                      boxShadow: "0 8px 24px rgba(244, 63, 94, 0.1)",
                    }}
                  >
                    <div style={{ display: "flex", alignItems: "center", gap: "8px", marginBottom: "8px" }}>
                      <ShieldOff size={16} color={C.danger} />
                      <span className="aegis-mono" style={{ fontSize: "11px", fontWeight: 700, color: C.danger, letterSpacing: "0.06em" }}>
                        PROMPT INJECTION GATING SHIELD
                      </span>
                    </div>
                    <div style={{ fontSize: "13px", color: C.text, lineHeight: "1.5" }}>
                      {m.text || "Security boundary violation: Input matches malicious instruction overrides. The event has been appended to the audit logging journals."}
                    </div>
                  </div>
                </div>
              );
            }

            if (m.type === "denied") {
              const cat = categoryInfo(m.category);
              return (
                <div key={m.id} className="aegis-fade-in" style={{ display: "flex", justifyContent: "flex-start" }}>
                  <div
                    className="aegis-ticket"
                    style={{
                      maxWidth: "80%",
                      background: "rgba(245, 158, 11, 0.05)",
                      border: `1px solid rgba(245, 158, 11, 0.3)`,
                      borderRadius: "2px 14px 14px 14px",
                      padding: "16px 18px",
                      boxShadow: "0 8px 24px rgba(245, 158, 11, 0.05)",
                    }}
                  >
                    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "10px" }}>
                      <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                        <Lock size={14} color={C.gold} />
                        <span className="aegis-mono" style={{ fontSize: "10.5px", fontWeight: 700, color: C.gold, letterSpacing: "0.06em" }}>
                          ACCESS DENIED
                        </span>
                      </div>
                      <div className="aegis-stamp" style={{ border: `1.5px solid ${C.gold}`, color: C.gold, borderRadius: "4px", padding: "1px 6px", fontSize: "9px", fontWeight: 700, letterSpacing: "0.05em" }}>
                        RESTRICTED
                      </div>
                    </div>
                    <div style={{ fontSize: "13px", color: C.text, lineHeight: "1.5" }}>
                      {m.text || (
                        <>
                          Clearance Error: Your role does not hold credentials to retrieve database category{" "}
                          <strong>{cat.label}</strong> [{cat.classification}].
                        </>
                      )}
                    </div>
                  </div>
                </div>
              );
            }

            // Grounded Verified Response Card
            const cat = categoryInfo(m.category);
            return (
              <div key={m.id} className="aegis-fade-in" style={{ display: "flex", justifyContent: "flex-start" }}>
                <div
                  className="aegis-ticket aegis-glass-panel"
                  style={{
                    maxWidth: "85%",
                    padding: "18px 20px",
                    boxShadow: "0 12px 30px rgba(0, 0, 0, 0.25)",
                    background: "rgba(15, 23, 42, 0.65)"
                  }}
                >
                  <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "12px", flexWrap: "wrap", gap: "8px" }}>
                    <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                      <Sparkles size={14} color={C.gold} />
                      <span className="aegis-mono" style={{ fontSize: "10.5px", color: C.muted, letterSpacing: "0.08em" }}>
                        GROUNDED RESOURCE · {cat.label.toUpperCase()}
                      </span>
                    </div>
                    <div className="aegis-stamp" style={{ border: `1.5px solid ${C.success}`, color: C.success, borderRadius: "4px", padding: "1px 6px", fontSize: "9px", fontWeight: 700, letterSpacing: "0.05em" }}>
                      VERIFIED
                    </div>
                  </div>

                  {/* Grounded text output */}
                  <div style={{ color: C.text, fontSize: "13.5px", lineHeight: "1.6" }}>
                    {Array.isArray(m.answer) ? (
                      <ul style={{ margin: 0, paddingLeft: "18px" }}>
                        {m.answer.map((line, i) => (
                          <li key={i} style={{ marginBottom: "6px" }}>{maskSensitive(line)}</li>
                        ))}
                      </ul>
                    ) : (
                      <div style={{ whiteSpace: "pre-wrap" }}>{maskSensitive(m.answer)}</div>
                    )}
                  </div>

                  {/* Citations & Confidence Indicators */}
                  {((m.citations && m.citations.length > 0) || m.confidence !== undefined) && (
                    <div
                      style={{
                        marginTop: "16px",
                        borderTop: `1px solid rgba(255, 255, 255, 0.08)`,
                        paddingTop: "14px",
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "space-between",
                        flexWrap: "wrap",
                        gap: "10px",
                      }}
                    >
                      <div style={{ display: "flex", flexWrap: "wrap", gap: "6px" }}>
                        {(m.citations || []).map((c, i) => (
                          <span
                            key={i}
                            className="aegis-mono"
                            style={{
                              display: "inline-flex",
                              alignItems: "center",
                              gap: "5px",
                              fontSize: "10.5px",
                              padding: "3px 8px",
                              borderRadius: "6px",
                              border: `1px solid rgba(255, 255, 255, 0.06)`,
                              background: "rgba(255, 255, 255, 0.02)",
                              color: C.muted,
                            }}
                          >
                            <FileText size={10} color={C.teal} /> {c}
                          </span>
                        ))}
                      </div>
                      {m.confidence !== undefined && (
                        <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                          <span className="aegis-mono" style={{ fontSize: "10px", color: C.muted, letterSpacing: "0.05em" }}>RELEVANCE</span>
                          <ConfidenceBar score={m.confidence} />
                        </div>
                      )}
                    </div>
                  )}
                </div>
              </div>
            );
          })}
        </div>

        {/* Input container */}
        <div
          style={{
            padding: "16px 24px 20px 24px",
            borderTop: `1px solid rgba(255, 255, 255, 0.06)`,
            background: "rgba(3, 7, 18, 0.5)",
            backdropFilter: "blur(8px)"
          }}
        >
          <div style={{ display: "flex", gap: "10px" }}>
            <input
              className="aegis-input"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && !loading && handleSend()}
              placeholder="Query documents index (e.g. customer data retention or system CPU)..."
              disabled={loading}
              style={{
                padding: "12px 14px",
                fontSize: "13.5px",
                borderRadius: "10px",
                background: "rgba(0, 0, 0, 0.25)"
              }}
            />
            <button
              onClick={() => handleSend()}
              disabled={loading || !input.trim()}
              className="aegis-btn aegis-btn-primary"
              style={{ padding: "12px 20px", borderRadius: "10px", flexShrink: 0 }}
            >
              {loading ? <Loader2 size={15} className="aegis-spin" /> : <Send size={14} />}
              <span>Ask AEGIS</span>
            </button>
          </div>
          <div style={{ marginTop: "10px", fontSize: "11px", color: C.muted, display: "flex", alignItems: "center", gap: "6px" }}>
            <CheckCircle2 size={12} color={C.success} />
            <span>
              {live
                ? `RBAC enforcement queries active on FastAPI gateway: ${apiBase}`
                : "Sandbox Simulator mode — query intent and access scopes evaluated locally."}
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}
