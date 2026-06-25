"""Thread-safe, in-memory conversation session manager.

Each user session is identified by a UUID ``session_id``.  The manager keeps
a bounded list of turns per session and automatically evicts sessions that
have been idle longer than ``session_ttl_minutes``.

Usage::

    manager = ConversationManager()
    session = manager.get_or_create_session(session_id=None, username="alice")
    manager.add_turn(session.session_id, role="user", content="What policies exist?")
    manager.add_turn(session.session_id, role="assistant", content="There are 3 policies…")
    history = manager.get_history(session.session_id)
"""

import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Literal


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class ConversationTurn:
    """A single exchange turn (user query **or** assistant answer)."""

    role: Literal["user", "assistant"]
    content: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class ConversationSession:
    """Holds all turns for one logical conversation."""

    session_id: str
    username: str
    turns: list[ConversationTurn] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_active: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------


class ConversationManager:
    """Thread-safe in-memory store for conversation sessions.

    Parameters
    ----------
    max_turns_per_session:
        Maximum number of turns retained per session.  Older turns are dropped
        (FIFO) once the limit is reached, keeping the context window bounded.
    session_ttl_minutes:
        Sessions idle for longer than this are automatically evicted on the
        next ``get_or_create_session`` call.
    """

    def __init__(
        self,
        max_turns_per_session: int = 20,
        session_ttl_minutes: int = 60,
    ) -> None:
        self._sessions: dict[str, ConversationSession] = {}
        self._lock = threading.Lock()
        self.max_turns_per_session = max_turns_per_session
        self.session_ttl = timedelta(minutes=session_ttl_minutes)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_or_create_session(
        self,
        session_id: str | None,
        username: str,
    ) -> ConversationSession:
        """Return an existing session or create a new one.

        If ``session_id`` is ``None`` or not found, a fresh session is created
        and returned.  Expired sessions are purged lazily on each call.

        Parameters
        ----------
        session_id:
            The client-supplied session identifier (may be ``None``).
        username:
            The authenticated user making the request.  Used to scope sessions
            so that listing only returns the caller's sessions.

        Returns
        -------
        ConversationSession
            Always a valid, non-expired session.
        """
        with self._lock:
            self._evict_expired()

            if session_id and session_id in self._sessions:
                session = self._sessions[session_id]
                session.last_active = datetime.now(timezone.utc)
                return session

            # Create a fresh session
            new_id = str(uuid.uuid4())
            session = ConversationSession(session_id=new_id, username=username)
            self._sessions[new_id] = session
            return session

    def add_turn(
        self,
        session_id: str,
        role: Literal["user", "assistant"],
        content: str,
    ) -> None:
        """Append a turn to the session.

        If the session has reached ``max_turns_per_session``, the oldest turn
        is removed first (sliding window).

        Parameters
        ----------
        session_id:
            Target session.  Silently no-ops if the session no longer exists
            (e.g. was deleted between the query and the response).
        role:
            ``"user"`` for a human query, ``"assistant"`` for the AI answer.
        content:
            The raw text of the turn.
        """
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return
            session.turns.append(ConversationTurn(role=role, content=content))
            # Enforce sliding window — keep the most recent N turns
            if len(session.turns) > self.max_turns_per_session:
                session.turns = session.turns[-self.max_turns_per_session :]
            session.last_active = datetime.now(timezone.utc)

    def get_history(
        self,
        session_id: str,
        max_turns: int | None = None,
    ) -> list[ConversationTurn]:
        """Return the ordered list of turns for a session.

        Parameters
        ----------
        session_id:
            Target session.
        max_turns:
            If supplied, only the most recent ``max_turns`` turns are returned.
            Useful to limit the context window fed to the LLM.

        Returns
        -------
        list[ConversationTurn]
            Ordered oldest-to-newest.  Empty list if session not found.
        """
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return []
            turns = session.turns
            if max_turns is not None:
                turns = turns[-max_turns:]
            return list(turns)

    def get_turn_count(self, session_id: str) -> int:
        """Return the number of turns stored in a session (0 if not found)."""
        with self._lock:
            session = self._sessions.get(session_id)
            return len(session.turns) if session else 0

    def delete_session(self, session_id: str) -> bool:
        """Delete a session.

        Returns
        -------
        bool
            ``True`` if the session existed and was deleted, ``False`` otherwise.
        """
        with self._lock:
            return self._sessions.pop(session_id, None) is not None

    def list_user_sessions(self, username: str) -> list[dict]:
        """Return summary dicts for all active sessions owned by *username*.

        Returns
        -------
        list[dict]
            Each dict contains ``session_id``, ``turn_count``, ``created_at``,
            and ``last_active`` (all timestamps as ISO-8601 strings).
        """
        with self._lock:
            self._evict_expired()
            return [
                {
                    "session_id": s.session_id,
                    "turn_count": len(s.turns),
                    "created_at": s.created_at.isoformat(),
                    "last_active": s.last_active.isoformat(),
                }
                for s in self._sessions.values()
                if s.username == username
            ]

    def get_session_info(self, session_id: str) -> ConversationSession | None:
        """Return the full session object, or ``None`` if not found / expired."""
        with self._lock:
            return self._sessions.get(session_id)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _evict_expired(self) -> None:
        """Remove sessions idle past the TTL.  Must be called with ``_lock`` held."""
        now = datetime.now(timezone.utc)
        expired = [
            sid
            for sid, s in self._sessions.items()
            if now - s.last_active > self.session_ttl
        ]
        for sid in expired:
            del self._sessions[sid]


# ---------------------------------------------------------------------------
# Module-level singleton (shared across the app)
# ---------------------------------------------------------------------------

_manager: ConversationManager | None = None
_manager_lock = threading.Lock()


def get_conversation_manager(
    max_turns: int = 20,
    ttl_minutes: int = 60,
) -> ConversationManager:
    """Return the module-level singleton ``ConversationManager``.

    The first call initialises it with the supplied parameters; subsequent
    calls return the same instance regardless of the parameters passed.
    """
    global _manager
    if _manager is None:
        with _manager_lock:
            if _manager is None:
                _manager = ConversationManager(
                    max_turns_per_session=max_turns,
                    session_ttl_minutes=ttl_minutes,
                )
    return _manager
