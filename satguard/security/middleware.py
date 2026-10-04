"""
satguard/security/middleware.py
HTTP Security Headers, Request Correlation (X-Request-ID), and Rate Limiting Middleware.
"""

import time
import uuid
import logging
from collections import defaultdict
from typing import Dict, List, Tuple
from fastapi import Request, Response, status
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from satguard.config import settings

logger = logging.getLogger("satguard.security.middleware")


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    Applies security headers to all HTTP responses to mitigate clickjacking, MIME sniffing, and XSS.
    """

    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)

        if settings.SECURITY_HEADERS_ENABLED:
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["X-Frame-Options"] = "SAMEORIGIN"
            response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
            response.headers["X-XSS-Protection"] = "1; mode=block"

            # Production Content-Security-Policy supporting Leaflet map tiles and local assets
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; "
                "img-src 'self' data: https: blob:; "
                "script-src 'self' 'unsafe-inline'; "
                "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
                "font-src 'self' https://fonts.gstatic.com; "
                "connect-src 'self' http: https: ws: wss:;"
            )

            # Strict-Transport-Security in production
            if settings.SATGUARD_ENV == "production" or request.url.scheme == "https":
                response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains; preload"

        return response


class RequestCorrelationMiddleware(BaseHTTPMiddleware):
    """
    Injects or propagates correlation request IDs across the distributed monitoring pipeline.
    """

    async def dispatch(self, request: Request, call_next):
        # Extract or generate X-Request-ID
        request_id = request.headers.get("X-Request-ID") or f"req-{uuid.uuid4().hex[:12]}"
        request.state.request_id = request_id

        start_time = time.time()
        response: Response = await call_next(request)
        process_time_ms = round((time.time() - start_time) * 1000, 2)
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Process-Time-Ms"] = str(process_time_ms)

        try:
            from satguard.observability.metrics import metrics_collector
            metrics_collector.record_request(request.url.path, process_time_ms, response.status_code)
        except Exception:
            pass

        return response



class RateLimitingMiddleware(BaseHTTPMiddleware):
    """
    In-memory sliding window rate limiter.
    Limits requests per client IP to prevent denial of service and API abuse.
    """

    def __init__(self, app, max_requests: int = 120, window_seconds: int = 60):
        super().__init__(app)
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.client_records: Dict[str, List[float]] = defaultdict(list)

    async def dispatch(self, request: Request, call_next):
        if not settings.RATE_LIMIT_ENABLED:
            return await call_next(request)

        # Exempt health & metrics endpoints from rate limiting
        exempt_paths = [
            "/api/health",
            "/api/health/live",
            "/api/health/ready",
            "/health",
            "/ready",
            "/live",
            "/api/metrics",
            "/metrics",
        ]
        if request.url.path in exempt_paths:
            return await call_next(request)

        client_ip = request.client.host if request.client else "127.0.0.1"
        now = time.time()
        window_start = now - self.window_seconds

        # Clean timestamps older than the window
        timestamps = [ts for ts in self.client_records[client_ip] if ts > window_start]
        timestamps.append(now)
        self.client_records[client_ip] = timestamps

        # Allow high telemetry ceiling for local development / operator dashboard polling
        if settings.SATGUARD_ENV != "production" and client_ip in ("127.0.0.1", "localhost", "::1"):
            effective_limit = max(self.max_requests, 5000)
        else:
            effective_limit = self.max_requests

        if len(timestamps) > effective_limit:
            logger.warning(f"Rate limit exceeded for client {client_ip} ({len(timestamps)} requests in {self.window_seconds}s)")
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={
                    "error_code": "RATE_LIMIT_EXCEEDED",
                    "detail": f"Rate limit of {effective_limit} requests per minute exceeded. Please back off.",
                    "retry_after_seconds": self.window_seconds,
                },
                headers={"Retry-After": str(self.window_seconds)},
            )

        return await call_next(request)
