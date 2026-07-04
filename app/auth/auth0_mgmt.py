"""Auth0 Management API client for admin user provisioning.

This module is the backend's only interface to the Auth0 Management API.
It is used exclusively by the admin provisioning endpoints
(POST /admin/users, DELETE /admin/users/{id}) and never by request-path code.

The credentials used here belong to the **infoDba** Auth0 Machine-to-Machine
application. Required scopes on that application:

    create:users                 – POST /api/v2/users
    update:users                 – PATCH /api/v2/users/{id} (set app_metadata)
    delete:users                 – DELETE /api/v2/users/{id}
    create:organization_members  – POST /api/v2/organizations/{id}/members

Credentials are loaded exclusively from environment variables:
    AUTH0_M2M_CLIENT_ID      – logged at INFO level only as an 8-char prefix
    AUTH0_M2M_CLIENT_SECRET  – never logged, never returned in any response

Token caching
-------------
The Management API M2M token (~24h TTL) is cached per process instance with a
60-second safety buffer before expiry. Under multi-replica deployments each
replica maintains its own cache; that is intentional — the per-replica fetch
cost is negligible compared to a Redis round-trip and avoids a shared-cache
failure mode.

Compensation / rollback
-----------------------
`create_auth0_user` is the only function that creates state outside a Postgres
transaction. Callers (app/api/admin.py) are responsible for calling
`delete_auth0_user` if any subsequent step (including Postgres inserts) fails.
See app/api/admin.py for the full rollback sequence.
"""

from __future__ import annotations

import logging
import secrets
import string
import time
from typing import Any

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

# Module-level token cache: (access_token, expiry_monotonic_seconds)
_token_cache: tuple[str, float] | None = None


# ── Helpers ──────────────────────────────────────────────────────────────────


def _generate_random_password(length: int = 24) -> str:
    """Return a cryptographically random throwaway password.

    This password is used only to satisfy Auth0's complexity requirement when
    creating a Username-Password-Authentication user. It is never stored,
    never logged, and never returned to any caller. The user receives a
    password-change ticket separately and sets their own credential.

    Guarantees at least one uppercase, one lowercase, one digit, and one
    special character to satisfy Auth0's default policy.
    """
    special = "!@#$%^&*"
    alphabet = string.ascii_letters + string.digits + special
    required = [
        secrets.choice(string.ascii_uppercase),
        secrets.choice(string.ascii_lowercase),
        secrets.choice(string.digits),
        secrets.choice(special),
    ]
    rest = [secrets.choice(alphabet) for _ in range(length - len(required))]
    combined = required + rest
    secrets.SystemRandom().shuffle(combined)
    return "".join(combined)


async def _get_mgmt_token() -> str:
    """Return a valid Auth0 Management API access token, refreshing if needed.

    Raises RuntimeError if the M2M credentials are not configured or if the
    token endpoint returns a non-200 response.

    The client_id prefix (first 8 chars) is logged for traceability;
    the client_secret is never logged under any code path.
    """
    global _token_cache

    now = time.monotonic()
    if _token_cache is not None:
        cached_token, expiry = _token_cache
        if now < expiry:
            return cached_token

    settings = get_settings()
    domain = settings.auth0_domain
    client_id = settings.auth0_m2m_client_id
    client_secret = settings.auth0_m2m_client_secret

    if not client_id or not client_secret:
        raise RuntimeError(
            "infoDba M2M credentials missing. "
            "Set AUTH0_M2M_CLIENT_ID and AUTH0_M2M_CLIENT_SECRET in the environment. "
            f"(client_id configured: {bool(client_id)}, "
            f"client_secret configured: {bool(client_secret)})"
        )

    async with httpx.AsyncClient(timeout=10.0) as http:
        resp = await http.post(
            f"https://{domain}/oauth/token",
            json={
                "grant_type": "client_credentials",
                "client_id": client_id,
                "client_secret": client_secret,  # intentionally NOT logged
                "audience": f"https://{domain}/api/v2/",
            },
        )

    if resp.status_code != 200:
        logger.error(
            "Auth0 Management API token request failed: status=%d body_excerpt=%r "
            "client_id_prefix=%s",
            resp.status_code,
            resp.text[:200],
            client_id[:8],
        )
        raise RuntimeError(
            f"Auth0 Management API token request returned HTTP {resp.status_code}. "
            "Check infoDba M2M credentials and audience."
        )

    data = resp.json()
    token: str = data["access_token"]
    expires_in: int = int(data.get("expires_in", 86400))
    # Cache with a 60-second buffer so we never use a token that's about to expire
    _token_cache = (token, now + expires_in - 60)

    logger.info(
        "Auth0 Management API token obtained (expires_in=%ds, client_id_prefix=%s)",
        expires_in,
        client_id[:8],
    )
    return token


# ── Public API ────────────────────────────────────────────────────────────────


async def create_auth0_user(
    email: str,
    display_name: str,
    app_metadata: dict[str, Any],
) -> str:
    """Create a new user in Auth0's database connection.

    Sets app_metadata at creation time so the Post-Login Action can inject
    org_id / team_ids / roles into the JWT on the user's very first login
    without any backend round-trip.

    Returns the Auth0 user_id string (the JWT `sub` claim, e.g. "auth0|abc").

    Raises:
        ValueError   – if Auth0 returns 409 (email already registered).
        RuntimeError – if credentials are missing or token fetch fails.
        httpx.HTTPStatusError – for any other non-2xx Auth0 response.
    """
    settings = get_settings()
    token = await _get_mgmt_token()

    async with httpx.AsyncClient(timeout=15.0) as http:
        resp = await http.post(
            f"https://{settings.auth0_domain}/api/v2/users",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "connection": "Username-Password-Authentication",
                "email": email,
                "name": display_name,
                # Throwaway password; user will reset via password-change ticket.
                "password": _generate_random_password(),
                # Do not auto-send Auth0's default verification email.
                # We send a password-change ticket below (in the route handler)
                # which marks the email verified on click — cleaner UX.
                "email_verified": False,
                "verify_email": False,
                "app_metadata": app_metadata,
            },
        )

    if resp.status_code == 409:
        raise ValueError(
            f"An Auth0 user with email {email!r} already exists. "
            "Use the Management Dashboard to inspect or recover the existing account."
        )

    resp.raise_for_status()
    data = resp.json()
    auth0_user_id: str = data["user_id"]

    logger.info(
        "Auth0 user created: user_id_prefix=%s email=%s",
        auth0_user_id[:16],
        email,
    )
    return auth0_user_id


async def add_user_to_org(auth0_org_id: str, auth0_user_id: str) -> None:
    """Add an Auth0 user to an Auth0 Organization.

    Required scope on infoDba: create:organization_members.

    Auth0 Organizations enforce their own access control; adding a user here
    allows that user to authenticate under the org's SSO connection and
    branding. This call is made immediately after create_auth0_user so the
    user's JWT will carry the org context from their very first login.
    """
    settings = get_settings()
    token = await _get_mgmt_token()

    async with httpx.AsyncClient(timeout=15.0) as http:
        resp = await http.post(
            f"https://{settings.auth0_domain}/api/v2/organizations/{auth0_org_id}/members",
            headers={"Authorization": f"Bearer {token}"},
            json={"members": [auth0_user_id]},
        )

    resp.raise_for_status()
    logger.info(
        "Auth0 user %s added to org %s",
        auth0_user_id[:16],
        auth0_org_id,
    )


async def update_user_app_metadata(
    auth0_user_id: str,
    app_metadata: dict[str, Any],
) -> None:
    """Patch an Auth0 user's app_metadata.

    Required scope on infoDba: update:users.

    Used when a user's team/role assignment changes after initial provisioning,
    so that their next JWT (issued after their current token expires) reflects
    the updated membership.
    """
    settings = get_settings()
    token = await _get_mgmt_token()

    async with httpx.AsyncClient(timeout=15.0) as http:
        resp = await http.patch(
            f"https://{settings.auth0_domain}/api/v2/users/{auth0_user_id}",
            headers={"Authorization": f"Bearer {token}"},
            json={"app_metadata": app_metadata},
        )

    resp.raise_for_status()
    logger.info("Auth0 app_metadata updated: user_id_prefix=%s", auth0_user_id[:16])


async def delete_auth0_user(auth0_user_id: str) -> None:
    """Delete an Auth0 user account.

    Required scope on infoDba: delete:users.

    Auth0 automatically removes the user from all organizations and revokes
    all their sessions/refresh-tokens on deletion — no separate member-removal
    call is needed.

    This function is called in two scenarios:
    1. Compensation (rollback): POST /admin/users Auth0-created the user but
       the Postgres insert failed. The user is deleted to avoid a half-created
       state where an Auth0 account exists with no corresponding Postgres row.
    2. Deprovisioning: DELETE /admin/users/{id} — the Postgres row is already
       committed before this is called (Postgres-first for deprovision).

    A 404 response is treated as a no-op (idempotent) since the end state
    (user does not exist in Auth0) is already achieved.
    """
    settings = get_settings()
    token = await _get_mgmt_token()

    async with httpx.AsyncClient(timeout=15.0) as http:
        resp = await http.delete(
            f"https://{settings.auth0_domain}/api/v2/users/{auth0_user_id}",
            headers={"Authorization": f"Bearer {token}"},
        )

    if resp.status_code == 404:
        logger.warning(
            "Auth0 delete: user %s not found (already deleted or never created). "
            "Treating as success.",
            auth0_user_id[:16],
        )
        return

    resp.raise_for_status()
    logger.info("Auth0 user deleted: user_id_prefix=%s", auth0_user_id[:16])


async def send_password_change_ticket(auth0_user_id: str) -> None:
    """Send a set-password email to a newly created user.

    Required scope on infoDba: update:users (the ticket endpoint uses the same
    scope as PATCH /api/v2/users).

    The ticket URL itself is NOT returned to the caller — it is delivered
    only via Auth0's email channel. Auth0 marks the email as verified when
    the user clicks the link.

    This is called as a best-effort step after Postgres commit. If it fails,
    the user can request a password-reset link from Auth0's Universal Login
    page themselves. The failure does NOT roll back provisioning.
    """
    settings = get_settings()
    token = await _get_mgmt_token()

    async with httpx.AsyncClient(timeout=15.0) as http:
        resp = await http.post(
            f"https://{settings.auth0_domain}/api/v2/tickets/password-change",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "user_id": auth0_user_id,
                "mark_email_as_verified": True,
                # Do not embed the ticket URL in the redirect — the email
                # is the only delivery channel.
                "includeEmailInRedirect": False,
            },
        )

    resp.raise_for_status()
    logger.info(
        "Password-change ticket dispatched: user_id_prefix=%s",
        auth0_user_id[:16],
    )
