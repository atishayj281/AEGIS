"""Internal API module.

The /internal/org-membership endpoint previously used by Auth0 Actions
has been removed. Auth0 custom claim injection is now handled entirely
on the Auth0 tenant side (Actions/Rules) before the token is issued
to the frontend. The backend is a pure JWT consumer.
"""
