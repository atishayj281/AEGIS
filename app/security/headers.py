"""Security HTTP headers middleware.

Injects a hardened set of HTTP security headers on every response.
These headers satisfy common compliance scanner requirements
(OWASP ZAP, Qualys SSL Labs, Mozilla Observatory) and are expected
by SOC-2 CC6.6 / ISO-27001 A.14.2.5 control families.

Headers applied
---------------
Strict-Transport-Security
    Tells browsers to only connect over HTTPS for the next year.
    ``includeSubDomains`` covers API sub-domains.

X-Content-Type-Options: nosniff
    Prevents browsers from MIME-sniffing a response away from the
    declared Content-Type, mitigating certain injection attacks.

X-Frame-Options: DENY
    Prevents any page from being loaded in a frame/iframe, blocking
    clickjacking attacks.  ``DENY`` is stricter than ``SAMEORIGIN``
    and appropriate for a pure-API backend.

Content-Security-Policy
    Restricts resource origins to the same origin.  The ``/docs``
    (Swagger UI) endpoint needs ``script-src`` and ``style-src``
    relaxations — FastAPI's docs CDN URLs are added to avoid breaking
    the interactive documentation page.

Referrer-Policy: strict-origin-when-cross-origin
    Sends the full URL as referrer for same-origin requests and only
    the origin (no path/query) for cross-origin requests.

Permissions-Policy
    Opt-out of browser APIs the service never uses.

Cache-Control
    Ensures API responses are not cached by shared proxies or browsers
    (auth tokens and PII must not be stored in caches).
"""

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


# Swagger UI CDN sources required for /docs to work
_SWAGGER_SCRIPT_SRC = "https://cdn.jsdelivr.net https://cdnjs.cloudflare.com"
_SWAGGER_STYLE_SRC = "https://cdn.jsdelivr.net https://cdnjs.cloudflare.com"
_SWAGGER_IMG_SRC = "https://fastapi.tiangolo.com"

SECURITY_HEADERS: dict[str, str] = {
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Content-Security-Policy": (
        "default-src 'self'; "
        f"script-src 'self' 'unsafe-inline' {_SWAGGER_SCRIPT_SRC}; "
        f"style-src 'self' 'unsafe-inline' {_SWAGGER_STYLE_SRC}; "
        f"img-src 'self' data: {_SWAGGER_IMG_SRC}; "
        "object-src 'none'; "
        "frame-ancestors 'none'"
    ),
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "geolocation=(), microphone=(), camera=()",
    "Cache-Control": "no-store, no-cache, must-revalidate, private",
    "X-Permitted-Cross-Domain-Policies": "none",
}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Inject HTTP security headers into every outgoing response."""

    async def dispatch(self, request: Request, call_next) -> Response:
        response: Response = await call_next(request)
        for header, value in SECURITY_HEADERS.items():
            response.headers[header] = value
        return response
