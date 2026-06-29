"""Seeding script to populate Postgres database with test organizations, teams, users, and memberships.

Creates:
- Acme Corp and Globex Inc
- Several teams under each organization
- 7 different roles assigned to test users
"""
import asyncio
import sys
from pathlib import Path
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db.session import get_session_factory


async def seed():
    print("Seeding database...")
    session_factory = get_session_factory()
    
    org_acme_id = "00000000-0000-0000-0000-000000000001"
    org_globex_id = "00000000-0000-0000-0000-000000000002"
    
    team_eng_id = "10000000-0000-0000-0000-000000000001"
    team_hr_id = "10000000-0000-0000-0000-000000000002"
    team_finance_id = "10000000-0000-0000-0000-000000000003"
    team_globex_id = "20000000-0000-0000-0000-000000000001"
    
    # User auth0 sub mapping to predictable DB UUIDs
    users_data = [
        {"id": "30000000-0000-0000-0000-000000000001", "org_id": org_acme_id, "auth0_sub": "auth0|admin", "email": "admin@acme.com", "display_name": "Acme Admin"},
        {"id": "30000000-0000-0000-0000-000000000002", "org_id": org_acme_id, "auth0_sub": "auth0|lead", "email": "lead@acme.com", "display_name": "Acme Lead"},
        {"id": "30000000-0000-0000-0000-000000000003", "org_id": org_acme_id, "auth0_sub": "auth0|compliance", "email": "compliance@acme.com", "display_name": "Acme Compliance"},
        {"id": "30000000-0000-0000-0000-000000000004", "org_id": org_acme_id, "auth0_sub": "auth0|finance", "email": "finance@acme.com", "display_name": "Acme Finance"},
        {"id": "30000000-0000-0000-0000-000000000005", "org_id": org_acme_id, "auth0_sub": "auth0|ops", "email": "ops@acme.com", "display_name": "Acme Ops"},
        {"id": "30000000-0000-0000-0000-000000000006", "org_id": org_acme_id, "auth0_sub": "auth0|employee", "email": "employee@acme.com", "display_name": "Acme Employee"},
        {"id": "30000000-0000-0000-0000-000000000007", "org_id": org_acme_id, "auth0_sub": "auth0|guest", "email": "guest@acme.com", "display_name": "Acme Guest"},
        {"id": "30000000-0000-0000-0000-000000000008", "org_id": org_globex_id, "auth0_sub": "auth0|globex_user", "email": "user@globex.com", "display_name": "Globex User"},
    ]
    
    memberships_data = [
        {"team_id": team_eng_id, "user_id": "30000000-0000-0000-0000-000000000001", "role": "org_admin", "org_id": org_acme_id},
        {"team_id": team_eng_id, "user_id": "30000000-0000-0000-0000-000000000002", "role": "team_lead", "org_id": org_acme_id},
        {"team_id": team_hr_id, "user_id": "30000000-0000-0000-0000-000000000003", "role": "compliance_officer", "org_id": org_acme_id},
        {"team_id": team_finance_id, "user_id": "30000000-0000-0000-0000-000000000004", "role": "finance_analyst", "org_id": org_acme_id},
        {"team_id": team_eng_id, "user_id": "30000000-0000-0000-0000-000000000005", "role": "operations_engineer", "org_id": org_acme_id},
        {"team_id": team_hr_id, "user_id": "30000000-0000-0000-0000-000000000006", "role": "employee", "org_id": org_acme_id},
        {"team_id": team_hr_id, "user_id": "30000000-0000-0000-0000-000000000007", "role": "guest", "org_id": org_acme_id},
        {"team_id": team_globex_id, "user_id": "30000000-0000-0000-0000-000000000008", "role": "org_admin", "org_id": org_globex_id},
    ]

    async with session_factory() as session:
        async with session.begin():
            # 1. Organizations
            await session.execute(
                text(
                    "INSERT INTO organizations (id, name, slug) VALUES "
                    "(:org1, 'Acme Corp', 'acme-corp'), "
                    "(:org2, 'Globex Inc', 'globex-inc') "
                    "ON CONFLICT (slug) DO NOTHING"
                ),
                {"org1": org_acme_id, "org2": org_globex_id}
            )
            
            # 2. Teams
            await session.execute(
                text(
                    "INSERT INTO teams (id, org_id, name) VALUES "
                    "(:team_eng, :org_acme, 'Engineering'), "
                    "(:team_hr, :org_acme, 'Human Resources'), "
                    "(:team_finance, :org_acme, 'Finance'), "
                    "(:team_globex, :org_globex, 'Globex Eng') "
                    "ON CONFLICT (org_id, name) DO NOTHING"
                ),
                {
                    "team_eng": team_eng_id,
                    "team_hr": team_hr_id,
                    "team_finance": team_finance_id,
                    "team_globex": team_globex_id,
                    "org_acme": org_acme_id,
                    "org_globex": org_globex_id
                }
            )
            
            # 3. Users
            for u in users_data:
                await session.execute(
                    text(
                        "INSERT INTO users (id, org_id, auth0_sub, email, display_name) VALUES "
                        "(:id, :org_id, :auth0_sub, :email, :display_name) "
                        "ON CONFLICT (auth0_sub) DO NOTHING"
                    ),
                    u
                )
                
            # 4. Team memberships
            for m in memberships_data:
                await session.execute(
                    text(
                        "INSERT INTO team_memberships (org_id, team_id, user_id, role) VALUES "
                        "(:org_id, :team_id, :user_id, :role) "
                        "ON CONFLICT (team_id, user_id) DO NOTHING"
                    ),
                    m
                )
                
            print("Successfully seeded all tables.")

if __name__ == "__main__":
    asyncio.run(seed())
