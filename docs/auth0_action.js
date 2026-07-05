/**
 * Auth0 Post-Login Action — inject org / team / role claims from app_metadata.
 *
 * CURRENT MECHANISM (as of Phase 1 rev, 2026-06-xx)
 * --------------------------------------------------
 * This Action reads the user's `app_metadata` directly from the Auth0 event
 * object. It does NOT call back to the AEGIS backend — the
 * `/internal/org-membership` endpoint previously referenced here was removed
 * in Phase 1 (see app/api/internal.py for the removal note).
 *
 * app_metadata is populated in two ways:
 *   1. Admin provisioning (POST /admin/users): the AEGIS backend sets
 *      app_metadata via the infoDba M2M application when a new user is
 *      created. This ensures the JWT carries correct claims on the user's
 *      very first login.
 *   2. Role/team changes: the AEGIS backend calls
 *      PATCH /api/v2/users/{id} (update:users scope on infoDba) whenever a
 *      user's team or role assignment changes. The updated claims take effect
 *      at the user's next login (after their current token expires).
 *
 * Expected app_metadata shape (set by the AEGIS provisioning backend):
 *   {
 *     "org_id":   "<postgres-org-uuid>",                 // string
 *     "team_ids": ["<postgres-team-uuid>", ...],          // string[]
 *     "roles":    { "<team-id>": "<role-name>", ... }     // dict[str, str]
 *   }
 *
 * JWT claim namespace: "https://aegis-api"
 * Verified by:         app/auth/auth0_verify.py (CLAIMS_NAMESPACE constant)
 *
 * In Auth0 Dashboard:
 *   1. Navigate to Actions → Library → Custom Actions → Post-Login.
 *   2. Paste this file's content. No npm dependencies required.
 *   3. No secrets are needed (this Action is self-contained).
 *   4. Deploy to the Login Flow.
 *
 * @param {Event}        event  - Auth0 login event (contains user + metadata).
 * @param {PostLoginAPI} api    - API to mutate tokens and control access.
 */
exports.onExecutePostLogin = async (event, api) => {
  const meta = event.user.app_metadata || {};
  const namespace = "https://aegis-api";

  // Deny access if the user has no org assignment.
  // This prevents users created outside the AEGIS provisioning flow (e.g.,
  // social-login users who were never provisioned) from obtaining a token
  // with the AEGIS audience — they'd have no Postgres row and would fail
  // every resolve_access check anyway, but denying here gives a clear error.
  if (!meta.org_id) {
    console.error(
      `User ${event.user.user_id} has no org_id in app_metadata. ` +
      "Provision the user via POST /admin/users before they can log in."
    );
    return api.access.deny(
      "Access Denied: this account has not been provisioned for AEGIS. " +
      "Contact your organization administrator."
    );
  }

  // Stamp custom claims into the Access Token (read by the backend on every request).
  api.accessToken.setCustomClaim(`${namespace}/org_id`,   meta.org_id);
  api.accessToken.setCustomClaim(`${namespace}/team_ids`, meta.team_ids || []);
  api.accessToken.setCustomClaim(`${namespace}/roles`,    meta.roles    || {});

  // Stamp the same claims into the ID Token (consumed by the frontend).
  api.idToken.setCustomClaim(`${namespace}/org_id`,   meta.org_id);
  api.idToken.setCustomClaim(`${namespace}/team_ids`, meta.team_ids || []);
  api.idToken.setCustomClaim(`${namespace}/roles`,    meta.roles    || {});
};
