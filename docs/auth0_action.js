/**
 * Auth0 Post-Login Action for injecting custom organization, team, and role claims.
 * 
 * In Auth0 Dashboard:
 * 1. Create a Custom Action in the Post-Login flow.
 * 2. Add dependencies: `axios`
 * 3. Set secrets:
 *    - `INTERNAL_SECRET`: The same secret key set in the backend env.
 *    - `BACKEND_INTERNAL_URL`: The accessible URL of the enterprise-rag-platform.
 * 
 * @param {Event} event - Details about the user logging in.
 * @param {PostLoginAPI} api - Interface to mutate tokens and control access.
 */
exports.onExecutePostLogin = async (event, api) => {
  const axios = require('axios');
  const userId = event.user.user_id;
  const internalSecret = event.secrets.INTERNAL_SECRET;
  const backendUrl = event.secrets.BACKEND_INTERNAL_URL;

  if (!internalSecret || !backendUrl) {
    console.error("Configuration error: INTERNAL_SECRET or BACKEND_INTERNAL_URL not set.");
    return api.access.deny("Authentication system configuration error.");
  }

  try {
    const response = await axios.get(
      `${backendUrl}/internal/org-membership/${encodeURIComponent(userId)}`,
      {
        headers: {
          "X-Internal-Secret": internalSecret
        },
        timeout: 3000 // 3 seconds timeout limit
      }
    );

    const { org_id, team_ids, roles } = response.data;

    if (!org_id) {
      console.error(`User ${userId} does not have a mapped organization.`);
      return api.access.deny("Access Denied: User is not assigned to any organization.");
    }

    const namespace = "https://yourapp.com";

    // Set custom claims in Access Token
    api.accessToken.setCustomClaim(`${namespace}/org_id`, org_id);
    api.accessToken.setCustomClaim(`${namespace}/team_ids`, team_ids || []);
    api.accessToken.setCustomClaim(`${namespace}/roles`, roles || {});

    // Set custom claims in ID Token
    api.idToken.setCustomClaim(`${namespace}/org_id`, org_id);
    api.idToken.setCustomClaim(`${namespace}/team_ids`, team_ids || []);
    api.idToken.setCustomClaim(`${namespace}/roles`, roles || {});

  } catch (error) {
    console.error("Failed to lookup organization membership:", error.message);
    return api.access.deny("Authentication service temporarily unavailable.");
  }
};
