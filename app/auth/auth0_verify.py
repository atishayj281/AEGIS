"""RS256 JWT verification via Auth0 JWKS.

The frontend (Auth0 SDK) handles login and obtains an access_token.
Every API request carries that token as:
    Authorization: Bearer <access_token>

This module verifies the token against Auth0's public JWKS endpoint
and extracts the user context encoded in custom claims.

Expected custom claims (set by the "Add Roles Claim" Auth0 Action):
    https://aegis-api/org_id   → str
    https://aegis-api/team_ids → list[str]
    https://aegis-api/roles    → dict[str, str]  (team_id → role_name)
"""

import jwt
from fastapi import Header, HTTPException, status
from app.config import get_settings

# Namespace prefix used for custom JWT claims
CLAIMS_NAMESPACE = "https://aegis-api"


def verify_token(token: str) -> dict:
    """Verify an Auth0 RS256 token against the well-known JWKS endpoint.

    Returns a dict with keys: user_id, org_id, team_ids, roles.

    Raises jwt.PyJWTError on any verification failure.
    """
    settings = get_settings()
    url = f"https://{settings.auth0_domain}/.well-known/jwks.json"

    # Fresh client per call so tests can patch jwt.PyJWKClient cleanly.
    client = jwt.PyJWKClient(url)
    signing_key = client.get_signing_key_from_jwt(token)

    payload = jwt.decode(
        token,
        signing_key.key,
        algorithms=["RS256"],
        audience=settings.auth0_audience,
        issuer=f"https://{settings.auth0_domain}/",
    )

    payload_org_id = payload.get(f"{CLAIMS_NAMESPACE}/org_id")
    if not payload_org_id:
        raise jwt.InvalidTokenError("Token is missing required org_id claim")

    return {
        "user_id": payload.get("sub"),
        "org_id": payload_org_id,
        "team_ids": payload.get(f"{CLAIMS_NAMESPACE}/team_ids", []),
        "roles": payload.get(f"{CLAIMS_NAMESPACE}/roles", {}),
    }


async def get_current_context(authorization: str = Header(...)) -> dict:
    """FastAPI dependency: extract and verify the Bearer token."""
    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header must start with Bearer",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = authorization.split(" ", 1)[1]
    try:
        return verify_token(token)
    except jwt.PyJWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
            headers={"WWW-Authenticate": "Bearer"},
        ) from e