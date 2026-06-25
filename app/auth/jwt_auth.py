"""JWT authentication and user management."""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.config import Settings, get_settings
from app.models.domain import UserRole

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


class User:
    def __init__(
        self,
        username: str,
        role: UserRole,
        department: str,
        org_id: str | None = None,
        team_ids: list[str] | None = None,
        roles: dict[str, str] | None = None,
    ):
        self.username = username
        self.role = role
        self.department = department
        self.org_id = org_id
        self.team_ids = team_ids or []
        self.roles = roles or {}



class AuthService:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self._users: dict[str, dict] = {}
        self._load_users()

    def _load_users(self) -> None:
        users_path = self.settings.data_dir / "rbac" / "users.json"
        if not users_path.exists():
            return
        with open(users_path, encoding="utf-8") as f:
            users = json.load(f)
        for u in users:
            self._users[u["username"]] = u

    def authenticate(self, username: str, password: str) -> User | None:
        record = self._users.get(username)
        if not record:
            return None
        stored_hash = record.get("password_hash")
        if stored_hash:
            if not pwd_context.verify(password, stored_hash):
                return None
        elif record.get("password") != password:
            return None
        return User(
            username=record["username"],
            role=UserRole(record["role"]),
            department=record.get("department", "Unknown"),
        )

    def create_token(self, user: User) -> tuple[str, int]:
        expire_minutes = self.settings.jwt_expire_minutes
        expire = datetime.now(timezone.utc) + timedelta(minutes=expire_minutes)
        payload = {
            "sub": user.username,
            "role": user.role.value,
            "department": user.department,
            "exp": expire,
        }
        token = jwt.encode(
            payload,
            self.settings.jwt_secret_key,
            algorithm=self.settings.jwt_algorithm,
        )
        return token, expire_minutes * 60

    def decode_token(self, token: str) -> User | None:
        try:
            payload = jwt.decode(
                token,
                self.settings.jwt_secret_key,
                algorithms=[self.settings.jwt_algorithm],
            )
            return User(
                username=payload["sub"],
                role=UserRole(payload["role"]),
                department=payload.get("department", "Unknown"),
            )
        except JWTError:
            return None

    def list_demo_users(self) -> list[dict]:
        return [
            {"username": u["username"], "role": u["role"], "department": u.get("department")}
            for u in self._users.values()
        ]
