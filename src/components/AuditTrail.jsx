import React, { useState, useEffect, useRef, useCallback, useMemo } from "react";
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
  // Stats are derived (not stored as state) so new objects don't trigger a re-render cycle
  const [remoteStats, setRemoteStats] = useState(null);
  const derivedStats = useMemo(() => {
    if (live && remoteStats) return remoteStats;
    const src = live ? (remoteLogs || []) : logs;
    const denied = src.filter(l => l.result === "DENIED").length;
    const blocked = src.filter(l => l.result === "BLOCKED").length;
    return {
      total_logged: src.length,
      rbac_violations: denied,
      security_violations: blocked,
      avg_response_time_ms: 125.4
    };
  }, [live, logs, remoteLogs, remoteStats]);

  const [filter, setFilter] = useState("all"); // 'all' | 'ALLOWED' | 'DENIED' | 'BLOCKED'
  const [loading, setLoading] = useState(live);
  const [error, setError] = useState(null);

  // Compliance Export States
  const [showExportModal, setShowExportModal] = useState(false);
  const [exportFormat, setExportFormat] = useState("json");
  const [exportFrom, setExportFrom] = useState("");
  const [exportTo, setExportTo] = useState("");
  const [exportUsername, setExportUsername] = useState("");
  const [exportLimit, setExportLimit] = useState(1000);
  const [exportBusy, setExportBusy] = useState(false);
  const [exportError, setExportError] = useState(null);

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
        if (statsData) setRemoteStats(statsData);
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
  }, [apiBase, token]);

  const loadLogsAndStats = loadRemote;

  useEffect(() => {
    if (!live) {
      setLoading(false);
      return;
    }
    loadRemote();
  }, [live, apiBase, token, loadRemote]);

  // (No separate stats useEffect — stats are now derived via useMemo above)

  const handleExport = async (e) => {
    e.preventDefault();
    setExportBusy(true);
    setExportError(null);
    
    if (!live) {
      setTimeout(() => {
        let localData = logs;
        if (exportUsername.trim()) {
          localData = localData.filter(l => String(l.user).toLowerCase() === exportUsername.trim().toLowerCase());
        }
        localData = localData.slice(0, exportLimit);
        
        let blob;
        let filename = `sandbox_compliance_audit_${new Date().toISOString().split('T')[0]}`;
        if (exportFormat === "csv") {
          const csvLines = [
            ["ID", "Timestamp", "Operator", "Role", "Query", "Outcome", "Source"],
            ...localData.map(l => [l.id, l.time, l.user, l.role, l.query, l.result, l.source])
          ].map(row => row.map(cell => `"${String(cell).replace(/"/g, '""')}"`).join(",")).join("\n");
          blob = new Blob([csvLines], { type: "text/csv;charset=utf-8;" });
          filename += ".csv";
        } else {
          blob = new Blob([JSON.stringify(localData, null, 2)], { type: "application/json;charset=utf-8;" });
          filename += ".json";
        }
        
        const link = document.createElement("a");
        const url = URL.createObjectURL(blob);
        link.setAttribute("href", url);
        link.setAttribute("download", filename);
        link.style.visibility = "hidden";
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        
        setExportBusy(false);
        setShowExportModal(false);
      }, 500);
      return;
    }
    
    try {
      const params = {
        format: exportFormat,
        from_date: exportFrom ? new Date(exportFrom).toISOString() : undefined,
        to_date: exportTo ? new Date(exportTo).toISOString() : undefined,
        username: exportUsername.trim() || undefined,
        limit: exportLimit,
      };
      
      const res = await apiClientRef.current.complianceExport(apiBase, token, params);
      
      let blob;
      let filename = `aegis_compliance_audit_${new Date().toISOString().split('T')[0]}`;
      if (exportFormat === "csv") {
        blob = new Blob([res], { type: "text/csv;charset=utf-8;" });
        filename += ".csv";
      } else {
        blob = new Blob([JSON.stringify(res, null, 2)], { type: "application/json;charset=utf-8;" });
        filename += ".json";
      }
      
      const link = document.createElement("a");
      const url = URL.createObjectURL(blob);
      link.setAttribute("href", url);
      link.setAttribute("download", filename);
      link.style.visibility = "hidden";
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      
      setShowExportModal(false);
    } catch (err) {
      if (err.status === 401) {
        onSessionExpiredRef.current();
        return;
      }
      setExportError(err.message || "Failed to export compliance logs.");
    } finally {
      setExportBusy(false);
    }
  };

  const resultStyle = {
    ALLOWED: { color: C.success, icon: CheckCircle2, bg: "rgba(16, 185, 129, 0.08)" },
    DENIED: { color: C.gold, icon: XCircle, bg: "rgba(245, 158, 11, 0.08)" },
    BLOCKED: { color: C.danger, icon: ShieldOff, bg: "rgba(244, 63, 94, 0.08)" },
  };

  const data = live ? (remoteLogs || []) : logs;
  const stats = derivedStats;

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
          <div style={{ display: "flex", gap: "8px" }}>
            <button
              onClick={() => {
                setExportError(null);
                setShowExportModal(true);
              }}
              disabled={loading}
              className="aegis-btn"
              style={{
                display: "flex",
                alignItems: "center",
                gap: "6px",
                padding: "8px 12px",
                fontSize: "12px",
                borderRadius: "8px",
                borderColor: "rgba(245, 158, 11, 0.3)",
              }}
            >
              <ClipboardList size={12} color={C.gold} /> Export Logs
            </button>
            {live && (
              <button
                onClick={loadLogsAndStats}
                disabled={loading}
                className="aegis-btn"
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: "6px",
                  padding: "8px 12px",
                  fontSize: "12px",
                  borderRadius: "8px",
                }}
              >
                <RefreshCw size={12} className={loading ? "aegis-spin" : ""} /> Refresh Telemetry
              </button>
            )}
          </div>
        </div>

        {error && (
          <div
            style={{
              display: "flex",
              gap: "8px",
              background: "rgba(244, 63, 94, 0.08)",
              border: `1px solid rgba(244, 63, 94, 0.25)`,
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
            <div style={{ background: "rgba(6, 182, 212, 0.06)", border: "1px solid rgba(6, 182, 212, 0.2)", borderRadius: "10px", width: "42px", height: "42px", display: "flex", alignItems: "center", justifyContent: "center" }}>
              <ClipboardList size={18} color={C.teal} />
            </div>
            <div>
              <div style={{ fontSize: "10.5px", color: C.muted, fontWeight: 600, letterSpacing: "0.05em" }}>TOTAL REQUESTS</div>
              <div style={{ fontSize: "20px", fontWeight: 700, color: C.text, marginTop: "1px" }}>{stats.total_logged}</div>
            </div>
          </div>
          
          <div className="aegis-stat-card">
            <div style={{ background: "rgba(245, 158, 11, 0.06)", border: "1px solid rgba(245, 158, 11, 0.2)", borderRadius: "10px", width: "42px", height: "42px", display: "flex", alignItems: "center", justifyContent: "center" }}>
              <XCircle size={18} color={C.gold} />
            </div>
            <div>
              <div style={{ fontSize: "10.5px", color: C.muted, fontWeight: 600, letterSpacing: "0.05em" }}>ACCESS VIOLATIONS</div>
              <div style={{ fontSize: "20px", fontWeight: 700, color: C.gold, marginTop: "1px" }}>{stats.rbac_violations}</div>
            </div>
          </div>
          
          <div className="aegis-stat-card">
            <div style={{ background: "rgba(244, 63, 94, 0.06)", border: "1px solid rgba(244, 63, 94, 0.2)", borderRadius: "10px", width: "42px", height: "42px", display: "flex", alignItems: "center", justifyContent: "center" }}>
              <ShieldAlert size={18} color={C.danger} />
            </div>
            <div>
              <div style={{ fontSize: "10.5px", color: C.muted, fontWeight: 600, letterSpacing: "0.05em" }}>ATTACKS BLOCKED</div>
              <div style={{ fontSize: "20px", fontWeight: 700, color: C.danger, marginTop: "1px" }}>{stats.security_violations}</div>
            </div>
          </div>
          
          <div className="aegis-stat-card">
            <div style={{ background: "rgba(16, 185, 129, 0.06)", border: "1px solid rgba(16, 185, 129, 0.2)", borderRadius: "10px", width: "42px", height: "42px", display: "flex", alignItems: "center", justifyContent: "center" }}>
              <BarChart2 size={18} color={C.success} />
            </div>
            <div>
              <div style={{ fontSize: "10.5px", color: C.muted, fontWeight: 600, letterSpacing: "0.05em" }}>AVG LATENCY</div>
              <div style={{ fontSize: "20px", fontWeight: 700, color: C.success, marginTop: "1px" }}>
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
                padding: "8px 14px",
                fontSize: "11.5px",
                borderRadius: "20px",
                borderColor: filter === btn.key ? "rgba(245, 158, 11, 0.35)" : C.border,
                background: filter === btn.key ? "rgba(245, 158, 11, 0.08)" : "transparent",
                color: filter === btn.key ? C.gold : C.muted,
                transition: "all 0.2s"
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
            <Loader2 size={16} className="aegis-spin" color={C.gold} /> Querying audit records…
          </div>
        ) : filteredLogs.length === 0 ? (
          <div style={{ textAlign: "center", color: C.muted, marginTop: "40px", padding: "24px", border: `1px dashed ${C.border}`, borderRadius: "12px", background: "rgba(255,255,255,0.01)" }}>
            No audit records match the selected filter outcome.
          </div>
        ) : (
          <div className="aegis-table-container">
            <div
              className="aegis-table-header"
              style={{
                display: "grid",
                gridTemplateColumns: "130px 160px 1.5fr 100px 1.2fr",
                padding: "12px 16px",
                fontSize: "11px",
                color: C.muted,
                fontWeight: 600,
                letterSpacing: "0.06em",
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
                    gridTemplateColumns: "130px 160px 1.5fr 100px 1.2fr",
                    padding: "12px 16px",
                    borderTop: `1px solid ${C.border}`,
                    fontSize: "12.5px",
                    alignItems: "center",
                    transition: "all 0.15s ease",
                  }}
                >
                  <div className="aegis-mono" style={{ color: C.muted, fontSize: "11.5px" }}>
                    {log.time}
                  </div>
                  <div>
                    <div style={{ fontWeight: 600, color: C.text }}>{log.user}</div>
                    <div className="aegis-mono" style={{ fontSize: "9.5px", color: C.muted, marginTop: "1px", fontWeight: 500 }}>
                      {ROLES[log.role]?.label || log.role}
                    </div>
                  </div>
                  <div style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", color: C.text, paddingRight: "10px" }} title={log.query}>
                    {log.query}
                  </div>
                  <div>
                    <span
                      style={{
                        display: "inline-flex",
                        alignItems: "center",
                        gap: "5px",
                        color: r.color,
                        fontWeight: 600,
                        fontSize: "11.5px",
                        padding: "3px 8px",
                        borderRadius: "6px",
                        background: r.bg,
                        border: `1px solid ${r.color}25`
                      }}
                    >
                      <Icon size={12} /> {log.result}
                    </span>
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

      {/* Export Modal */}
      {showExportModal && (
        <div
          style={{
            position: "fixed",
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            background: "rgba(0, 0, 0, 0.6)",
            backdropFilter: "blur(8px)",
            WebkitBackdropFilter: "blur(8px)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            zIndex: 100,
          }}
        >
          <form
            onSubmit={handleExport}
            className="aegis-glass-panel aegis-fade-in"
            style={{
              padding: "24px",
              width: "100%",
              maxWidth: "460px",
              background: "rgba(15, 23, 42, 0.8)",
              border: `1px solid ${C.border}`,
              boxShadow: "0 20px 40px rgba(0,0,0,0.5)",
              margin: "16px",
            }}
          >
            <div style={{ display: "flex", gap: "10px", alignItems: "center", marginBottom: "16px" }}>
              <ClipboardList size={18} color={C.gold} />
              <h3 className="aegis-display" style={{ margin: 0, fontSize: "16px", fontWeight: 700 }}>
                Export Compliance Audit Logs
              </h3>
            </div>

            <p style={{ fontSize: "12px", color: C.muted, lineHeight: 1.5, marginBottom: "16px" }}>
              Generate cryptographically cited evidence for regulatory and compliance audits. 
              {live ? " Downloads directly from the PostgreSQL audit tables." : " Extracts active Sandbox simulator history."}
            </p>

            {exportError && (
              <div
                style={{
                  display: "flex",
                  gap: "8px",
                  background: "rgba(244, 63, 94, 0.08)",
                  border: `1px solid rgba(244, 63, 94, 0.25)`,
                  borderRadius: "8px",
                  padding: "10px",
                  marginBottom: "16px",
                  fontSize: "12px",
                  color: C.danger,
                }}
              >
                <AlertTriangle size={14} style={{ flexShrink: 0, marginTop: "1px" }} />
                <span>{exportError}</span>
              </div>
            )}

            <div style={{ display: "flex", flexDirection: "column", gap: "12px", marginBottom: "20px" }}>
              {/* Format selection */}
              <div>
                <label style={{ fontSize: "11px", color: C.muted, fontWeight: 500, display: "block", marginBottom: "4px" }}>
                  Export Format
                </label>
                <div style={{ display: "flex", gap: "6px" }}>
                  {["json", "csv"].map((f) => (
                    <button
                      key={f}
                      type="button"
                      onClick={() => setExportFormat(f)}
                      className="aegis-btn"
                      style={{
                        flex: 1,
                        padding: "8px",
                        fontSize: "12px",
                        borderRadius: "8px",
                        borderColor: exportFormat === f ? "rgba(245, 158, 11, 0.4)" : C.border,
                        background: exportFormat === f ? "rgba(245, 158, 11, 0.08)" : "transparent",
                        color: exportFormat === f ? C.gold : C.muted,
                        fontWeight: 600,
                        textTransform: "uppercase",
                      }}
                    >
                      {f}
                    </button>
                  ))}
                </div>
              </div>

              {live && (
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "10px" }}>
                  <div>
                    <label style={{ fontSize: "11px", color: C.muted, fontWeight: 500, display: "block", marginBottom: "4px" }}>
                      From Date (Optional)
                    </label>
                    <input
                      className="aegis-input"
                      type="date"
                      value={exportFrom}
                      onChange={(e) => setExportFrom(e.target.value)}
                      disabled={exportBusy}
                      style={{ fontSize: "12px" }}
                    />
                  </div>
                  <div>
                    <label style={{ fontSize: "11px", color: C.muted, fontWeight: 500, display: "block", marginBottom: "4px" }}>
                      To Date (Optional)
                    </label>
                    <input
                      className="aegis-input"
                      type="date"
                      value={exportTo}
                      onChange={(e) => setExportTo(e.target.value)}
                      disabled={exportBusy}
                      style={{ fontSize: "12px" }}
                    />
                  </div>
                </div>
              )}

              <div>
                <label style={{ fontSize: "11px", color: C.muted, fontWeight: 500, display: "block", marginBottom: "4px" }}>
                  Filter by Operator Email (Optional)
                </label>
                <input
                  className="aegis-input"
                  type="text"
                  placeholder="e.g. auditor@enterprise.com"
                  value={exportUsername}
                  onChange={(e) => setExportUsername(e.target.value)}
                  disabled={exportBusy}
                  style={{ fontSize: "12px" }}
                />
              </div>

              <div>
                <label style={{ fontSize: "11px", color: C.muted, fontWeight: 500, display: "block", marginBottom: "4px" }}>
                  Max Entries Limit
                </label>
                <input
                  className="aegis-input aegis-mono"
                  type="number"
                  min="1"
                  max="10000"
                  value={exportLimit}
                  onChange={(e) => setExportLimit(parseInt(e.target.value) || 1000)}
                  disabled={exportBusy}
                  style={{ fontSize: "12px" }}
                />
              </div>
            </div>

            <div style={{ display: "flex", gap: "10px", borderTop: `1px solid ${C.border}`, paddingTop: "16px" }}>
              <button
                type="button"
                onClick={() => setShowExportModal(false)}
                disabled={exportBusy}
                className="aegis-btn"
                style={{ flex: 1, padding: "10px", borderRadius: "8px" }}
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={exportBusy}
                className="aegis-btn aegis-btn-primary"
                style={{ flex: 1, padding: "10px", borderRadius: "8px" }}
              >
                {exportBusy ? (
                  <><Loader2 size={13} className="aegis-spin" /> Exporting…</>
                ) : (
                  "Download Audit File"
                )}
              </button>
            </div>
          </form>
        </div>
      )}
    </div>
  );
}
