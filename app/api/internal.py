"""Internal lookup APIs for Auth0 Action authentication integration."""

from fastapi import APIRouter, Header, HTTPException, status
from app.config import get_settings
from app.db.models import get_org_membership

router = APIRouter()

@router.get("/internal/org-membership/{auth0_user_id}")
async def get_internal_org_membership(
    auth0_user_id: str,
    x_internal_secret: str = Header(None, alias="X-Internal-Secret")
):
    settings = get_settings()
    
    # Restrict endpoint usage to Auth0 Action using a shared secret
    expected_secret = getattr(settings, "internal_secret", None)
    if not expected_secret:
        # Fallback to direct environment query if setting isn't fully bound yet
        import os
        expected_secret = os.getenv("INTERNAL_SECRET")
        
    if not expected_secret or x_internal_secret != expected_secret:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized access to internal endpoint."
        )

    membership = get_org_membership(auth0_user_id)
    if not membership:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Organization membership not found for user: {auth0_user_id}"
        )
        
    return membership
