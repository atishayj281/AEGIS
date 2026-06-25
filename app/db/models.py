"""Database models and helpers for Phase 1 (SQLite-backed)."""

import json
import sqlite3
from pathlib import Path
from datetime import datetime, timezone
from app.config import get_settings

# SQLite schema for the bootstrap membership table
ORG_MEMBERS_SCHEMA = """
CREATE TABLE IF NOT EXISTS org_members (
    id TEXT PRIMARY KEY,
    auth0_user_id TEXT UNIQUE NOT NULL,
    org_id TEXT NOT NULL,
    team_ids TEXT NOT NULL, -- JSON array
    roles TEXT NOT NULL,    -- JSON object: team_id -> role
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_org_members_auth0_user_id ON org_members(auth0_user_id);
CREATE INDEX IF NOT EXISTS idx_org_members_org_id ON org_members(org_id);
"""

def init_db() -> None:
    """Initialize the org_members table in the SQLite database."""
    settings = get_settings()
    db_path = settings.sqlite_path
    db_path.parent.mkdir(parents=True, exist_ok=True)
    
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(ORG_MEMBERS_SCHEMA)
        conn.commit()
    finally:
        conn.close()

def get_org_membership(auth0_user_id: str) -> dict | None:
    """Look up organization membership for a given Auth0 user ID."""
    settings = get_settings()
    db_path = settings.sqlite_path
    init_db() # Ensure table exists
    
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT org_id, team_ids, roles FROM org_members WHERE auth0_user_id = ?",
            (auth0_user_id,)
        ).fetchone()
        
        if not row:
            return None
            
        return {
            "org_id": row["org_id"],
            "team_ids": json.loads(row["team_ids"]),
            "roles": json.loads(row["roles"])
        }
    finally:
        conn.close()

def create_org_member(member_id: str, auth0_user_id: str, org_id: str, team_ids: list, roles: dict) -> None:
    """Insert or update a member in the org_members table."""
    settings = get_settings()
    db_path = settings.sqlite_path
    init_db() # Ensure table exists
    
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            INSERT INTO org_members (id, auth0_user_id, org_id, team_ids, roles, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(auth0_user_id) DO UPDATE SET
                org_id=excluded.org_id,
                team_ids=excluded.team_ids,
                roles=excluded.roles
            """,
            (
                member_id,
                auth0_user_id,
                org_id,
                json.dumps(team_ids),
                json.dumps(roles),
                datetime.now(timezone.utc).isoformat()
            )
        )
        conn.commit()
    finally:
        conn.close()
