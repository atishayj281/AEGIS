import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App.jsx";
import { Auth0Provider } from "@auth0/auth0-react";
import './index.css';
// ── Auth0 application values (Applications → AEGIS → Settings) ──
const AUTH0_DOMAIN = "dev-n7xa3gj4sm53kgry.us.auth0.com";
const AUTH0_CLIENT_ID = "9OK0791NyslUgSIoQQgObWhH7Miqsmpr";
// Applications → APIs → [your API] → Settings → Identifier
const AUTH0_API_AUDIENCE = "https://aegis-api"; // e.g. https://aegis-api

createRoot(document.getElementById("root")).render(
  <StrictMode>
    <Auth0Provider
      domain={AUTH0_DOMAIN}
      clientId={AUTH0_CLIENT_ID}
      authorizationParams={{
        redirect_uri: window.location.origin,
        audience: AUTH0_API_AUDIENCE,
      }}
    >
      <App />
    </Auth0Provider>
  </StrictMode>,
);
