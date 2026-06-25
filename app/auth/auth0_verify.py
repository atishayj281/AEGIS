"""JWT Verification using Auth0 JWKS."""

import jwt
from fastapi import Header, HTTPException, status
from app.config import get_settings


def verify_token(token: str) -> dict:
    """Verify an Auth0 RS256 token against the well-known JWKS endpoint.

    Constructs a fresh PyJWKClient per call so that tests can patch
    jwt.PyJWKClient without hitting a cached singleton.
    """
    settings = get_settings()
    url = f"https://{settings.auth0_domain}/.well-known/jwks.json"
    try:
        client = jwt.PyJWKClient(url)
        signing_key = client.get_signing_key_from_jwt(token)

        # Decode and validate claims
        payload = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=settings.auth0_audience,
            issuer=f"https://{settings.auth0_domain}/",
        )

        namespace = "https://yourapp.com"
        return {
            "user_id": payload.get("sub"),
            "org_id": payload.get(f"{namespace}/org_id"),
            "team_ids": payload.get(f"{namespace}/team_ids", []),
            "roles": payload.get(f"{namespace}/roles", {}),
        }
    except jwt.PyJWTError:
        raise
    except Exception as e:
        raise jwt.PyJWTError(f"Token verification failed: {str(e)}") from e

async def get_current_context(authorization: str = Header(...)) -> dict:
    """FastAPI dependency to extract and verify the bearer token."""
    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header must start with Bearer",
            headers={"WWW-Authenticate": "Bearer"},
        )
        
    token = authorization.split(" ")[1]
    try:
        return verify_token(token)
    except jwt.PyJWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
            headers={"WWW-Authenticate": "Bearer"},
        ) from e
