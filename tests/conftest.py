import asyncio
import pytest
from app.db.session import get_engine

@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for each test case.
    
    Using a session-scoped event loop prevents 'Event loop is closed' errors
    on Windows when running multiple async tests that share connection pools.
    """
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    yield loop
    loop.close()

@pytest.fixture(autouse=True)
async def dispose_engine_after_test():
    """Dispose of the global database engine after every test.
    
    This clears the connection pool so that subsequent tests do not attempt
    to reuse connections created on a closed event loop.
    """
    yield
    try:
        engine = get_engine()
        await engine.dispose()
    except Exception:
        pass
