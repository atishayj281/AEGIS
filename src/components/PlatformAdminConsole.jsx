import React, { useState, useEffect, useCallback } from "react";
import {
  Building2, Users, Database, Clock, Search, RefreshCw,
  AlertTriangle, Loader2, Plus, X, ChevronRight, ShieldCheck,
  ToggleLeft, ToggleRight, Trash2, ArrowLeft, UserPlus, CheckCircle2,
  Edit3, ShieldAlert,
} from "lucide-react";
import { C } from "./SmallComponents";

const PLATFORM_VALID_ROLES = [
  { value: "org_admin",           label: "Organization Administrator" },
  { value: "team_lead",           label: "Team Lead" },
  { value: "compliance_officer", label: "Compliance Officer" },
  { value: "finance_analyst",    label: "Finance Analyst" },
  { value: "operations_engineer",label: "Operations Engineer" },
  { value: "employee",           label: "Standard Employee" },
  { value: "guest",              label: "Guest (Restricted)" },
];

/* ─────────────────────────────────────────────
   Helpers
───────────────────────────────────────────── */

function slugify(name) {
  return name.toLowerCase().trim().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 100);
}

function formatDate(iso) {
  if (!iso) return "—";
  try { return new Date(iso).toLocaleString(); } catch { return iso; }
}

/* ─────────────────────────────────────────────
   Sub-components
───────────────────────────────────────────── */

function StatusBadge({ active, label }) {
  const color = active ? C.teal : C.muted;
  return (
    <span style={{
      fontSize: "9px", letterSpacing: "0.08em", padding: "2px 7px",
      borderRadius: "4px", border: `1px solid ${color}44`,
      color, background: `${color}0D`, fontWeight: 700, textTransform: "uppercase",
    }}>
      {label ?? (active ? "active" : "inactive")}
    </span>
  );
}

function Spinner({ size = 14 }) {
  return <Loader2 size={size} className="aegis-spin" color="#a855f7" />;
}

function ModalOverlay({ onClose, children }) {
  return (
    <div
      onClick={onClose}
      style={{
        position: "fixed", inset: 0, background: "rgba(0,0,0,0.65)",
        display: "flex", alignItems: "center", justifyContent: "center",
        zIndex: 1000, backdropFilter: "blur(4px)",
      }}
    >
      <div onClick={(e) => e.stopPropagation()} style={{
        background: "linear-gradient(135deg, rgba(15,23,42,0.98), rgba(22,33,58,0.98))",
        border: "1px solid rgba(255,255,255,0.10)", borderRadius: "16px",
        padding: "28px 32px", width: "100%", maxWidth: "480px",
        boxShadow: "0 24px 64px rgba(0,0,0,0.6)",
      }}>
        {children}
      </div>
    </div>
  );
}

function ModalHeader({ icon: Icon, title, onClose }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "22px" }}>
      <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
        <Icon size={18} color="#a855f7" />
        <h3 className="aegis-display" style={{ margin: 0, fontSize: "16px", fontWeight: 700 }}>{title}</h3>
      </div>
      <button onClick={onClose} style={{ background: "none", border: "none", cursor: "pointer", color: C.muted, padding: "2px" }}>
        <X size={16} />
      </button>
    </div>
  );
}

function FormField({ label, children, error }) {
  return (
    <div style={{ marginBottom: "16px" }}>
      <label style={{ fontSize: "11px", fontWeight: 600, color: C.muted, textTransform: "uppercase", letterSpacing: "0.06em", display: "block", marginBottom: "6px" }}>
        {label}
      </label>
      {children}
      {error && <div style={{ fontSize: "11px", color: C.danger, marginTop: "4px" }}>{error}</div>}
    </div>
  );
}

/* ─────────────────────────────────────────────
   Create Org Modal
───────────────────────────────────────────── */

function CreateOrgModal({ apiBase, token, apiClient, onCreated, onClose }) {
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [slugTouched, setSlugTouched] = useState(false);
  const [retentionDays, setRetentionDays] = useState("365");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const derivedSlug = slugTouched ? slug : slugify(name);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const org = await apiClient.createOrg(apiBase, token, {
        name: name.trim(),
        slug: derivedSlug || undefined,
        retention_days: parseInt(retentionDays, 10) || 365,
      });
      onCreated(org);
    } catch (err) {
      setError(err.message || "Failed to create organization.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <ModalOverlay onClose={onClose}>
      <ModalHeader icon={Building2} title="New Organization" onClose={onClose} />
      <form onSubmit={handleSubmit}>
        <FormField label="Organization Name *">
          <input
            className="aegis-input" autoFocus
            value={name} onChange={(e) => setName(e.target.value)}
            placeholder="e.g. Acme Corp" required style={{ fontSize: "13px" }}
          />
        </FormField>
        <FormField label="Slug (URL-safe ID)">
          <input
            className="aegis-input"
            value={derivedSlug}
            onChange={(e) => { setSlugTouched(true); setSlug(e.target.value); }}
            placeholder="auto-generated from name"
            style={{ fontSize: "13px", fontFamily: "monospace" }}
          />
          <div style={{ fontSize: "10px", color: C.muted, marginTop: "4px" }}>
            Lowercase letters, numbers and hyphens only.
          </div>
        </FormField>
        <FormField label="Data Retention (days)">
          <input
            className="aegis-input" type="number" min="1" max="3650"
            value={retentionDays} onChange={(e) => setRetentionDays(e.target.value)}
            style={{ fontSize: "13px" }}
          />
        </FormField>
        {error && (
          <div style={{ display: "flex", gap: "6px", alignItems: "center", color: C.danger, fontSize: "12px", marginBottom: "14px" }}>
            <AlertTriangle size={13} />{error}
          </div>
        )}
        <div style={{ display: "flex", gap: "10px", justifyContent: "flex-end" }}>
          <button type="button" onClick={onClose} className="aegis-btn" style={{ padding: "8px 16px", fontSize: "12px", background: "rgba(255,255,255,0.04)" }}>
            Cancel
          </button>
          <button type="submit" disabled={busy || !name.trim()} className="aegis-btn" style={{ padding: "8px 18px", fontSize: "12px", background: "linear-gradient(135deg, #7c3aed, #a855f7)" }}>
            {busy ? <Spinner size={12} /> : <><Plus size={12} /> Create Org</>}
          </button>
        </div>
      </form>
    </ModalOverlay>
  );
}

/* ─────────────────────────────────────────────
   Create User Modal
───────────────────────────────────────────── */

function CreateUserModal({ org, apiBase, token, apiClient, onCreated, onClose }) {
  const [email, setEmail] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const user = await apiClient.createUser(apiBase, token, org.id, {
        email: email.trim(),
        display_name: displayName.trim() || undefined,
      });
      onCreated(user);
    } catch (err) {
      setError(err.message || "Failed to provision user.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <ModalOverlay onClose={onClose}>
      <ModalHeader icon={UserPlus} title={`Add User to ${org.name}`} onClose={onClose} />
      <form onSubmit={handleSubmit}>
        <FormField label="Email *">
          <input
            className="aegis-input" type="email" autoFocus
            value={email} onChange={(e) => setEmail(e.target.value)}
            placeholder="user@company.com" required style={{ fontSize: "13px" }}
          />
        </FormField>
        <FormField label="Display Name">
          <input
            className="aegis-input"
            value={displayName} onChange={(e) => setDisplayName(e.target.value)}
            placeholder="Jane Doe (optional)" style={{ fontSize: "13px" }}
          />
        </FormField>
        {error && (
          <div style={{ display: "flex", gap: "6px", alignItems: "center", color: C.danger, fontSize: "12px", marginBottom: "14px" }}>
            <AlertTriangle size={13} />{error}
          </div>
        )}
        <div style={{ display: "flex", gap: "10px", justifyContent: "flex-end" }}>
          <button type="button" onClick={onClose} className="aegis-btn" style={{ padding: "8px 16px", fontSize: "12px", background: "rgba(255,255,255,0.04)" }}>
            Cancel
          </button>
          <button type="submit" disabled={busy || !email.trim()} className="aegis-btn" style={{ padding: "8px 18px", fontSize: "12px", background: "linear-gradient(135deg, #0d9488, #14b8a6)" }}>
            {busy ? <Spinner size={12} /> : <><UserPlus size={12} /> Provision User</>}
          </button>
        </div>
      </form>
    </ModalOverlay>
  );
}

/* ─────────────────────────────────────────────
   Change Role Modal
───────────────────────────────────────────── */

function ChangeRoleModal({ user, org, apiBase, token, apiClient, onChanged, onClose }) {
  const [selectedRole, setSelectedRole] = useState(user.role || "employee");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (selectedRole === user.role) {
      onClose();
      return;
    }
    setError(null);
    setBusy(true);
    try {
      const updated = await apiClient.updateUser(apiBase, token, org.id, user.id, { role: selectedRole });
      onChanged(updated);
    } catch (err) {
      setError(err.message || "Failed to change role.");
    } finally {
      setBusy(false);
    }
  };

  const currentRoleLabel = PLATFORM_VALID_ROLES.find(r => r.value === user.role)?.label ?? user.role ?? "None";

  return (
    <ModalOverlay onClose={onClose}>
      <ModalHeader icon={ShieldAlert} title="Change User Role" onClose={onClose} />

      <div style={{ marginBottom: "18px", padding: "12px 14px", borderRadius: "8px", background: "rgba(168,85,247,0.06)", border: "1px solid rgba(168,85,247,0.18)" }}>
        <div style={{ fontSize: "11px", color: C.muted, marginBottom: "4px", fontWeight: 600, letterSpacing: "0.04em" }}>TARGET USER</div>
        <div style={{ fontSize: "13px", fontWeight: 700, color: C.text }}>{user.display_name || user.email}</div>
        <div style={{ fontSize: "11px", color: C.muted }}>{user.email}</div>
        <div style={{ fontSize: "11px", color: C.muted, marginTop: "6px" }}>
          Current role: <span style={{ color: "#a855f7", fontFamily: "monospace" }}>{currentRoleLabel}</span>
        </div>
      </div>

      <form onSubmit={handleSubmit}>
        <FormField label="New Role *">
          <select
            className="aegis-select"
            value={selectedRole}
            onChange={(e) => setSelectedRole(e.target.value)}
            disabled={busy}
            style={{ fontSize: "13px" }}
          >
            {PLATFORM_VALID_ROLES.map((r) => (
              <option key={r.value} value={r.value}>{r.label}</option>
            ))}
          </select>
        </FormField>

        <div style={{
          marginBottom: "16px", padding: "10px 12px", borderRadius: "7px",
          background: "rgba(245,158,11,0.07)", border: "1px solid rgba(245,158,11,0.22)",
          fontSize: "11.5px", color: C.muted, lineHeight: "1.5",
        }}>
          <strong style={{ color: C.gold }}>⚠ Auth0 Sync:</strong> This will update Auth0
          app_metadata so the new role takes effect on the user's next login.
          Existing sessions will continue with the old role until they re-authenticate.
        </div>

        {error && (
          <div style={{ display: "flex", gap: "6px", alignItems: "center", color: C.danger, fontSize: "12px", marginBottom: "14px" }}>
            <AlertTriangle size={13} />{error}
          </div>
        )}
        <div style={{ display: "flex", gap: "10px", justifyContent: "flex-end" }}>
          <button type="button" onClick={onClose} className="aegis-btn" style={{ padding: "8px 16px", fontSize: "12px", background: "rgba(255,255,255,0.04)" }}>
            Cancel
          </button>
          <button type="submit" disabled={busy} className="aegis-btn" style={{ padding: "8px 18px", fontSize: "12px", background: "linear-gradient(135deg, #7c3aed, #a855f7)" }}>
            {busy ? <Spinner size={12} /> : <><Edit3 size={12} /> Apply Role Change</>}
          </button>
        </div>
      </form>
    </ModalOverlay>
  );
}


function OrgDetailPanel({ org, apiBase, token, apiClient, onOrgUpdated, onBack }) {
  const [users, setUsers] = useState([]);
  const [loadingUsers, setLoadingUsers] = useState(true);
  const [userError, setUserError] = useState(null);
  const [showAddUser, setShowAddUser] = useState(false);
  const [togglingUserId, setTogglingUserId] = useState(null);
  const [togglingOrg, setTogglingOrg] = useState(false);
  const [toast, setToast] = useState(null);
  const [changingRoleUser, setChangingRoleUser] = useState(null);

  const showToast = useCallback((msg, type = "success") => {
    setToast({ msg, type });
    setTimeout(() => setToast(null), 3000);
  }, []);

  const loadUsers = useCallback(async () => {
    setLoadingUsers(true);
    setUserError(null);
    try {
      const list = await apiClient.listOrgUsers(apiBase, token, org.id);
      setUsers(list);
    } catch (err) {
      setUserError(err.message || "Failed to load users.");
    } finally {
      setLoadingUsers(false);
    }
  }, [apiBase, token, org.id, apiClient]);

  useEffect(() => { loadUsers(); }, [loadUsers]);

  const handleToggleOrg = async () => {
    setTogglingOrg(true);
    try {
      if (org.is_active) {
        await apiClient.deactivateOrg(apiBase, token, org.id);
        onOrgUpdated({ ...org, is_active: false });
        showToast("Organization deactivated.");
      } else {
        const updated = await apiClient.updateOrg(apiBase, token, org.id, { is_active: true });
        onOrgUpdated(updated);
        showToast("Organization reactivated.");
      }
    } catch (err) {
      showToast(err.message || "Failed to update org.", "error");
    } finally {
      setTogglingOrg(false);
    }
  };

  const handleToggleUser = async (user) => {
    setTogglingUserId(user.id);
    try {
      if (user.is_active) {
        await apiClient.deactivateUser(apiBase, token, org.id, user.id);
        setUsers((prev) => prev.map((u) => u.id === user.id ? { ...u, is_active: false } : u));
        showToast(`${user.email} deactivated.`);
      } else {
        const updated = await apiClient.updateUser(apiBase, token, org.id, user.id, { is_active: true });
        setUsers((prev) => prev.map((u) => u.id === user.id ? updated : u));
        showToast(`${user.email} reactivated.`);
      }
    } catch (err) {
      showToast(err.message || "Failed to update user.", "error");
    } finally {
      setTogglingUserId(null);
    }
  };

  const handleUserCreated = (newUser) => {
    setUsers((prev) => [newUser, ...prev]);
    setShowAddUser(false);
    showToast(`${newUser.email} provisioned successfully.`);
  };

  const handleRoleChanged = (updatedUser) => {
    setUsers((prev) => prev.map((u) => u.id === updatedUser.id ? updatedUser : u));
    setChangingRoleUser(null);
    showToast(`Role updated for ${updatedUser.email}.`);
  };

  return (
    <div style={{ height: "100%", display: "flex", flexDirection: "column", position: "relative" }} className="aegis-fade-in">

      {/* Toast */}
      {toast && (
        <div style={{
          position: "absolute", top: "12px", right: "16px", zIndex: 100,
          display: "flex", alignItems: "center", gap: "8px",
          background: toast.type === "error" ? "rgba(244,63,94,0.12)" : "rgba(20,184,166,0.12)",
          border: `1px solid ${toast.type === "error" ? C.danger : C.teal}44`,
          borderRadius: "8px", padding: "8px 14px", fontSize: "12.5px",
          color: toast.type === "error" ? C.danger : C.teal,
        }}>
          <CheckCircle2 size={13} />
          {toast.msg}
        </div>
      )}

      {/* Header */}
      <div style={{ padding: "20px 24px 0 24px", flexShrink: 0 }}>
        <div style={{ display: "flex", alignItems: "center", gap: "10px", marginBottom: "16px" }}>
          <button onClick={onBack} style={{ background: "none", border: "none", cursor: "pointer", color: C.muted, display: "flex", alignItems: "center", gap: "4px", fontSize: "12px", padding: 0 }}>
            <ArrowLeft size={13} /> All Orgs
          </button>
        </div>

        {/* Org info card */}
        <div className="aegis-glass-panel" style={{ padding: "18px 20px", marginBottom: "20px", display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
          <div>
            <div style={{ display: "flex", alignItems: "center", gap: "10px", marginBottom: "4px" }}>
              <h3 className="aegis-display" style={{ margin: 0, fontSize: "18px", fontWeight: 700 }}>{org.name}</h3>
              <StatusBadge active={org.is_active} label={org.slug} />
            </div>
            <div className="aegis-mono" style={{ fontSize: "10px", color: C.muted }}>{org.id}</div>
          </div>
          <button
            onClick={handleToggleOrg}
            disabled={togglingOrg}
            className="aegis-btn"
            style={{
              padding: "7px 14px", fontSize: "11px", borderRadius: "8px",
              background: org.is_active ? "rgba(244,63,94,0.10)" : "rgba(20,184,166,0.10)",
              border: `1px solid ${org.is_active ? C.danger : C.teal}44`,
              color: org.is_active ? C.danger : C.teal,
              display: "flex", alignItems: "center", gap: "6px",
            }}
          >
            {togglingOrg ? <Spinner size={11} /> : org.is_active ? <><ToggleRight size={13} /> Deactivate</> : <><ToggleLeft size={13} /> Reactivate</>}
          </button>
        </div>

        {/* Users header */}
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "12px" }}>
          <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
            <Users size={14} color={C.muted} />
            <span style={{ fontSize: "12px", fontWeight: 600, color: C.muted, textTransform: "uppercase", letterSpacing: "0.06em" }}>
              Users {!loadingUsers && `(${users.length})`}
            </span>
          </div>
          <button
            onClick={() => setShowAddUser(true)}
            className="aegis-btn"
            style={{ padding: "6px 12px", fontSize: "11px", borderRadius: "7px", display: "flex", alignItems: "center", gap: "5px", background: "linear-gradient(135deg, rgba(20,184,166,0.15), rgba(20,184,166,0.08))", border: `1px solid ${C.teal}44`, color: C.teal }}
          >
            <UserPlus size={11} /> Add User
          </button>
        </div>
      </div>

      {/* Users list */}
      <div className="aegis-scroll" style={{ flex: 1, overflowY: "auto", padding: "0 24px 24px 24px" }}>
        {userError && (
          <div style={{ display: "flex", gap: "8px", color: C.danger, fontSize: "12.5px", padding: "10px 12px", background: "rgba(244,63,94,0.07)", border: `1px solid ${C.danger}30`, borderRadius: "8px", marginBottom: "12px" }}>
            <AlertTriangle size={14} /> {userError}
          </div>
        )}
        {loadingUsers ? (
          <div style={{ display: "flex", justifyContent: "center", marginTop: "40px", gap: "8px", color: C.muted, fontSize: "13px" }}>
            <Spinner /> Loading users…
          </div>
        ) : users.length === 0 ? (
          <div style={{ textAlign: "center", color: C.muted, marginTop: "40px", padding: "28px", border: `1px dashed ${C.border}`, borderRadius: "12px" }}>
            <UserPlus size={28} color={C.border} style={{ marginBottom: "8px" }} />
            <div style={{ fontSize: "13px" }}>No users in this organization yet.</div>
            <div style={{ fontSize: "11.5px", marginTop: "4px" }}>Use "Add User" to provision the first member.</div>
          </div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
            {users.map((user) => (
              <div key={user.id} className="aegis-glass-panel" style={{
                padding: "14px 16px", display: "flex", alignItems: "center",
                justifyContent: "space-between", gap: "12px",
                opacity: user.is_active ? 1 : 0.55, transition: "opacity 0.2s",
              }}>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ display: "flex", alignItems: "center", gap: "8px", marginBottom: "2px" }}>
                    <span style={{ fontWeight: 600, fontSize: "13px", color: C.text }}>
                      {user.display_name || user.email}
                    </span>
                    <StatusBadge active={user.is_active} />
                  </div>
                  <div style={{ fontSize: "11px", color: C.muted }}>{user.email}</div>
                  <div className="aegis-mono" style={{ fontSize: "9.5px", color: C.muted, marginTop: "2px", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {user.auth0_sub}
                  </div>
                </div>
                <div style={{ display: "flex", alignItems: "center", gap: "6px", flexShrink: 0 }}>
                  {/* Role badge */}
                  {user.role && (
                    <span style={{
                      fontSize: "9.5px", padding: "2px 7px", borderRadius: "4px",
                      border: "1px solid rgba(168,85,247,0.28)",
                      color: "#a855f7", background: "rgba(168,85,247,0.08)",
                      fontFamily: "monospace", fontWeight: 600, whiteSpace: "nowrap",
                    }}>
                      {user.role}
                    </span>
                  )}
                  <span style={{ fontSize: "10px", color: C.muted }}>
                    {formatDate(user.created_at).split(",")[0]}
                  </span>
                  {/* Change role button */}
                  <button
                    onClick={() => setChangingRoleUser(user)}
                    title="Change user role"
                    style={{
                      background: "none", border: "none", cursor: "pointer",
                      color: "#a855f7", padding: "4px",
                      display: "flex", alignItems: "center",
                    }}
                  >
                    <Edit3 size={13} />
                  </button>
                  {/* Toggle active button */}
                  <button
                    onClick={() => handleToggleUser(user)}
                    disabled={togglingUserId === user.id}
                    title={user.is_active ? "Deactivate user" : "Reactivate user"}
                    style={{
                      background: "none", border: "none", cursor: "pointer",
                      color: user.is_active ? C.danger : C.teal, padding: "4px",
                      display: "flex", alignItems: "center",
                    }}
                  >
                    {togglingUserId === user.id
                      ? <Spinner size={13} />
                      : user.is_active
                        ? <ToggleRight size={16} />
                        : <ToggleLeft size={16} />
                    }
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {showAddUser && (
        <CreateUserModal
          org={org}
          apiBase={apiBase}
          token={token}
          apiClient={apiClient}
          onCreated={handleUserCreated}
          onClose={() => setShowAddUser(false)}
        />
      )}

      {changingRoleUser && (
        <ChangeRoleModal
          user={changingRoleUser}
          org={org}
          apiBase={apiBase}
          token={token}
          apiClient={apiClient}
          onChanged={handleRoleChanged}
          onClose={() => setChangingRoleUser(null)}
        />
      )}
    </div>
  );
}

/* ─────────────────────────────────────────────
   Main Component
───────────────────────────────────────────── */

export default function PlatformAdminConsole({ live, apiBase, token, onSessionExpired, apiClient }) {
  const [orgs, setOrgs] = useState([]);
  const [summaries, setSummaries] = useState({});
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedOrg, setSelectedOrg] = useState(null);
  const [showCreateOrg, setShowCreateOrg] = useState(false);

  const MOCK_ORGS = [
    { id: "326f588d-71b5-4b08-8e6d-478cbef1a4c8", name: "Aegis Corporation (Primary)", slug: "aegis-corp", is_active: true, created_at: "2025-01-01T00:00:00Z" },
    { id: "98e4cf1a-478c-4b08-8e6d-326f588d71b5", name: "Apex Financial Group", slug: "apex-financial", is_active: true, created_at: "2025-03-15T00:00:00Z" },
    { id: "4f8cbd91-c0a4-11ef-bd21-0a41d911a3d0", name: "Cyberdyne Systems", slug: "cyberdyne", is_active: false, created_at: "2025-06-01T00:00:00Z" },
  ];

  const loadData = useCallback(async (isRefresh = false) => {
    if (isRefresh) setRefreshing(true);
    else setLoading(true);
    setError(null);

    if (!live) {
      setTimeout(() => { setOrgs(MOCK_ORGS); setLoading(false); setRefreshing(false); }, 600);
      return;
    }

    try {
      const orgList = await apiClient.listAllOrgs(apiBase, token);
      setOrgs(orgList);

      // Fetch summaries in parallel (non-blocking — don't let one failure kill all cards)
      const summaryResults = await Promise.allSettled(
        orgList.map(async (org) => {
          const detail = await apiClient.getOrgSummary(apiBase, token, org.id);
          return { orgId: org.id, detail };
        })
      );
      const summaryMap = {};
      summaryResults.forEach((r) => {
        if (r.status === "fulfilled") summaryMap[r.value.orgId] = r.value.detail;
      });
      setSummaries(summaryMap);
    } catch (err) {
      if (err.status === 401) { onSessionExpired(); return; }
      setError(err.message || "Failed to load platform registry data.");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [live, token, apiBase, apiClient, onSessionExpired]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { loadData(); }, [loadData]);

  const handleOrgCreated = (newOrg) => {
    setOrgs((prev) => [newOrg, ...prev].sort((a, b) => a.name.localeCompare(b.name)));
    setShowCreateOrg(false);
    setSelectedOrg(newOrg);
  };

  const handleOrgUpdated = (updatedOrg) => {
    setOrgs((prev) => prev.map((o) => o.id === updatedOrg.id ? updatedOrg : o));
    setSelectedOrg(updatedOrg);
  };

  const filteredOrgs = orgs.filter((org) => {
    const q = searchQuery.toLowerCase().trim();
    return !q || org.name.toLowerCase().includes(q) || org.id.toLowerCase().includes(q) || (org.slug || "").toLowerCase().includes(q);
  });

  // ── If an org is selected, show detail panel ──
  if (selectedOrg) {
    return (
      <OrgDetailPanel
        key={selectedOrg.id}
        org={selectedOrg}
        apiBase={apiBase}
        token={token}
        apiClient={apiClient}
        onOrgUpdated={handleOrgUpdated}
        onBack={() => setSelectedOrg(null)}
      />
    );
  }

  // ── Org list view ──
  return (
    <div style={{ height: "100%", display: "flex", flexDirection: "column" }} className="aegis-fade-in">
      {/* Header */}
      <div style={{ padding: "20px 24px 0 24px", flexShrink: 0 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "16px" }}>
          <div>
            <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
              <ShieldCheck size={22} color="#a855f7" />
              <h2 className="aegis-display" style={{ margin: 0, fontSize: "20px", fontWeight: 700 }}>Platform Superuser Dashboard</h2>
            </div>
            <p style={{ margin: "4px 0 0", fontSize: "12.5px", color: C.muted }}>
              Global control registry of cross-organization databases. Row-Level Security bypassed.
            </p>
          </div>
          <div style={{ display: "flex", gap: "8px" }}>
            <button onClick={() => setShowCreateOrg(true)} className="aegis-btn" style={{ padding: "8px 14px", fontSize: "12px", borderRadius: "8px", display: "flex", alignItems: "center", gap: "6px", background: "linear-gradient(135deg, rgba(168,85,247,0.15), rgba(168,85,247,0.08))", border: "1px solid rgba(168,85,247,0.3)", color: "#a855f7" }}>
              <Plus size={13} /> New Org
            </button>
            <button onClick={() => loadData(true)} disabled={loading || refreshing} className="aegis-btn" style={{ padding: "8px 12px", fontSize: "12px", borderRadius: "8px" }}>
              <RefreshCw size={12} className={refreshing ? "aegis-spin" : ""} /> Sync
            </button>
          </div>
        </div>

        {error && (
          <div style={{ display: "flex", gap: "8px", background: "rgba(244,63,94,0.08)", border: `1px solid rgba(244,63,94,0.25)`, borderRadius: "8px", padding: "10px 12px", marginBottom: "16px", fontSize: "12.5px", color: C.danger }}>
            <AlertTriangle size={15} style={{ flexShrink: 0, marginTop: "1px" }} />
            <span>{error}</span>
          </div>
        )}

        <div style={{ position: "relative", marginBottom: "20px" }}>
          <Search size={14} color={C.muted} style={{ position: "absolute", left: "12px", top: "11px" }} />
          <input
            className="aegis-input" type="text"
            placeholder="Search organizations by name, slug or UUID registry ID…"
            value={searchQuery} onChange={(e) => setSearchQuery(e.target.value)}
            style={{ paddingLeft: "34px", fontSize: "13px" }}
          />
        </div>
      </div>

      {/* Org grid */}
      <div className="aegis-scroll" style={{ flex: 1, overflowY: "auto", padding: "0 24px 24px 24px" }}>
        {loading ? (
          <div style={{ display: "flex", alignItems: "center", gap: "8px", color: C.muted, fontSize: "13.5px", marginTop: "40px", justifyContent: "center" }}>
            <Spinner /> Loading tenant registry…
          </div>
        ) : filteredOrgs.length === 0 ? (
          <div style={{ textAlign: "center", color: C.muted, marginTop: "40px", padding: "24px", border: `1px dashed ${C.border}`, borderRadius: "12px" }}>
            {orgs.length === 0
              ? <>No registered organizations yet. <button onClick={() => setShowCreateOrg(true)} style={{ background: "none", border: "none", cursor: "pointer", color: "#a855f7", textDecoration: "underline", padding: 0, fontSize: "inherit" }}>Create the first one →</button></>
              : "No organizations matching search query."
            }
          </div>
        ) : (
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(320px, 1fr))", gap: "16px" }}>
            {filteredOrgs.map((org) => {
              const summary = summaries[org.id];
              const statusColor = org.is_active ? C.teal : C.muted;
              return (
                <div
                  key={org.id}
                  className="aegis-glass-panel"
                  onClick={() => setSelectedOrg(org)}
                  style={{
                    padding: "20px", cursor: "pointer",
                    border: `1px solid rgba(255,255,255,0.06)`,
                    background: "rgba(15,23,42,0.35)",
                    transition: "all 0.18s ease",
                    display: "flex", flexDirection: "column",
                    justifyContent: "space-between",
                    position: "relative", overflow: "hidden",
                    opacity: org.is_active ? 1 : 0.65,
                  }}
                >
                  <div style={{ position: "absolute", width: "120px", height: "120px", background: `radial-gradient(circle, ${statusColor}09 0%, transparent 70%)`, top: "-20px", right: "-20px", pointerEvents: "none" }} />

                  <div>
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: "10px", marginBottom: "6px" }}>
                      <h4 className="aegis-display" style={{ margin: 0, fontSize: "15px", fontWeight: 700, color: C.text }}>{org.name}</h4>
                      <StatusBadge active={org.is_active} label={org.slug} />
                    </div>
                    <div className="aegis-mono" style={{ fontSize: "9.5px", color: C.muted, marginBottom: "16px", wordBreak: "break-all" }}>
                      {org.id}
                    </div>
                  </div>

                  <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "10px", borderTop: `1px solid ${C.border}`, paddingTop: "12px", marginBottom: "12px" }}>
                    {[
                      { icon: Users, label: "USERS", value: summary?.user_count ?? "—" },
                      { icon: Database, label: "DOCS", value: summary?.document_count ?? "—" },
                    ].map(({ icon: Icon, label, value }) => (
                      <div key={label} style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                        <div style={{ width: "28px", height: "28px", borderRadius: "7px", background: "rgba(255,255,255,0.02)", display: "flex", alignItems: "center", justifyContent: "center", border: `1px solid ${C.border}` }}>
                          <Icon size={12} color={C.muted} />
                        </div>
                        <div>
                          <div style={{ fontSize: "9px", color: C.muted, fontWeight: 500 }}>{label}</div>
                          <div style={{ fontSize: "14px", fontWeight: 700, color: C.text }}>{value}</div>
                        </div>
                      </div>
                    ))}
                  </div>

                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                    <div style={{ display: "flex", alignItems: "center", gap: "5px", fontSize: "10.5px", color: C.muted }}>
                      <Clock size={10} />
                      {summary?.last_activity ? formatDate(summary.last_activity) : "No activity yet"}
                    </div>
                    <div style={{ display: "flex", alignItems: "center", gap: "4px", fontSize: "11px", color: "#a855f7" }}>
                      Manage <ChevronRight size={12} />
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {showCreateOrg && (
        <CreateOrgModal
          apiBase={apiBase}
          token={token}
          apiClient={apiClient}
          onCreated={handleOrgCreated}
          onClose={() => setShowCreateOrg(false)}
        />
      )}
    </div>
  );
}
