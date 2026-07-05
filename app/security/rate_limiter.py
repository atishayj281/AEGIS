"""Per-user Redis sliding-window rate limiter.

Algorithm: fixed-window counter using Redis INCR + EXPIRE.

For every request:
  1. Increment a key ``rate_limit:{org_id}:{username}`` in Redis.
  2. If the key was just created (INCR returned 1), set a TTL of
     ``window_seconds``.
  3. If the counter value exceeds ``max_requests``, return False.

This is a fixed-window (not sliding-window) implementation — it is
simple, lock-free, and sufficient for abuse prevention at the
request rates expected.  If true sliding-window semantics are
required in the future, replace with a Lua script or the Redis
``ZRANGEBYSCORE`` pattern.

Key design choices
------------------
- Keyed as ``rate_limit:{org_id}:{username}`` — avoids false collisions
  between users with the same username in different orgs.
- Uses ``redis.asyncio`` so it is fully non-blocking in the FastAPI
  async context.  The same Redis URL as Phase 5's ConversationManager
  is reused.
- Misconfigured or temporarily unavailable Redis fails *open* (allows
  the request) — availability is preferred over strict rate enforcement
  for this use case.  A warning is logged on every failure.
"""

import logging
import os

import redis.asyncio as redis

logger = logging.getLogger(__name__)

_redis_client: redis.Redis | None = None


def _get_redis() -> redis.Redis:
    global _redis_client
    if _redis_client is None:
        redis_url = os.environ.get("REDIS_URL", "redis://redis:6379/0")
        _redis_client = redis.from_url(redis_url, decode_responses=True)
    return _redis_client


class RateLimiter:
    """Async Redis-backed rate limiter.

    Parameters
    ----------
    max_requests:    Maximum requests allowed per window.
    window_seconds:  Duration of the rate-limit window in seconds.
    """

    def __init__(
        self,
        max_requests: int = 60,
        window_seconds: int = 60,
    ) -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds

    async def is_allowed(self, org_id: str, username: str) -> tuple[bool, int]:
        """Check and record a request for the given org/user combination.

        Returns
        -------
        (allowed, current_count)
            ``allowed`` is ``True`` if the request is within the limit.
            ``current_count`` is the counter value after this request.
        """
        key = f"rate_limit:{org_id}:{username}"
        try:
            r = _get_redis()
            count = await r.incr(key)
            if count == 1:
                # First request in window — set expiry
                await r.expire(key, self.window_seconds)
            if count > self.max_requests:
                return False, count
            return True, count
        except Exception as exc:
            logger.warning(
                "RateLimiter: Redis error for key=%s (%s) — failing open.",
                key,
                exc,
            )
            # Fail open: don't block the request if Redis is unavailable
            return True, 0

    async def remaining(self, org_id: str, username: str) -> int:
        """Return the number of remaining requests in the current window."""
        key = f"rate_limit:{org_id}:{username}"
        try:
            r = _get_redis()
            count_raw = await r.get(key)
            count = int(count_raw) if count_raw else 0
            return max(0, self.max_requests - count)
        except Exception:
            return self.max_requests
