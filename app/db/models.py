"""Database initialization for the Enterprise RAG platform.

The org_members table and Auth0 Action callback helpers have been removed.
Auth0 custom claims (org_id, team_ids, roles) are now embedded directly
in the JWT by Auth0 Actions/Rules on the tenant — the backend reads them
from the token claims without any database lookup.
"""

import sqlite3
from app.config import get_settings


def init_db() -> None:
    """Initialize the SQLite database directory and file.

    No schema is created here currently; extend this function
    to set up any future application tables.
    """
    settings = get_settings()
    db_path = settings.sqlite_path
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(db_path)
    conn.close()
