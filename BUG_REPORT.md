# Critical Bugs Found in API Rate Limiting

## Summary
The API server (`hub/server.py`) lacks any form of rate limiting for inbound requests. This allows an attacker with access to localhost (or same origin) to make an unlimited number of requests, potentially leading to denial of service, excessive resource consumption, or abuse of the underlying model providers.

## Details
- **File**: `hub/server.py`
- **Methods**: `do_POST` and `do_GET` (and all API endpoints they route to) have no rate limiting checks.
- **Existing Protections**: The server does perform origin and host checks (`_host_is_local` and `_same_origin`/`_own_request`) to ensure requests originate from localhost and same origin. However, once these checks pass, there is no limit on the number of requests.
- **Impact**: An attacker who can execute code on the localhost (e.g., a malicious local application) could:
  - Flood the API with requests, causing high CPU/memory usage.
  - Exhaust model provider rate limits (if the API proxies to external models) leading to temporary bans.
  - Cause a denial of service for legitimate users on the same machine.
- **Affected Endpoints**: All API endpoints (e.g., `/api/ask`, `/api/ping`, `/api/scan`, `/api/events`, etc.) are vulnerable.

## Recommendations
Implement rate limiting for inbound API requests. Consider:
- Using a token bucket or fixed window counter per client IP (or per API key if authentication is added).
- Integrating the existing `Pacer` class (or a similar mechanism) for inbound requests.
- Setting reasonable limits based on the expected usage (e.g., 10 requests per second per IP).
- Applying limits to both POST and GET endpoints, including the SSE endpoint (`/api/events`).

## Additional Notes
The server does limit the size of POST bodies (1MB) and uses a queue with a limit for SSE event buffering, which mitigates some resource exhaustion vectors. However, these do not prevent excessive request frequency.

## Conclusion
The absence of rate limiting is a critical vulnerability that could be exploited to disrupt the service or abuse connected services. Implementing rate limiting is essential for securing the API.
