"""User context model for the RAG platform.

Auth0 authentication is handled entirely on the frontend.
The backend only validates the RS256 JWT that the frontend passes
as a Bearer token (see app/auth/auth0_verify.py).
"""

import uuid

class User:
    """Represents an authenticated user extracted from an Auth0 JWT."""

    def __init__(
        self,
        username: str,
        db_id: uuid.UUID | None = None,
        department: str = "General",
        org_id: str | None = None,
        team_ids: list[str] | None = None,
        roles: dict[str, str] | None = None,
    ):
        self.username = username
        self.db_id = db_id
        self.department = department
        self.org_id = org_id
        self.team_ids = team_ids or []
        self.roles = roles or {}
