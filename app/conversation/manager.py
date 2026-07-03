"""Redis-backed conversation session manager."""

import json
import os
import uuid
import redis.asyncio as redis
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Literal


@dataclass
class ConversationTurn:
    """A single exchange turn (user query **or** assistant answer)."""
    role: Literal["user", "assistant"]
    content: str
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class ConversationSession:
    """Holds all turns for one logical conversation."""
    session_id: str
    username: str
    turns: list[ConversationTurn] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    last_active: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class ConversationManager:
    """Thread-safe Redis store for conversation sessions."""

    def __init__(
        self,
        max_turns_per_session: int = 20,
        session_ttl_minutes: int = 60,
    ) -> None:
        self.max_turns_per_session = max_turns_per_session
        self.session_ttl_seconds = session_ttl_minutes * 60
        redis_url = os.environ.get("REDIS_URL", "redis://redis:6379/0")
        self.r = redis.from_url(redis_url, decode_responses=True)

    def _key(self, session_id: str) -> str:
        return f"conversation:{session_id}"

    def _user_key(self, username: str) -> str:
        return f"user_sessions:{username}"

    async def get_or_create_session(
        self,
        session_id: str | None,
        username: str,
    ) -> ConversationSession:
        if session_id:
            raw = await self.r.get(self._key(session_id))
            if raw:
                data = json.loads(raw)
                data["last_active"] = datetime.now(timezone.utc).isoformat()
                await self.r.set(self._key(session_id), json.dumps(data), ex=self.session_ttl_seconds)
                # Ensure it's in the user's set
                await self.r.sadd(self._user_key(username), session_id)
                # Parse turns
                if "turns" in data:
                    data["turns"] = [ConversationTurn(**t) for t in data["turns"]]
                return ConversationSession(**data)

        # Create a fresh session
        new_id = str(uuid.uuid4())
        session = ConversationSession(session_id=new_id, username=username)
        data = asdict(session)
        await self.r.set(self._key(new_id), json.dumps(data), ex=self.session_ttl_seconds)
        await self.r.sadd(self._user_key(username), new_id)
        return session

    async def add_turn(
        self,
        session_id: str,
        role: Literal["user", "assistant"],
        content: str,
    ) -> None:
        raw = await self.r.get(self._key(session_id))
        if not raw:
            return
        data = json.loads(raw)
        turn = ConversationTurn(role=role, content=content)
        data.setdefault("turns", []).append(asdict(turn))
        if len(data["turns"]) > self.max_turns_per_session:
            data["turns"] = data["turns"][-self.max_turns_per_session:]
        data["last_active"] = datetime.now(timezone.utc).isoformat()
        await self.r.set(self._key(session_id), json.dumps(data), ex=self.session_ttl_seconds)

    async def get_history(
        self,
        session_id: str,
        max_turns: int | None = None,
    ) -> list[ConversationTurn]:
        raw = await self.r.get(self._key(session_id))
        if not raw:
            return []
        data = json.loads(raw)
        turns = [ConversationTurn(**t) for t in data.get("turns", [])]
        if max_turns is not None:
            turns = turns[-max_turns:]
        return turns

    async def get_turn_count(self, session_id: str) -> int:
        raw = await self.r.get(self._key(session_id))
        if not raw:
            return 0
        data = json.loads(raw)
        return len(data.get("turns", []))

    async def delete_session(self, session_id: str) -> bool:
        raw = await self.r.get(self._key(session_id))
        if not raw:
            return False
        data = json.loads(raw)
        username = data.get("username")
        await self.r.delete(self._key(session_id))
        if username:
            await self.r.srem(self._user_key(username), session_id)
        return True

    async def list_user_sessions(self, username: str) -> list[dict]:
        session_ids = await self.r.smembers(self._user_key(username))
        result = []
        expired_ids = []
        for sid in session_ids:
            raw = await self.r.get(self._key(sid))
            if raw:
                data = json.loads(raw)
                result.append({
                    "session_id": data["session_id"],
                    "turn_count": len(data.get("turns", [])),
                    "created_at": data["created_at"],
                    "last_active": data["last_active"],
                })
            else:
                expired_ids.append(sid)
        
        if expired_ids:
            await self.r.srem(self._user_key(username), *expired_ids)
            
        return result

    async def get_session_info(self, session_id: str) -> ConversationSession | None:
        raw = await self.r.get(self._key(session_id))
        if not raw:
            return None
        data = json.loads(raw)
        if "turns" in data:
            data["turns"] = [ConversationTurn(**t) for t in data["turns"]]
        return ConversationSession(**data)


_manager: ConversationManager | None = None

def get_conversation_manager(
    max_turns: int = 20,
    ttl_minutes: int = 60,
) -> ConversationManager:
    global _manager
    if _manager is None:
        _manager = ConversationManager(
            max_turns_per_session=max_turns,
            session_ttl_minutes=ttl_minutes,
        )
    return _manager

async def get_conversation_manager_dep() -> ConversationManager:
    return get_conversation_manager()
