import React, { useState, useEffect, useRef, useCallback } from "react";
import { ClipboardList, AlertTriangle, CheckCircle2, XCircle, ShieldOff, Loader2, RefreshCw, BarChart2, ShieldAlert } from "lucide-react";
import { C, ROLES } from "./SmallComponents";

const fallbackApiClient = {
  auditLogs: async (apiBase, token) => {
    const res = await fetch(`${apiBase}/api/v1/audit/recent`, {
      headers: { Authorization: `Bearer ${token}` }
    });
    if (!res.ok) throw new Error("Failed to load audit logs");
    return res.json();
  },
  auditStats: async (apiBase, token) => {
    const res = await fetch(`${apiBase}/api/v1/audit/stats`, {
      headers: { Authorization: `Bearer ${token}` }
    });
    if (!res.ok) throw new Error("Failed to load audit stats");
    return res.json();
  }
};

export default function AuditTrail({
  live,
  apiBase,
  token,
  logs,
  onSessionExpired,
  apiClient = fallbackApiClient,
  normalizeLogHelper = (l) => l
}) {
  const [remoteLogs, setRemoteLogs] = useState(null);
  const [stats, setStats] = useState({
    total_logged: 0,
    rbac_violations: 0,
    security_violations: 0,
    avg_response_time_ms: 0
  });
  
  const [filter, setFilter] = useState("all"); // 'all' | 'ALLOWED' | 'DENIED' | 'BLOCKED'
  const [loading, setLoading] = useState(live);
  const [error, setError] = useState(null);

  // Stable refs for callbacks that shouldn't re-trigger effect
  const apiClientRef = useRef(apiClient);
  const normalizeRef = useRef(normalizeLogHelper);
  const onSessionExpiredRef = useRef(onSessionExpired);
  apiClientRef.current = apiClient;
  normalizeRef.current = normalizeLogHelper;
  onSessionExpiredRef.current = onSessionExpired;

  const loadRemote = useCallback(() => {
    setLoading(true);
    setError(null);

    Promise.all([
      apiClientRef.current.auditLogs(apiBase, token),
      apiClientRef.current.auditStats(apiBase, token)
    ])
      .then(([logsData, statsData]) => {
        const list = Array.isArray(logsData) ? logsData : logsData.entries || logsData.logs || logsData.items || [];
        setRemoteLogs(list.map((l, idx) => normalizeRef.current(l, idx)));
        setStats(statsData || {
          total_logged: 0,
          rbac_violations: 0,
          security_violations: 0,
          avg_response_time_ms: 0
        });
      })
      .catch((err) => {
        if (err.status === 401) {
          onSessionExpiredRef.current();
          return;
        }
        setError(err.message || "Failed to load audit trails.");
      })
      .finally(() => {
        setLoading(false);
      });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [apiBase, token]);

  const loadLogsAndStats = loadRemote;

  // Fetch from API only when connection params change — NOT on every log change
  useEffect(() => {
    if (!live) {
      setLoading(false);
      return;
    }
    loadRemote();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [live, apiBase, token]);

  // Recalculate offline stats whenever local `logs` prop changes (demo mode only)
  useEffect(() => {
    if (live) return;
    const denied = logs.filter(l => l.result === "DENIED").length;
    const blocked = logs.filter(l => l.result === "BLOCKED").length;
    setStats({
      total_logged: logs.length,
      rbac_violations: denied,
      security_violations: blocked,
      avg_response_time_ms: 125.4
    });
    setLoading(false);
  }, [live, logs]);

  const resultStyle = {
    ALLOWED: { color: C.success, icon: CheckCircle2 },
    DENIED: { color: C.gold, icon: XCircle },
    BLOCKED: { color: C.danger, icon: ShieldOff },
  };

  const data = live ? (remoteLogs || []) : logs;
  
  const filteredLogs = data.filter(log => {
    if (filter === "all") return true;
    return log.result === filter;
  });

  return (
    <div style={{ height: "100%", display: "flex", flexDirection: "column" }} className="aegis-fade-in">
      {/* Header section */}
      <div style={{ padding: "20px 24px 0 24px" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "16px" }}>
          <div>
            <h2 className="aegis-display" style={{ margin: 0, fontSize: "20px", fontWeight: 700 }}>
              RBAC Audit Trail
            </h2>
            <p style={{ margin: "4px 0 0", fontSize: "12.5px", color: C.muted }}>
              Cryptographically cited logs of access requests, compliance queries, and policy violations
            </p>
          </div>
          {live && (
            <button
              onClick={loadLogsAndStats}
              disabled={loading}
              className="aegis-btn"
              style={{ padding: "8px 12px", fontSize: "12px" }}
            >
              <RefreshCw size={12} className={loading ? "aegis-spin" : ""} /> Refresh Telemetry
            </button>
          )}
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

        {/* Dashboard Stats Telemetry Cards */}
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))",
            gap: "16px",
            marginBottom: "20px",
          }}
        >
          <div className="aegis-stat-card">
            <div style={{ background: "rgba(56, 189, 248, 0.08)", border: "1px solid rgba(56, 189, 248, 0.2)", borderRadius: "8px", width: "40px", height: "40px", display: "flex", alignItems: "center", justifyContent: "center" }}>
              <ClipboardList size={18} color={C.teal} />
            </div>
            <div>
              <div style={{ fontSize: "11px", color: C.muted, fontWeight: 500, letterSpacing: "0.05em" }}>TOTAL REQUESTS</div>
              <div style={{ fontSize: "20px", fontWeight: 700, color: C.text, marginTop: "2px" }}>{stats.total_logged}</div>
            </div>
          </div>
          
          <div className="aegis-stat-card">
            <div style={{ background: "rgba(226, 184, 87, 0.08)", border: "1px solid rgba(226, 184, 87, 0.2)", borderRadius: "8px", width: "40px", height: "40px", display: "flex", alignItems: "center", justifyContent: "center" }}>
              <XCircle size={18} color={C.gold} />
            </div>
            <div>
              <div style={{ fontSize: "11px", color: C.muted, fontWeight: 500, letterSpacing: "0.05em" }}>ACCESS VIOLATIONS</div>
              <div style={{ fontSize: "20px", fontWeight: 700, color: C.gold, marginTop: "2px" }}>{stats.rbac_violations}</div>
            </div>
          </div>
          
          <div className="aegis-stat-card">
            <div style={{ background: "rgba(239, 68, 68, 0.08)", border: "1px solid rgba(239, 68, 68, 0.2)", borderRadius: "8px", width: "40px", height: "40px", display: "flex", alignItems: "center", justifyContent: "center" }}>
              <ShieldAlert size={18} color={C.danger} />
            </div>
            <div>
              <div style={{ fontSize: "11px", color: C.muted, fontWeight: 500, letterSpacing: "0.05em" }}>ATTACKS BLOCKED</div>
              <div style={{ fontSize: "20px", fontWeight: 700, color: C.danger, marginTop: "2px" }}>{stats.security_violations}</div>
            </div>
          </div>
          
          <div className="aegis-stat-card">
            <div style={{ background: "rgba(16, 185, 129, 0.08)", border: "1px solid rgba(16, 185, 129, 0.2)", borderRadius: "8px", width: "40px", height: "40px", display: "flex", alignItems: "center", justifyContent: "center" }}>
              <BarChart2 size={18} color={C.success} />
            </div>
            <div>
              <div style={{ fontSize: "11px", color: C.muted, fontWeight: 500, letterSpacing: "0.05em" }}>AVG LATENCY</div>
              <div style={{ fontSize: "20px", fontWeight: 700, color: C.success, marginTop: "2px" }}>
                {stats.avg_response_time_ms ? `${stats.avg_response_time_ms} ms` : "—"}
              </div>
            </div>
          </div>
        </div>

        {/* Outcome filters */}
        <div style={{ display: "flex", gap: "6px", marginBottom: "16px" }}>
          {[
            { key: "all", label: "All Logs" },
            { key: "ALLOWED", label: "Allowed" },
            { key: "DENIED", label: "Denied" },
            { key: "BLOCKED", label: "Blocked" }
          ].map((btn) => (
            <button
              key={btn.key}
              onClick={() => setFilter(btn.key)}
              className="aegis-btn"
              style={{
                padding: "8px 12px",
                fontSize: "11.5px",
                borderRadius: "20px",
                borderColor: filter === btn.key ? "rgba(226, 184, 87, 0.4)" : C.border,
                background: filter === btn.key ? "rgba(226, 184, 87, 0.08)" : "transparent",
                color: filter === btn.key ? C.gold : C.muted
              }}
            >
              {btn.label}
            </button>
          ))}
        </div>
      </div>

      {/* Timeline table */}
      <div className="aegis-scroll" style={{ flex: 1, overflowY: "auto", padding: "0 24px 24px 24px" }}>
        {loading ? (
          <div style={{ display: "flex", alignItems: "center", gap: "8px", color: C.muted, fontSize: "13.5px", marginTop: "40px", justifyContent: "center" }}>
            <Loader2 size={16} className="aegis-spin" /> Querying audit journals…
          </div>
        ) : filteredLogs.length === 0 ? (
          <div style={{ textAlign: "center", color: C.muted, marginTop: "40px", padding: "20px", border: `1px dashed ${C.border}`, borderRadius: "10px" }}>
            No audit logs found matching this filter outcome.
          </div>
        ) : (
          <div className="aegis-table-container">
            <div
              className="aegis-table-header"
              style={{
                display: "grid",
                gridTemplateColumns: "130px 150px 1.5fr 100px 1.2fr",
                padding: "12px 16px",
                fontSize: "11px",
                color: C.muted,
                fontWeight: 600,
                letterSpacing: "0.05em",
              }}
            >
              <div>TIME STAMP</div>
              <div>OPERATOR / ROLE</div>
              <div>REQUEST QUERY</div>
              <div>OUTCOME</div>
              <div>ACCESSED SOURCE</div>
            </div>

            {filteredLogs.slice().reverse().map((log) => {
              const r = resultStyle[log.result] || resultStyle.ALLOWED;
              const Icon = r.icon;
              return (
                <div
                  key={log.id}
                  className="aegis-row"
                  style={{
                    display: "grid",
                    gridTemplateColumns: "130px 150px 1.5fr 100px 1.2fr",
                    padding: "12px 16px",
                    borderTop: `1px solid ${C.borderSoft}`,
                    fontSize: "12.5px",
                    alignItems: "center",
                  }}
                >
                  <div className="aegis-mono" style={{ color: C.muted, fontSize: "11.5px" }}>
                    {log.time}
                  </div>
                  <div>
                    <div style={{ fontWeight: 600, color: C.text }}>{log.user}</div>
                    <div className="aegis-mono" style={{ fontSize: "10px", color: C.muted, marginTop: "1px" }}>
                      {ROLES[log.role]?.label || log.role}
                    </div>
                  </div>
                  <div style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", color: C.text, paddingRight: "10px" }} title={log.query}>
                    {log.query}
                  </div>
                  <div style={{ display: "flex", alignItems: "center", gap: "6px", color: r.color, fontWeight: 600, fontSize: "11.5px" }}>
                    <Icon size={13} /> {log.result}
                  </div>
                  <div
                    style={{
                      color: C.muted,
                      fontSize: "11.5px",
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                      whiteSpace: "nowrap",
                    }}
                    title={log.source}
                  >
                    {log.source}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
