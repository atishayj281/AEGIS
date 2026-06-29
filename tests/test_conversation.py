"""Unit and integration tests for the conversation history feature."""

import asyncio
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi import status
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.api.deps import get_conversation_manager_dep
from app.auth.jwt_auth import User
from app.conversation.manager import ConversationManager, ConversationTurn, get_conversation_manager
from main import app

client = TestClient(app)

# --- JWKS mock payloads -------------------------------------------------------
_CONV_TOKEN_PAYLOADS = {
    "alice_token": {
        "user_id": "auth0|employee",
        "org_id": "00000000-0000-0000-0000-000000000001",
        "team_ids": ["10000000-0000-0000-0000-000000000002"],
        "roles": {"10000000-0000-0000-0000-000000000002": "employee"},
    },
    "bob_token": {
        "user_id": "auth0|ops",
        "org_id": "00000000-0000-0000-0000-000000000001",
        "team_ids": ["10000000-0000-0000-0000-000000000001"],
        "roles": {"10000000-0000-0000-0000-000000000001": "operations_engineer"},
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


class TestConversationManager:
    def test_session_creation(self):
        manager = ConversationManager(max_turns_per_session=5, session_ttl_minutes=1)
        session = manager.get_or_create_session(None, "alice")
        assert session.session_id is not None
        assert session.username == "alice"
        assert len(session.turns) == 0

        # Retrieve the same session
        retrieved = manager.get_or_create_session(session.session_id, "alice")
        assert retrieved.session_id == session.session_id

    def test_sliding_window_turns(self):
        manager = ConversationManager(max_turns_per_session=3, session_ttl_minutes=5)
        session = manager.get_or_create_session(None, "alice")

        manager.add_turn(session.session_id, "user", "turn 1")
        manager.add_turn(session.session_id, "assistant", "resp 1")
        manager.add_turn(session.session_id, "user", "turn 2")
        manager.add_turn(session.session_id, "assistant", "resp 2")

        history = manager.get_history(session.session_id)
        # Should retain only the last 3 turns
        assert len(history) == 3
        assert history[0].content == "resp 1"
        assert history[1].content == "turn 2"
        assert history[2].content == "resp 2"

    def test_session_expiry(self):
        manager = ConversationManager(max_turns_per_session=5, session_ttl_minutes=0)
        # Force session TTL to negative duration for instant expiry
        manager.session_ttl = timedelta(seconds=-1)

        session = manager.get_or_create_session(None, "alice")
        sid = session.session_id

        # Eviction occurs lazily on next get_or_create_session
        new_session = manager.get_or_create_session(None, "bob")
        assert manager.get_session_info(sid) is None

    def test_delete_session(self):
        manager = ConversationManager(max_turns_per_session=5, session_ttl_minutes=5)
        session = manager.get_or_create_session(None, "alice")
        sid = session.session_id

        assert manager.get_session_info(sid) is not None
        assert manager.delete_session(sid) is True
        assert manager.get_session_info(sid) is None


class TestConversationAPI:
    def test_e2e_query_session_chain(self, auth_headers):
        # Turn 1: Initial query
        response1 = client.post(
            "/api/v1/query",
            headers=auth_headers["alice"],
            json={"query": "What are the compliance requirements for data retention?"},
        )
        assert response1.status_code == status.HTTP_200_OK
        data1 = response1.json()
        assert "session_id" in data1
        assert data1["conversation_turn"] == 1
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
        assert response2.status_code == status.HTTP_200_OK
        data2 = response2.json()
        assert data2["session_id"] == session_id
        assert data2["conversation_turn"] == 2

        # Verify turns stored in session info endpoint
        session_response = client.get(
            f"/api/v1/conversation/sessions/{session_id}",
            headers=auth_headers["alice"],
        )
        assert session_response.status_code == status.HTTP_200_OK
        session_data = session_response.json()
        assert session_data["turn_count"] == 4  # 2 queries + 2 answers
        assert len(session_data["turns"]) == 4
        assert session_data["turns"][0]["role"] == "user"
        assert session_data["turns"][1]["role"] == "assistant"

    def test_list_user_sessions(self, auth_headers):
        # Create a session for Alice
        response = client.post(
            "/api/v1/query",
            headers=auth_headers["alice"],
            json={"query": "Hello database?"},
        )
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
        # Alice creates a session
        response = client.post(
            "/api/v1/query",
            headers=auth_headers["alice"],
            json={"query": "Alice private search"},
        )
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
        # Alice creates a session
        response = client.post(
            "/api/v1/query",
            headers=auth_headers["alice"],
            json={"query": "Temporary session query"},
        )
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
