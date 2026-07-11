"""Auth0 Management API client for platform admin user provisioning.

This module provides the backend's interface to the Auth0 Management API for
the platform superuser provisioning paths.

The credentials used here belong to the infoDba Auth0 Machine-to-Machine
application. Expected scopes:
    read:users
    update:users
    create:users
    read:users_app_metadata
    update:users_app_metadata

Note: delete:users is NOT granted.
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

# Cache for the Management API token
_token_cache: tuple[str, float] | None = None


def _generate_random_password(length: int = 24) -> str:
    """Return a cryptographically random throwaway password to satisfy complexity requirements."""
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


async def _get_m2m_token() -> str:
    """Return a cached or newly fetched Auth0 Management API M2M token."""
    global _token_cache
    now = time.monotonic()
    if _token_cache is not None:
        token, expiry = _token_cache
        if now < expiry:
            return token

    settings = get_settings()
    domain = settings.auth0_domain
    client_id = settings.auth0_m2m_client_id
    client_secret = settings.auth0_m2m_client_secret

    if not client_id or not client_secret:
        raise RuntimeError(
            "Auth0 Management API M2M credentials missing from configuration."
        )

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            f"https://{domain}/oauth/token",
            json={
                "grant_type": "client_credentials",
                "client_id": client_id,
                "client_secret": client_secret,
                "audience": f"https://{domain}/api/v2/",
            }
        )

    if resp.status_code != 200:
        logger.error(
            "Auth0 Management token request failed: status=%d, body=%r",
            resp.status_code,
            resp.text[:200]
        )
        raise RuntimeError(f"Auth0 token request failed with status {resp.status_code}")

    data = resp.json()
    token = data["access_token"]
    expires_in = int(data.get("expires_in", 86400))
    _token_cache = (token, now + expires_in - 60)
    return token


async def create_auth0_user(
    email: str,
    org_id: str,
    roles: dict,
    display_name: str | None = None,
) -> dict:
    """Create a new user in Auth0's database connection.

    Sets app_metadata at creation time and triggers a password change ticket
    to act as an invite email.

    Returns the Auth0 response body which includes the user_id as 'user_id'.
    """
    settings = get_settings()
    token = await _get_m2m_token()

    app_metadata = {
        "org_id": org_id,
        "roles": roles,
    }

    payload: dict[str, Any] = {
        "connection": "Username-Password-Authentication",
        "email": email,
        "password": _generate_random_password(),
        "email_verified": False,
        "verify_email": False,
        "app_metadata": app_metadata,
    }
    if display_name:
        payload["name"] = display_name

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            f"https://{settings.auth0_domain}/api/v2/users",
            headers={"Authorization": f"Bearer {token}"},
            json=payload,
        )

    if resp.status_code == 409:
        raise ValueError(f"An Auth0 user with email {email!r} already exists.")

    resp.raise_for_status()
    data = resp.json()
    auth0_user_id = data["user_id"]

    # Trigger invite email (password change) via Auth0 Authentication API
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            email_resp = await client.post(
                f"https://{settings.auth0_domain}/dbconnections/change_password",
                json={
                    "client_id": settings.auth0_m2m_client_id,
                    "email": email,
                    "connection": "Username-Password-Authentication",
                }
            )
            email_resp.raise_for_status()
    except Exception as exc:
        logger.warning("Failed to trigger invite email: %s", exc)

    return {
        "user_id": auth0_user_id,
        **data
    }


async def sync_existing_user(auth0_sub: str, org_id: str, roles: dict) -> dict:
    """Fetch the current app_metadata of an existing user, then PATCH it.

    Returns the previous app_metadata.
    """
    settings = get_settings()
    token = await _get_m2m_token()

    # 1. Fetch current app_metadata
    async with httpx.AsyncClient(timeout=15.0) as client:
        get_resp = await client.get(
            f"https://{settings.auth0_domain}/api/v2/users/{auth0_sub}",
            headers={"Authorization": f"Bearer {token}"}
        )
        get_resp.raise_for_status()
        user_data = get_resp.json()
        previous_metadata = user_data.get("app_metadata", {})

    # 2. Patch new app_metadata
    new_metadata = {
        "org_id": org_id,
        "roles": roles,
    }
    async with httpx.AsyncClient(timeout=15.0) as client:
        patch_resp = await client.patch(
            f"https://{settings.auth0_domain}/api/v2/users/{auth0_sub}",
            headers={"Authorization": f"Bearer {token}"},
            json={"app_metadata": new_metadata}
        )
        patch_resp.raise_for_status()

    return previous_metadata


async def rollback_created_user(auth0_sub: str) -> None:
    """Compensate user creation.

    Since delete:users scope is not granted by design, we do not attempt the HTTP delete call.
    Instead, we log a critical warning indicating that manual cleanup of the orphaned Auth0 user is required.
    """
    logger.critical(
        "CRITICAL: Auth0 rollback required for created user %s but delete:users scope is not granted. "
        "The Auth0 user remains orphaned but inert in Auth0. Manual deletion required.",
        auth0_sub
    )


async def rollback_synced_user(auth0_sub: str, previous_metadata: dict) -> None:
    """Compensate metadata sync by patching the previous app_metadata back to Auth0."""
    settings = get_settings()
    try:
        token = await _get_m2m_token()
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.patch(
                f"https://{settings.auth0_domain}/api/v2/users/{auth0_sub}",
                headers={"Authorization": f"Bearer {token}"},
                json={"app_metadata": previous_metadata}
            )
            resp.raise_for_status()
        logger.info("Auth0 rollback successful: restored app_metadata for user %s", auth0_sub)
    except Exception as exc:
        logger.critical(
            "CRITICAL: Auth0 rollback (restore app_metadata) failed for %s. "
            "Attempted restore to previous state: %r. "
            "Auth0 user is now in an inconsistent state. Manual reconciliation required. "
            "Error: %s",
            auth0_sub,
            previous_metadata,
            exc
        )
