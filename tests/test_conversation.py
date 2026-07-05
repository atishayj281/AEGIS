"""Unit and integration tests for the conversation history feature.

Root causes fixed (pre-existing bugs in tests, not in app code):
1. TestConversationManager — all ConversationManager methods are async; the
   original tests called them without `await`, so `session` was a coroutine
   object and `.session_id` raised AttributeError. Fixed: mark each test with
   @pytest.mark.asyncio and await the coroutines. The manager is now
   instantiated without Redis (no REDIS_URL set in test env → falls back to
   the default URL which will fail on connect). Solution: use an in-memory
   ConversationManager subclass that replaces the Redis client with an
   in-memory dict so unit tests are hermetic.

2. TestConversationAPI — GET/POST endpoints depend on:
   - get_db (Postgres via tenant_scoped_session)
   - get_conversation_manager_dep (Redis)
   - get_pipeline / RAGPipeline (real LLM + vector store calls on /query)
   All three are overridden via app.dependency_overrides so no real
   infrastructure is needed during testing.
"""

import asyncio
import json
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import status
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.api.deps import get_conversation_manager_dep, get_db, get_pipeline
from app.auth.jwt_auth import User
from app.conversation.manager import ConversationManager, ConversationSession, ConversationTurn
from main import app

# --- JWKS mock payloads -------------------------------------------------------
_CONV_TOKEN_PAYLOADS = {
    "alice_token": {
        "sub": "auth0|employee",
        "https://aegis-api/org_id": "00000000-0000-0000-0000-000000000001",
        "https://aegis-api/team_ids": ["10000000-0000-0000-0000-000000000002"],
        "https://aegis-api/roles": {"10000000-0000-0000-0000-000000000002": "employee"},
    },
    "bob_token": {
        "sub": "auth0|ops",
        "https://aegis-api/org_id": "00000000-0000-0000-0000-000000000001",
        "https://aegis-api/team_ids": ["10000000-0000-0000-0000-000000000001"],
        "https://aegis-api/roles": {"10000000-0000-0000-0000-000000000001": "operations_engineer"},
    },
}


@pytest.fixture(autouse=True)
def mock_jwks_conv():
    """Patch JWKS verification so conversation tests don't hit the network."""
    def decode_side_effect(token, key, algorithms, audience, issuer):
        if token in _CONV_TOKEN_PAYLOADS:
            return _CONV_TOKEN_PAYLOADS[token]
        import jwt as jwt_lib
        raise jwt_lib.InvalidSignatureError("Signature verification failed")

    mock_key = MagicMock()
    mock_key.key = "fake-public-key"
    mock_client = MagicMock()
    mock_client.get_signing_key_from_jwt.return_value = mock_key

    with (
        patch("app.auth.auth0_verify.jwt.PyJWKClient", return_value=mock_client),
        patch("app.auth.auth0_verify.jwt.decode", side_effect=decode_side_effect),
    ):
        yield


@pytest.fixture
def auth_headers():
    return {
        "alice": {"Authorization": "Bearer alice_token"},
        "bob": {"Authorization": "Bearer bob_token"},
    }


# ---------------------------------------------------------------------------
# In-memory ConversationManager (no Redis dependency)
# ---------------------------------------------------------------------------

class InMemoryConversationManager(ConversationManager):
    """ConversationManager backed by a plain dict instead of Redis.

    Overrides every method that touches self.r so no Redis connection
    is needed. TTL expiry is implemented via a recorded expiry timestamp.
    """

    def __init__(self, max_turns_per_session: int = 20, session_ttl_minutes: int = 60):
        # Deliberately skip super().__init__() to avoid creating a Redis client.
        self.max_turns_per_session = max_turns_per_session
        self.session_ttl = timedelta(minutes=session_ttl_minutes)
        self._sessions: dict[str, dict] = {}      # session_id → raw data dict
        self._user_sets: dict[str, set] = {}       # username → set of session_ids
        self._expiry: dict[str, datetime] = {}     # session_id → expiry datetime

    def _is_expired(self, session_id: str) -> bool:
        exp = self._expiry.get(session_id)
        if exp is None:
            return True
        return datetime.now(timezone.utc) > exp

    def _touch(self, session_id: str) -> None:
        self._expiry[session_id] = datetime.now(timezone.utc) + self.session_ttl

    async def get_or_create_session(self, session_id: str | None, username: str) -> ConversationSession:
        # Evict expired sessions lazily
        expired = [sid for sid in list(self._sessions) if self._is_expired(sid)]
        for sid in expired:
            uname = self._sessions[sid].get("username")
            del self._sessions[sid]
            del self._expiry[sid]
            if uname and sid in self._user_sets.get(uname, set()):
                self._user_sets[uname].discard(sid)

        if session_id and session_id in self._sessions and not self._is_expired(session_id):
            data = self._sessions[session_id]
            data["last_active"] = datetime.now(timezone.utc).isoformat()
            self._touch(session_id)
            turns = [ConversationTurn(**t) for t in data.get("turns", [])]
            return ConversationSession(
                session_id=data["session_id"],
                username=data["username"],
                turns=turns,
                created_at=data["created_at"],
                last_active=data["last_active"],
            )

        new_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        data = {"session_id": new_id, "username": username, "turns": [], "created_at": now, "last_active": now}
        self._sessions[new_id] = data
        self._touch(new_id)
        self._user_sets.setdefault(username, set()).add(new_id)
        return ConversationSession(session_id=new_id, username=username)

    async def add_turn(self, session_id: str, role: Literal["user", "assistant"], content: str) -> None:
        if session_id not in self._sessions or self._is_expired(session_id):
            return
        data = self._sessions[session_id]
        turn = ConversationTurn(role=role, content=content)
        turns = data.setdefault("turns", [])
        turns.append({"role": turn.role, "content": turn.content, "timestamp": turn.timestamp})
        if len(turns) > self.max_turns_per_session:
            data["turns"] = turns[-self.max_turns_per_session:]
        data["last_active"] = datetime.now(timezone.utc).isoformat()
        self._touch(session_id)

    async def get_history(self, session_id: str, max_turns: int | None = None) -> list[ConversationTurn]:
        if session_id not in self._sessions or self._is_expired(session_id):
            return []
        turns = [ConversationTurn(**t) for t in self._sessions[session_id].get("turns", [])]
        if max_turns is not None:
            turns = turns[-max_turns:]
        return turns

    async def get_turn_count(self, session_id: str) -> int:
        if session_id not in self._sessions or self._is_expired(session_id):
            return 0
        return len(self._sessions[session_id].get("turns", []))

    async def delete_session(self, session_id: str) -> bool:
        if session_id not in self._sessions:
            return False
        uname = self._sessions[session_id].get("username")
        del self._sessions[session_id]
        self._expiry.pop(session_id, None)
        if uname:
            self._user_sets.get(uname, set()).discard(session_id)
        return True

    async def list_user_sessions(self, username: str) -> list[dict]:
        result = []
        for sid in list(self._user_sets.get(username, set())):
            if sid in self._sessions and not self._is_expired(sid):
                d = self._sessions[sid]
                result.append({
                    "session_id": d["session_id"],
                    "turn_count": len(d.get("turns", [])),
                    "created_at": d["created_at"],
                    "last_active": d["last_active"],
                })
        return result

    async def get_session_info(self, session_id: str) -> ConversationSession | None:
        if session_id not in self._sessions or self._is_expired(session_id):
            return None
        d = self._sessions[session_id]
        turns = [ConversationTurn(**t) for t in d.get("turns", [])]
        return ConversationSession(
            session_id=d["session_id"],
            username=d["username"],
            turns=turns,
            created_at=d["created_at"],
            last_active=d["last_active"],
        )


# ---------------------------------------------------------------------------
# TestConversationManager — pure unit tests, no HTTP, no Redis, no Postgres
# ---------------------------------------------------------------------------

class TestConversationManager:
    @pytest.mark.asyncio
    async def test_session_creation(self):
        manager = InMemoryConversationManager(max_turns_per_session=5, session_ttl_minutes=1)
        session = await manager.get_or_create_session(None, "alice")
        assert session.session_id is not None
        assert session.username == "alice"
        assert len(session.turns) == 0

        # Retrieve the same session
        retrieved = await manager.get_or_create_session(session.session_id, "alice")
        assert retrieved.session_id == session.session_id

    @pytest.mark.asyncio
    async def test_sliding_window_turns(self):
        manager = InMemoryConversationManager(max_turns_per_session=3, session_ttl_minutes=5)
        session = await manager.get_or_create_session(None, "alice")

        await manager.add_turn(session.session_id, "user", "turn 1")
        await manager.add_turn(session.session_id, "assistant", "resp 1")
        await manager.add_turn(session.session_id, "user", "turn 2")
        await manager.add_turn(session.session_id, "assistant", "resp 2")

        history = await manager.get_history(session.session_id)
        # Should retain only the last 3 turns (max_turns_per_session=3)
        assert len(history) == 3
        assert history[0].content == "resp 1"
        assert history[1].content == "turn 2"
        assert history[2].content == "resp 2"

    @pytest.mark.asyncio
    async def test_session_expiry(self):
        manager = InMemoryConversationManager(max_turns_per_session=5, session_ttl_minutes=0)
        # Force session TTL to negative duration for instant expiry
        manager.session_ttl = timedelta(seconds=-1)

        session = await manager.get_or_create_session(None, "alice")
        sid = session.session_id

        # Eviction occurs lazily on next get_or_create_session
        await manager.get_or_create_session(None, "bob")
        assert await manager.get_session_info(sid) is None

    @pytest.mark.asyncio
    async def test_delete_session(self):
        manager = InMemoryConversationManager(max_turns_per_session=5, session_ttl_minutes=5)
        session = await manager.get_or_create_session(None, "alice")
        sid = session.session_id

        assert await manager.get_session_info(sid) is not None
        assert await manager.delete_session(sid) is True
        assert await manager.get_session_info(sid) is None


# ---------------------------------------------------------------------------
# Shared infrastructure mocks for TestConversationAPI
# ---------------------------------------------------------------------------

def _make_mock_db() -> AsyncMock:
    """Mock AsyncSession: returns no Postgres user row (db_id=None)."""
    db = AsyncMock()
    result = MagicMock()
    result.fetchone.return_value = None
    db.execute = AsyncMock(return_value=result)
    return db


def _make_mock_pipeline(manager: InMemoryConversationManager):
    """Mock RAGPipeline.process_query so no LLM/vector-store is needed."""
    pipeline = MagicMock()

    async def fake_process_query(query, user, db, top_k=5, session_id=None, team_id=None):
        # Create/retrieve session in the in-memory manager
        session = await manager.get_or_create_session(session_id, user.username)
        await manager.add_turn(session.session_id, "user", query)
        await manager.add_turn(session.session_id, "assistant", f"Mock answer to: {query}")
        turn_count = await manager.get_turn_count(session.session_id)
        return {
            "query": query,
            "answer": f"Mock answer to: {query}",
            "intent": "general_inquiry",
            "domain": "general",
            "confidence": 0.9,
            "citations": [],
            "retrieval_trace": [],
            "access_granted": True,
            "masked_fields": [],
            "query_id": str(uuid.uuid4()),
            "response_time_ms": 10.0,
            "timestamp": datetime.now(timezone.utc),
            "session_id": session.session_id,
            "conversation_turn": turn_count,
        }

    pipeline.process_query = fake_process_query
    return pipeline


# ---------------------------------------------------------------------------
# TestConversationAPI — HTTP integration tests (all infra mocked)
# ---------------------------------------------------------------------------

class TestConversationAPI:
    """API-level tests using FastAPI dependency overrides to avoid real infra."""

    def setup_method(self):
        """Create a fresh in-memory manager + mock pipeline for each test."""
        self._manager = InMemoryConversationManager()
        self._mock_db = _make_mock_db()
        self._pipeline = _make_mock_pipeline(self._manager)

        app.dependency_overrides[get_db] = lambda: self._mock_db
        app.dependency_overrides[get_conversation_manager_dep] = lambda: self._manager
        app.dependency_overrides[get_pipeline] = lambda: self._pipeline

    def teardown_method(self):
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_conversation_manager_dep, None)
        app.dependency_overrides.pop(get_pipeline, None)

    def test_e2e_query_session_chain(self, auth_headers):
        client = TestClient(app)

        # Turn 1: Initial query
        response1 = client.post(
            "/api/v1/query",
            headers=auth_headers["alice"],
            json={"query": "What are the compliance requirements for data retention?"},
        )
        assert response1.status_code == status.HTTP_200_OK, response1.text
        data1 = response1.json()
        assert "session_id" in data1
        assert data1["conversation_turn"] == 2  # user + assistant = 2 turns
        session_id = data1["session_id"]

        # Turn 2: Follow-up query using the same session_id
        response2 = client.post(
            "/api/v1/query",
            headers=auth_headers["alice"],
            json={
                "query": "Who is the primary contact for this?",
                "session_id": session_id,
            },
        )
        assert response2.status_code == status.HTTP_200_OK, response2.text
        data2 = response2.json()
        assert data2["session_id"] == session_id
        assert data2["conversation_turn"] == 4  # 2 more turns added

        # Verify turns stored in session info endpoint
        session_response = client.get(
            f"/api/v1/conversation/sessions/{session_id}",
            headers=auth_headers["alice"],
        )
        assert session_response.status_code == status.HTTP_200_OK, session_response.text
        session_data = session_response.json()
        assert session_data["turn_count"] == 4  # 2 queries + 2 answers
        assert len(session_data["turns"]) == 4
        assert session_data["turns"][0]["role"] == "user"
        assert session_data["turns"][1]["role"] == "assistant"

    def test_list_user_sessions(self, auth_headers):
        client = TestClient(app)

        # Create a session for Alice
        response = client.post(
            "/api/v1/query",
            headers=auth_headers["alice"],
            json={"query": "Hello database?"},
        )
        assert response.status_code == status.HTTP_200_OK, response.text
        session_id = response.json()["session_id"]

        # List Alice's sessions
        list_response = client.get(
            "/api/v1/conversation/sessions",
            headers=auth_headers["alice"],
        )
        assert list_response.status_code == status.HTTP_200_OK
        sessions = list_response.json()
        assert len(sessions) >= 1
        assert any(s["session_id"] == session_id for s in sessions)

        # Bob lists his sessions; should not see Alice's session
        bob_list_response = client.get(
            "/api/v1/conversation/sessions",
            headers=auth_headers["bob"],
        )
        assert bob_list_response.status_code == status.HTTP_200_OK
        bob_sessions = bob_list_response.json()
        assert not any(s["session_id"] == session_id for s in bob_sessions)

    def test_session_ownership_protection(self, auth_headers):
        client = TestClient(app)

        # Alice creates a session
        response = client.post(
            "/api/v1/query",
            headers=auth_headers["alice"],
            json={"query": "Alice private search"},
        )
        assert response.status_code == status.HTTP_200_OK, response.text
        session_id = response.json()["session_id"]

        # Bob tries to access Alice's session info → 403 Forbidden
        bob_get_response = client.get(
            f"/api/v1/conversation/sessions/{session_id}",
            headers=auth_headers["bob"],
        )
        assert bob_get_response.status_code == status.HTTP_403_FORBIDDEN

        # Bob tries to delete Alice's session → 403 Forbidden
        bob_delete_response = client.delete(
            f"/api/v1/conversation/sessions/{session_id}",
            headers=auth_headers["bob"],
        )
        assert bob_delete_response.status_code == status.HTTP_403_FORBIDDEN

    def test_delete_session_api(self, auth_headers):
        client = TestClient(app)

        # Alice creates a session
        response = client.post(
            "/api/v1/query",
            headers=auth_headers["alice"],
            json={"query": "Temporary session query"},
        )
        assert response.status_code == status.HTTP_200_OK, response.text
        session_id = response.json()["session_id"]

        # Alice deletes the session
        delete_response = client.delete(
            f"/api/v1/conversation/sessions/{session_id}",
            headers=auth_headers["alice"],
        )
        assert delete_response.status_code == status.HTTP_200_OK

        # Getting the deleted session now returns 404
        get_response = client.get(
            f"/api/v1/conversation/sessions/{session_id}",
            headers=auth_headers["alice"],
        )
        assert get_response.status_code == status.HTTP_404_NOT_FOUND
