import React, { useState, useEffect } from "react";
import {
  Users, UserPlus, Trash2, KeyRound, Mail, CheckCircle2, AlertTriangle,
  Loader2, ShieldAlert, FolderPlus, HelpCircle
} from "lucide-react";
import { C } from "./SmallComponents";

const VALID_ROLES = [
  { value: "org_admin", label: "Organization Administrator" },
  { value: "team_lead", label: "Team Lead" },
  { value: "compliance_officer", label: "Compliance Officer" },
  { value: "finance_analyst", label: "Finance Analyst" },
  { value: "operations_engineer", label: "Operations Engineer" },
  { value: "employee", label: "Standard Employee" },
  { value: "guest", label: "Guest (Restricted)" }
];

const ASSIGNABLE_ROLES = VALID_ROLES.filter(r => r.value !== "org_admin");

function decodeJwt(token) {
  try {
    const payload = token.split(".")[1];
    const json = atob(payload.replace(/-/g, "+").replace(/_/g, "/"));
    return JSON.parse(json);
  } catch { return {}; }
}

export default function AdminConsole({ live, apiBase, token, roleKey, onSessionExpired, apiClient }) {
  const [provisionedThisSession, setProvisionedThisSession] = useState([]);
  
  // Caller Identity & Role scoping
  const [isOrgAdmin, setIsOrgAdmin] = useState(false);
  const [isTeamLead, setIsTeamLead] = useState(false);
  
  // Form inputs
  const [displayName, setDisplayName] = useState("");
  const [email, setEmail] = useState("");
  const [role, setRole] = useState("employee");
  const [teamId, setTeamId] = useState("");
  
  // Team creation inputs
  const [newTeamName, setNewTeamName] = useState("");
  
  // Direct deprovision ID
  const [deprovisionId, setDeprovisionId] = useState("");
  
  // States
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [success, setSuccess] = useState(null);
  const [activeTab, setActiveTab] = useState("registry"); // 'registry' | 'provision' | 'create_team' | 'cleanup'

  // Extract org_id and team_id from JWT token in Live Mode
  useEffect(() => {
    if (live && token) {
      const claims = decodeJwt(token);
      const tokenTeamIds = claims["https://aegis-api/team_ids"] || claims["team_ids"] || [];
      const tokenTeamId = Array.isArray(tokenTeamIds) ? tokenTeamIds[0] : tokenTeamIds || "";
      
      const tokenRoles = claims["https://aegis-api/roles"] || claims["roles"] || {};
      const rolesValues = typeof tokenRoles === "object" ? Object.values(tokenRoles) : [];
      
      const adminClaim = rolesValues.includes("org_admin");
      const leadClaim = rolesValues.includes("team_lead");
      
      setIsOrgAdmin(adminClaim);
      setIsTeamLead(leadClaim);
      setTeamId(tokenTeamId);
    } else {
      // Mock configuration in demo mode
      setIsOrgAdmin(roleKey === "admin");
      setIsTeamLead(roleKey === "team_lead");
      setTeamId("94e2cb8f-28c0-43f1-bd21-0a41d911a3d0");
    }
  }, [live, token, roleKey]);

  const handleProvision = async (e) => {
    e.preventDefault();
    if (!email.trim() || !displayName.trim()) {
      setError("Please fill out all fields.");
      return;
    }
    
    // Team lead must have a team ID
    if (isTeamLead && !teamId.trim()) {
      setError("Team Lead callers must specify their Team UUID.");
      return;
    }
    
    setBusy(true);
    setError(null);
    setSuccess(null);
    
    if (!live) {
      // Simulate Provisioning locally
      setTimeout(() => {
        const emailLower = email.toLowerCase().trim();
        
        const newId = crypto.randomUUID();
        const newUser = {
          id: newId,
          display_name: displayName.trim(),
          email: emailLower,
          role: role,
          status: "active"
        };
        
        setProvisionedThisSession(prev => [newUser, ...prev]);
        setSuccess(`User "${displayName}" successfully provisioned in Sandbox! A verification invite was simulated.`);
        setDisplayName("");
        setEmail("");
        setBusy(false);
      }, 700);
      return;
    }
    
    try {
      const payload = {
        email: email.trim(),
        display_name: displayName.trim(),
        role: role,
        team_id: teamId.trim() || null
      };
      
      const res = await apiClient.orgProvisionUser(apiBase, token, payload);
      
      const newRecord = {
        id: res.id,
        display_name: res.display_name || displayName.trim(),
        email: res.email,
        role: res.role || role,
        status: "active"
      };
      
      setProvisionedThisSession(prev => [newRecord, ...prev]);
      setSuccess(`User successfully provisioned with ID ${res.id}. An invite ticket was sent.`);
      setDisplayName("");
      setEmail("");
    } catch (err) {
      if (err.status === 401) {
        onSessionExpired();
        return;
      }
      setError(err.message || "Failed to provision user.");
    } finally {
      setBusy(false);
    }
  };

  const handleCreateTeam = async (e) => {
    e.preventDefault();
    if (!newTeamName.trim()) {
      setError("Please specify a team name.");
      return;
    }
    
    setBusy(true);
    setError(null);
    setSuccess(null);
    
    if (!live) {
      setTimeout(() => {
        setSuccess(`Team "${newTeamName}" created in Sandbox!`);
        setNewTeamName("");
        setBusy(false);
      }, 600);
      return;
    }
    
    try {
      const res = await apiClient.orgCreateTeam(apiBase, token, { name: newTeamName.trim() });
      setSuccess(`Team "${res.name}" successfully created with ID ${res.id}.`);
      setNewTeamName("");
    } catch (err) {
      if (err.status === 401) {
        onSessionExpired();
        return;
      }
      setError(err.message || "Failed to create team.");
    } finally {
      setBusy(false);
    }
  };

  const handleDeactivate = async (userId, userEmail = "User") => {
    if (!window.confirm(`Are you sure you want to deactivate user ${userEmail}?`)) {
      return;
    }
    
    setBusy(true);
    setError(null);
    setSuccess(null);
    
    if (!live) {
      // Simulate Deactivation locally
      setTimeout(() => {
        setProvisionedThisSession(prev => prev.filter(u => u.id !== userId));
        setSuccess(`User "${userEmail}" deactivated in Sandbox.`);
        setBusy(false);
      }, 600);
      return;
    }
    
    try {
      await apiClient.orgDeactivateUser(apiBase, token, userId);
      setProvisionedThisSession(prev => prev.filter(u => u.id !== userId));
      setSuccess(`User successfully deactivated.`);
      if (deprovisionId === userId) {
        setDeprovisionId("");
      }
    } catch (err) {
      if (err.status === 401) {
        onSessionExpired();
        return;
      }
      setError(err.message || "Failed to deactivate user.");
    } finally {
      setBusy(false);
    }
  };

  const handleGDRPErase = async (userId, userEmail = "User") => {
    if (!window.confirm(`⚠️ WARNING: GDPR RIGHT TO ERASURE (Art 17) ⚠️\n\nThis will permanently delete ALL documents uploaded by this user, erase their complete query search history, and purge their audit trails.\n\nThis action is irreversible. Are you absolutely sure you want to proceed?`)) {
      return;
    }
    
    setBusy(true);
    setError(null);
    setSuccess(null);
    
    if (!live) {
      // Simulate GDPR Erasure locally
      setTimeout(() => {
        setProvisionedThisSession(prev => prev.filter(u => u.id !== userId));
        setSuccess(`GDPR right-to-erasure executed in Sandbox for ${userEmail}.`);
        setBusy(false);
      }, 800);
      return;
    }
    
    try {
      // Erase user data (org_admin only endpoint)
      const eraseRes = await apiClient.eraseUserData(apiBase, token, userId);
      setSuccess(`GDPR right-to-erasure completed successfully! ${eraseRes.message}`);
      if (deprovisionId === userId) {
        setDeprovisionId("");
      }
    } catch (err) {
      if (err.status === 401) {
        onSessionExpired();
        return;
      }
      setError(err.message || "Failed to execute GDPR erasure.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div style={{ height: "100%", display: "flex", flexDirection: "column" }} className="aegis-fade-in">
      <div style={{ padding: "20px 24px 0 24px" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "16px" }}>
          <div>
            <h2 className="aegis-display" style={{ margin: 0, fontSize: "20px", fontWeight: 700 }}>
              Org Provisions Console
            </h2>
            <p style={{ margin: "4px 0 0", fontSize: "12.5px", color: C.muted }}>
              Manage directory roles, provision new personnel, or deactivate user clearances.
            </p>
          </div>
        </div>

        {/* Success/Error Alerts */}
        {error && (
          <div style={{ display: "flex", gap: "8px", background: "rgba(239, 68, 68, 0.08)", border: `1px solid rgba(239, 68, 68, 0.3)`, borderRadius: "8px", padding: "10px 12px", marginBottom: "16px", fontSize: "12.5px", color: C.danger }}>
            <AlertTriangle size={15} style={{ flexShrink: 0, marginTop: "1px" }} />
            <span>{error}</span>
          </div>
        )}
        {success && (
          <div style={{ display: "flex", gap: "8px", background: "rgba(16, 185, 129, 0.08)", border: `1px solid rgba(16, 185, 129, 0.3)`, borderRadius: "8px", padding: "10px 12px", marginBottom: "16px", fontSize: "12.5px", color: C.success }}>
            <CheckCircle2 size={15} style={{ flexShrink: 0, marginTop: "1px" }} />
            <span>{success}</span>
          </div>
        )}

        {/* Horizontal Navigation */}
        <div style={{ display: "flex", gap: "6px", marginBottom: "16px" }}>
          {[
            { key: "registry", label: "User Registry" },
            { key: "provision", label: "Provision User" },
            isOrgAdmin && { key: "create_team", label: "Manage Teams" },
            { key: "cleanup", label: "Clearance Cleanup" }
          ].filter(Boolean).map((tabItem) => (
            <button
              key={tabItem.key}
              onClick={() => { setActiveTab(tabItem.key); setError(null); setSuccess(null); }}
              className="aegis-btn"
              style={{
                padding: "8px 14px",
                fontSize: "12px",
                borderRadius: "20px",
                borderColor: activeTab === tabItem.key ? "rgba(245, 158, 11, 0.4)" : C.border,
                background: activeTab === tabItem.key ? "rgba(245, 158, 11, 0.08)" : "transparent",
                color: activeTab === tabItem.key ? C.gold : C.muted
              }}
            >
              {tabItem.label}
            </button>
          ))}
        </div>
      </div>

      <div className="aegis-scroll" style={{ flex: 1, overflowY: "auto", padding: "0 24px 24px 24px" }}>
        
        {/* TAB 1: USER REGISTRY */}
        {activeTab === "registry" && (
          <div style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
            {provisionedThisSession.length === 0 ? (
              <div style={{ textAlign: "center", color: C.muted, padding: "40px", border: `1px dashed ${C.border}`, borderRadius: "12px" }}>
                <Users size={32} style={{ marginBottom: "12px", opacity: 0.5 }} />
                <div style={{ fontSize: "13.5px" }}>
                  No users provisioned in this session. Go to the <strong>Provision User</strong> tab to create new users.
                </div>
              </div>
            ) : (
              <div className="aegis-table-container">
                <div
                  className="aegis-table-header"
                  style={{
                    display: "grid",
                    gridTemplateColumns: "1.4fr 2fr 1.2fr 100px 110px",
                    padding: "12px 16px",
                    fontSize: "11px",
                    color: C.muted,
                    fontWeight: 600,
                    letterSpacing: "0.05em",
                  }}
                >
                  <div>DISPLAY NAME</div>
                  <div>EMAIL ADDRESS</div>
                  <div>ASSIGNED ROLE</div>
                  <div>STATUS</div>
                  <div style={{ textAlign: "right" }}>ACTIONS</div>
                </div>

                {provisionedThisSession.map((user) => (
                  <div
                    key={user.id}
                    className="aegis-row"
                    style={{
                      display: "grid",
                      gridTemplateColumns: "1.4fr 2fr 1.2fr 100px 110px",
                      padding: "12px 16px",
                      borderTop: `1px solid ${C.border}`,
                      fontSize: "13px",
                      alignItems: "center",
                    }}
                  >
                    <div style={{ fontWeight: 600, color: C.text }}>{user.display_name}</div>
                    <div style={{ color: C.muted, wordBreak: "break-all" }}>{user.email}</div>
                    <div>
                      <span
                        className="aegis-mono"
                        style={{
                          fontSize: "10px",
                          padding: "2px 6px",
                          borderRadius: "4px",
                          border: `1px solid rgba(255,255,255,0.06)`,
                          background: "rgba(255,255,255,0.02)",
                          color: C.gold,
                        }}
                      >
                        {user.role}
                      </span>
                    </div>
                    <div>
                      <span
                        style={{
                          fontSize: "11px",
                          fontWeight: 600,
                          color: C.success,
                          textTransform: "uppercase"
                        }}
                      >
                        ACTIVE
                      </span>
                    </div>
                    <div style={{ display: "flex", justifyContent: "flex-end", gap: "8px" }}>
                      {isOrgAdmin && (
                        <button
                          onClick={() => handleGDRPErase(user.id, user.email)}
                          disabled={busy}
                          title="GDPR Right to Erasure (Hard Purge)"
                          className="aegis-btn"
                          style={{
                            padding: "6px",
                            background: "transparent",
                            borderColor: "rgba(245, 158, 11, 0.2)",
                            borderRadius: "8px",
                            color: C.gold,
                            cursor: busy ? "not-allowed" : "pointer",
                          }}
                        >
                          <ShieldAlert size={13} />
                        </button>
                      )}
                      <button
                        onClick={() => handleDeactivate(user.id, user.email)}
                        disabled={busy}
                        title="Deactivate and Revoke Clearance"
                        className="aegis-btn"
                        style={{
                          padding: "6px",
                          background: "transparent",
                          borderColor: C.border,
                          borderRadius: "8px",
                          color: C.danger,
                          cursor: busy ? "not-allowed" : "pointer",
                        }}
                      >
                        <Trash2 size={13} />
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
            
            {live && (
              <div style={{ padding: "12px 16px", borderRadius: "10px", border: `1px solid ${C.border}`, background: C.panel, display: "flex", gap: "10px", alignItems: "flex-start" }}>
                <KeyRound size={16} color={C.gold} style={{ flexShrink: 0, marginTop: "2px" }} />
                <span style={{ fontSize: "11.5px", color: C.muted, lineHeight: "1.4" }}>
                  <strong>Security boundary notice:</strong> Organization directory lookups are protected. Only users provisioned during the current console session are shown above. Use the <strong>Clearance Cleanup</strong> tool to deactivate pre-existing accounts by UUID.
                </span>
              </div>
            )}
          </div>
        )}

        {/* TAB 2: PROVISION USER */}
        {activeTab === "provision" && (
          <form onSubmit={handleProvision} className="aegis-glass-panel" style={{ padding: "24px", maxWidth: "560px", margin: "10px auto" }}>
            <div style={{ display: "flex", gap: "10px", alignItems: "center", marginBottom: "18px" }}>
              <UserPlus size={18} color={C.gold} />
              <h3 className="aegis-display" style={{ margin: 0, fontSize: "16px", fontWeight: 700 }}>Provision New Directory Access</h3>
            </div>

            <div style={{ display: "flex", flexDirection: "column", gap: "14px", marginBottom: "20px" }}>
              <div>
                <label style={{ fontSize: "11.5px", color: C.muted, fontWeight: 500, display: "block", marginBottom: "4px" }}>Display Name</label>
                <input
                  className="aegis-input"
                  type="text"
                  required
                  placeholder="e.g. Alexis Carter"
                  value={displayName}
                  onChange={(e) => setDisplayName(e.target.value)}
                  disabled={busy}
                />
              </div>

              <div>
                <label style={{ fontSize: "11.5px", color: C.muted, fontWeight: 500, display: "block", marginBottom: "4px" }}>Email Address</label>
                <div style={{ position: "relative" }}>
                  <Mail size={14} color={C.muted} style={{ position: "absolute", left: "12px", top: "13px" }} />
                  <input
                     className="aegis-input"
                    type="email"
                    required
                    placeholder="alexis@example.com"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    disabled={busy}
                    style={{ paddingLeft: "34px" }}
                  />
                </div>
              </div>

              <div>
                <label style={{ fontSize: "11.5px", color: C.muted, fontWeight: 500, display: "block", marginBottom: "4px" }}>Clearance Role</label>
                <select
                  className="aegis-select"
                  value={role}
                  onChange={(e) => setRole(e.target.value)}
                  disabled={busy}
                >
                  {ASSIGNABLE_ROLES.map((r) => (
                    <option key={r.value} value={r.value}>{r.label}</option>
                  ))}
                </select>
              </div>

              <div>
                <label style={{ fontSize: "11.5px", color: C.muted, fontWeight: 500, display: "block", marginBottom: "4px" }}>
                  Team UUID {isTeamLead && <span style={{ color: C.danger }}>* (Required)</span>}
                </label>
                <input
                  className="aegis-input aegis-mono"
                  type="text"
                  required={isTeamLead}
                  placeholder={isOrgAdmin ? "e.g. uuid (optional, defaults to org-wide default team)" : "Enter UUID for a team you lead"}
                  value={teamId}
                  onChange={(e) => setTeamId(e.target.value)}
                  disabled={busy}
                  style={{ fontSize: "11.5px" }}
                />
                {!isOrgAdmin && (
                  <p style={{ fontSize: "10px", color: C.muted, marginTop: "4px" }}>
                    As a Team Lead, you can only provision users into teams you lead.
                  </p>
                )}
              </div>
            </div>

            <div style={{ display: "flex", justifyContent: "flex-end", gap: "10px", borderTop: `1px solid ${C.border}`, paddingTop: "16px" }}>
              <button
                type="submit"
                disabled={busy}
                className="aegis-btn aegis-btn-primary"
                style={{ width: "100%", padding: "11px" }}
              >
                {busy ? (
                  <><Loader2 size={15} className="aegis-spin" /> Provisioning atomically…</>
                ) : (
                  <><UserPlus size={14} /> Provision User Account</>
                )}
              </button>
            </div>
          </form>
        )}

        {/* TAB 3: CREATE TEAM (org_admin only) */}
        {activeTab === "create_team" && isOrgAdmin && (
          <form onSubmit={handleCreateTeam} className="aegis-glass-panel" style={{ padding: "24px", maxWidth: "560px", margin: "10px auto" }}>
            <div style={{ display: "flex", gap: "10px", alignItems: "center", marginBottom: "18px" }}>
              <FolderPlus size={18} color={C.gold} />
              <h3 className="aegis-display" style={{ margin: 0, fontSize: "16px", fontWeight: 700 }}>Create Org Team</h3>
            </div>

            <div style={{ display: "flex", flexDirection: "column", gap: "14px", marginBottom: "20px" }}>
              <div>
                <label style={{ fontSize: "11.5px", color: C.muted, fontWeight: 500, display: "block", marginBottom: "4px" }}>Team Name</label>
                <input
                  className="aegis-input"
                  type="text"
                  required
                  placeholder="e.g. Sales-APAC"
                  value={newTeamName}
                  onChange={(e) => setNewTeamName(e.target.value)}
                  disabled={busy}
                />
              </div>
            </div>

            <div style={{ display: "flex", justifyContent: "flex-end", borderTop: `1px solid ${C.border}`, paddingTop: "16px" }}>
              <button
                type="submit"
                disabled={busy}
                className="aegis-btn aegis-btn-primary"
                style={{ width: "100%", padding: "11px" }}
              >
                {busy ? (
                  <><Loader2 size={15} className="aegis-spin" /> Creating team…</>
                ) : (
                  <><FolderPlus size={14} /> Create Team</>
                )}
              </button>
            </div>
          </form>
        )}

        {/* TAB 4: CLEARANCE CLEANUP */}
        {activeTab === "cleanup" && (
          <div className="aegis-glass-panel" style={{ padding: "24px", maxWidth: "560px", margin: "10px auto" }}>
            <div style={{ display: "flex", gap: "10px", alignItems: "center", marginBottom: "18px" }}>
              <Trash2 size={18} color={C.danger} />
              <h3 className="aegis-display" style={{ margin: 0, fontSize: "16px", fontWeight: 700 }}>Revoke Directory Account</h3>
            </div>
            
            <p style={{ fontSize: "12.5px", color: C.muted, lineHeight: "1.5", marginBottom: "18px" }}>
              Deprovision or deactivate a user using their Postgres UUID.
            </p>

            <div style={{ display: "flex", flexDirection: "column", gap: "14px", marginBottom: "20px" }}>
              <div>
                <label style={{ fontSize: "11.5px", color: C.muted, fontWeight: 500, display: "block", marginBottom: "4px" }}>User Postgres UUID</label>
                <input
                  className="aegis-input aegis-mono"
                  type="text"
                  placeholder="e.g. d2f6eb8b-155d-45bf-a681-30d8c0b299e4"
                  value={deprovisionId}
                  onChange={(e) => setDeprovisionId(e.target.value)}
                  disabled={busy}
                  style={{ fontSize: "12.5px" }}
                />
              </div>
            </div>

            <div style={{ display: "flex", gap: "12px", borderTop: `1px solid ${C.border}`, paddingTop: "16px" }}>
              {isOrgAdmin && (
                <button
                  onClick={() => handleGDRPErase(deprovisionId, deprovisionId)}
                  disabled={busy || !deprovisionId.trim()}
                  className="aegis-btn aegis-btn-primary"
                  style={{ flex: 1, padding: "11px", borderColor: "rgba(245, 158, 11, 0.4)" }}
                >
                  {busy ? (
                    <><Loader2 size={15} className="aegis-spin" /> Erasing & Revoking…</>
                  ) : (
                    <><ShieldAlert size={14} /> GDPR Hard Purge</>
                  )}
                </button>
              )}
              <button
                onClick={() => handleDeactivate(deprovisionId, deprovisionId)}
                disabled={busy || !deprovisionId.trim()}
                className="aegis-btn aegis-btn-danger"
                style={{ flex: 1, padding: "11px" }}
              >
                {busy ? (
                  <><Loader2 size={15} className="aegis-spin" /> Deactivating…</>
                ) : (
                  <><Trash2 size={14} /> Deactivate Account</>
                )}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
