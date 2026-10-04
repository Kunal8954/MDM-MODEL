"""
satguard.security package
Production security, authentication, RBAC, middleware, and audit logging.
"""

from satguard.security.schemas import (
    RoleEnum,
    UserLoginRequest,
    TokenResponse,
    UserProfileResponse,
    UserCreateRequest,
    AuditLogResponse,
)
from satguard.security.auth import (
    hash_password,
    verify_password,
    create_access_token,
    decode_access_token,
    authenticate_user,
    seed_default_users,
)
from satguard.security.rbac import (
    get_current_user,
    require_role,
    has_sufficient_role,
)
from satguard.security.audit import (
    record_audit_event,
    query_audit_logs,
)
from satguard.security.middleware import (
    SecurityHeadersMiddleware,
    RequestCorrelationMiddleware,
    RateLimitingMiddleware,
)

__all__ = [
    "RoleEnum",
    "UserLoginRequest",
    "TokenResponse",
    "UserProfileResponse",
    "UserCreateRequest",
    "AuditLogResponse",
    "hash_password",
    "verify_password",
    "create_access_token",
    "decode_access_token",
    "authenticate_user",
    "seed_default_users",
    "get_current_user",
    "require_role",
    "has_sufficient_role",
    "record_audit_event",
    "query_audit_logs",
    "SecurityHeadersMiddleware",
    "RequestCorrelationMiddleware",
    "RateLimitingMiddleware",
]
