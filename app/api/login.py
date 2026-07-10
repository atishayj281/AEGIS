from fastapi import APIRouter, Depends
from app.api.deps import get_current_context, verify_platform_admin_row
from app.db.session import platform_admin_session
from pydantic import BaseModel

router = APIRouter()

class OrgScopedUserResponse(BaseModel):
    status: str = "org_scoped"
    user_id: str
    org_id: str
    roles: dict[str, str]
    team_ids: list[str]

class PlatformAdminResponse(BaseModel):
    status: str = "platform_admin"
    user_id: str

class UnprovisionedResponse(BaseModel):
    status: str = "unprovisioned"
    user_id: str

@router.get(
    "/login",
    response_model=OrgScopedUserResponse | PlatformAdminResponse | UnprovisionedResponse,
    summary="Resolve identity and return user status on login",
)
async def login_identity(
    context: dict = Depends(get_current_context),
):
    """Resolve identity state after post-login redirect.
    
    1. Org-scoped user: context["org_id"] is set.
    2. Platform admin: context["org_id"] is None, claims roles contains platform_admin, and row in platform_admins is active.
    3. Unprovisioned: valid signature but missing org_id and not a verified platform admin.
    """
    org_id = context.get("org_id")
    auth0_sub = context.get("user_id")
    roles = context.get("roles", {})
    team_ids = context.get("team_ids", [])
    
    # 1. Org-scoped user check
    if org_id is not None:
        return OrgScopedUserResponse(
            status="org_scoped",
            user_id=auth0_sub,
            org_id=str(org_id),
            roles=roles if isinstance(roles, dict) else {},
            team_ids=team_ids,
        )
        
    # Check if they claim to be platform_admin
    # roles may be a list (platform_admin claim) or a dict (team_id->role map).
    roles_list = roles
    if isinstance(roles_list, dict):
        roles_list = list(roles_list.values())
    elif not isinstance(roles_list, list):
        roles_list = [roles_list]
        
    is_platform_admin_claim = "platform_admin" in roles_list
    
    if is_platform_admin_claim:
        # Check active row in platform_admins DB table (authoritative layer)
        async with platform_admin_session() as session:
            is_active_platform_admin = await verify_platform_admin_row(session, auth0_sub)
            if is_active_platform_admin:
                return PlatformAdminResponse(
                    status="platform_admin",
                    user_id=auth0_sub,
                )
                
    # Default to unprovisioned
    return UnprovisionedResponse(
        status="unprovisioned",
        user_id=auth0_sub,
    )
