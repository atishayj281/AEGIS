"""Central auth exports and provider configurations."""

import os
from app.config import get_settings

def get_auth_provider() -> str:
    """Return the currently configured AUTH_PROVIDER ('legacy' or 'auth0')."""
    settings = get_settings()
    return getattr(settings, "auth_provider", "legacy")
