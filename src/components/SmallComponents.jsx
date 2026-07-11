import React from "react";
import {
  Shield,
  ShieldCheck,
  ClipboardList,
  Database,
  DollarSign,
  Activity,
  Lock,
  FileText,
  FileSearch,
  Wifi,
  WifiOff,
  Sparkles,
  Loader2,
} from "lucide-react";

export const DEFAULT_API_BASE = "http://localhost:8000";

export const INJECTION_PATTERN = /ignore (all |previous |any )?instructions|reveal (all|confidential|hidden)|bypass (security|policies|rbac|permissions)|display hidden|system prompt|act as (an? )?(admin|root)|disable (rbac|security|filters)/i;

/* Colors Palette */
export const C = {
  bg: "#030712",
  panel: "rgba(15, 23, 42, 0.45)",
  panel2: "rgba(30, 41, 59, 0.6)",
  border: "rgba(255, 255, 255, 0.08)",
  borderSoft: "rgba(255, 255, 255, 0.04)",
  gold: "#f59e0b",
  teal: "#06b6d4",
  text: "#f3f4f6",
  muted: "#9ca3af",
  success: "#10b981",
  danger: "#f43f5e",
  info: "#3b82f6",
};

/* Data categories in alignment with backend DataSource Enum */
export const CATEGORIES = {
  pdf_documents: { label: "PDF Documents", icon: FileSearch, classification: "INTERNAL" },
  compliance_records: { label: "Compliance Records", icon: ShieldCheck, classification: "CONFIDENTIAL" },
  audit_logs: { label: "Audit Logs", icon: ClipboardList, classification: "RESTRICTED" },
  financial_database: { label: "Financial Database", icon: Database, classification: "CONFIDENTIAL" },
  invoice_records: { label: "Invoice Records", icon: DollarSign, classification: "CONFIDENTIAL" },
  budget_reports: { label: "Budget Reports", icon: ClipboardList, classification: "CONFIDENTIAL" },
  monitoring_logs: { label: "Monitoring Logs", icon: ClipboardList, classification: "RESTRICTED" },
  infrastructure_reports: { label: "Infrastructure Reports", icon: FileSearch, classification: "CONFIDENTIAL" },
  system_metrics: { label: "System Metrics", icon: Activity, classification: "INTERNAL" },
  operational_datasets: { label: "Operational Datasets", icon: Activity, classification: "INTERNAL" },
  public_policies: { label: "Public Policies", icon: FileText, classification: "PUBLIC" },
  internal_documentation: { label: "Internal Documentation", icon: FileText, classification: "INTERNAL" },
  salary_records: { label: "Salary Records", icon: Lock, classification: "RESTRICTED" },
};

const CATEGORY_FALLBACK = { label: "Unclassified Source", icon: FileSearch, classification: "INTERNAL" };

export const CLASSIFICATION_COLOR = {
  PUBLIC: C.success,
  INTERNAL: C.info,
  CONFIDENTIAL: C.gold,
  RESTRICTED: C.danger,
};

export function categoryInfo(key) {
  return CATEGORIES[key] || CATEGORY_FALLBACK;
}

/* Roles with specific data sources categories, fully mapping backend ROLE_PERMISSIONS */
export const ROLES = {
  platform_admin: {
    label: "Platform Superuser",
    categories: Object.keys(CATEGORIES),
    accent: "#a855f7",
  },
  admin: {
    label: "Administrator",
    categories: Object.keys(CATEGORIES),
    accent: C.gold,
  },
  team_lead: {
    label: "Team Lead",
    categories: Object.keys(CATEGORIES),
    accent: "#ec4899",
  },
  compliance_officer: {
    label: "Compliance Officer",
    categories: ["compliance_records", "audit_logs", "pdf_documents", "public_policies"],
    accent: C.info,
  },
  finance_analyst: {
    label: "Finance Analyst",
    categories: ["financial_database", "invoice_records", "budget_reports", "public_policies"],
    accent: C.success,
  },
  operations_engineer: {
    label: "Operations Engineer",
    categories: ["monitoring_logs", "infrastructure_reports", "system_metrics", "operational_datasets", "audit_logs", "public_policies"],
    accent: C.teal,
  },
  employee: {
    label: "Employee",
    categories: ["public_policies", "internal_documentation"],
    accent: C.muted,
  },
};

export function normalizeRole(rawRole, username) {
  const s = `${rawRole || ""} ${username || ""}`.toLowerCase();
  if (s.includes("platform_admin")) return "platform_admin";
  if (s.includes("org_admin") || s.includes("admin")) return "admin";
  if (s.includes("team_lead") || s.includes("lead")) return "team_lead";
  if (s.includes("compliance")) return "compliance_officer";
  if (s.includes("finance")) return "finance_analyst";
  if (s.includes("ops") || s.includes("operation") || s.includes("engineer")) return "operations_engineer";
  if (s.includes("employee")) return "employee";
  return "employee";
}

export function confidenceColor(score) {
  if (score >= 0.9 || score >= 90) return C.success;
  if (score >= 0.75 || score >= 75) return C.gold;
  return C.danger;
}

export function ClassificationBadge({ classification }) {
  const color = CLASSIFICATION_COLOR[classification] || C.muted;
  return (
    <span
      className="aegis-mono"
      style={{
        fontSize: "10px",
        letterSpacing: "0.08em",
        padding: "3px 8px",
        borderRadius: "6px",
        border: `1px solid ${color}44`,
        color,
        background: `${color}0F`,
        backdropFilter: "blur(4px)",
        fontWeight: 600,
        whiteSpace: "nowrap",
      }}
    >
      {classification}
    </span>
  );
}

export function ConfidenceBar({ score }) {
  if (score === null || score === undefined) {
    return <span className="aegis-mono" style={{ fontSize: "11px", color: C.muted }}>n/a</span>;
  }
  
  // Normalize percentage vs float (0.0 - 1.0)
  const isPercentage = score > 1.0;
  const percent = isPercentage ? score : score * 100;
  const displayScore = isPercentage ? Math.round(score) : Math.round(score * 100);
  const color = confidenceColor(isPercentage ? score : score * 100);
  
  return (
    <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
      <div style={{ width: "80px", height: "6px", borderRadius: "3px", background: "rgba(255,255,255,0.05)", overflow: "hidden" }}>
        <div style={{ width: `${Math.max(0, Math.min(100, percent))}%`, height: "100%", background: color, borderRadius: "3px" }} />
      </div>
      <span className="aegis-mono" style={{ fontSize: "11.5px", color, fontWeight: 600 }}>{displayScore}%</span>
    </div>
  );
}

export function RoleBadge({ roleKey, username }) {
  const role = ROLES[roleKey];
  if (!role) return null;
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: "10px",
        padding: "8px 12px",
        border: `1px solid rgba(255, 255, 255, 0.06)`,
        borderRadius: "12px",
        background: "rgba(255, 255, 255, 0.02)",
        backdropFilter: "blur(6px)",
        boxShadow: "0 4px 12px rgba(0, 0, 0, 0.1)",
      }}
    >
      <div
        style={{
          width: "26px",
          height: "26px",
          borderRadius: "8px",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          background: `${role.accent}14`,
          border: `1px solid ${role.accent}40`,
        }}
      >
        <Shield size={14} color={role.accent} />
      </div>
      <div style={{ overflow: "hidden", lineHeight: "1.2" }}>
        <div className="aegis-mono" style={{ fontSize: "9px", color: C.muted, letterSpacing: "0.06em", fontWeight: 600 }}>
          {role.label.toUpperCase()}
        </div>
        <div style={{ fontSize: "12px", fontWeight: 500, overflow: "hidden", textOverflow: "ellipsis", color: C.text, marginTop: "1px" }}>
          {username}
        </div>
      </div>
    </div>
  );
}

export function ConnectionPill({ status, apiBase }) {
  const map = {
    connected: { color: C.success, icon: Wifi, label: "Connected" },
    error: { color: C.danger, icon: WifiOff, label: "Unreachable" },
    demo: { color: C.muted, icon: Sparkles, label: "Sandbox mode" },
    checking: { color: C.muted, icon: Loader2, label: "Checking…" },
  };
  const m = map[status] || map.demo;
  const Icon = m.icon;
  return (
    <div
      title={apiBase}
      style={{
        display: "flex",
        alignItems: "center",
        gap: "6px",
        fontSize: "11px",
        color: m.color,
        fontWeight: 500,
        padding: "6px 10px",
        borderRadius: "10px",
        background: `${m.color}0A`,
        border: `1px solid ${m.color}20`,
        backdropFilter: "blur(4px)",
      }}
    >
      <Icon size={12} className={status === "checking" ? "aegis-spin" : ""} /> {m.label}
    </div>
  );
}

export function maskSensitive(text) {
  if (typeof text !== "string") return text;
  return text
    .replace(/api[_-]?key\s*[:=]\s*\S+/gi, "API_KEY=************")
    .replace(/(db[_-]?)?password\s*[:=]\s*\S+/gi, "PASSWORD=************")
    .replace(/\b\d{3}-\d{2}-\d{4}\b/g, "XXX-XX-####")
    .replace(/\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b/g, "[EMAIL_REDACTED]");
}
