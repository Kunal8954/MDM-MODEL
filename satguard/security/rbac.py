"""
satguard/security/rbac.py
Role-Based Access Control (RBAC) & Authorization Dependencies for Government Operations.
"""

from typing import List, Optional, Callable
from fastapi import Depends, HTTPException, status, Header
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from satguard.config import settings
from satguard.models.entities import User
from satguard.security.schemas import RoleEnum
from satguard.security.auth import decode_access_token

http_bearer_scheme = HTTPBearer(auto_error=False)

# Role hierarchy ordering from least to most privileged
ROLE_HIERARCHY = {
    RoleEnum.VIEWER: 10,
    RoleEnum.ANALYST: 20,
    RoleEnum.OPERATOR: 30,
    RoleEnum.SUPERVISOR: 40,
    RoleEnum.ADMIN: 50,
}


def has_sufficient_role(user_role: str, required_role: RoleEnum) -> bool:
    """Evaluates whether the user's role meets or exceeds the required privilege level."""
    try:
        user_enum = RoleEnum(user_role)
    except ValueError:
        return False
    return ROLE_HIERARCHY.get(user_enum, 0) >= ROLE_HIERARCHY.get(required_role, 0)


has_required_role = has_sufficient_role


def get_current_user(
    auth: Optional[HTTPAuthorizationCredentials] = Depends(http_bearer_scheme),
    x_operator_role: Optional[str] = Header(None, alias="X-Operator-Role"),
    x_operator_user: Optional[str] = Header(None, alias="X-Operator-User"),
) -> User:
    """
    Resolves the authenticated government operator.
    In production: strictly validates JWT Bearer token.
    In testing/dev fallback: allows standard test header or falls back to system operator.
    """
    if auth and auth.credentials:
        payload = decode_access_token(auth.credentials)
        if not payload or not payload.get("sub"):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired access token.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        username = payload.get("sub")
        role = payload.get("role", RoleEnum.OPERATOR.value)

        # Retrieve user from DB or return transient user object
        try:
            from satguard.db.session import get_db_session
            session = get_db_session()
            try:
                user = session.query(User).filter(User.username == username).first()
                if user:
                    if not user.is_active:
                        raise HTTPException(
                            status_code=status.HTTP_403_FORBIDDEN,
                            detail="User account is deactivated.",
                        )
                    return user
            finally:
                session.close()
        except HTTPException:
            raise
        except Exception:
            pass

        # Transient user representation from JWT payload
        return User(
            id=payload.get("user_id", f"usr-{username}"),
            username=username,
            email=payload.get("email", f"{username}@satguard.gov.in"),
            role=role,
            full_name=payload.get("full_name", username),
            department=payload.get("department", "Operations"),
            is_active=True,
        )

    # In dev/testing, support development operator header or default operator
    if settings.SATGUARD_ENV != "production":
        role_val = x_operator_role or RoleEnum.SUPERVISOR.value
        user_name = x_operator_user or "operator"
        return User(
            id=f"usr-{user_name}",
            username=user_name,
            email=f"{user_name}@satguard.gov.in",
            role=role_val,
            full_name=f"Operational {user_name.capitalize()}",
            department="Surveillance Operations Desk",
            is_active=True,
        )

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required. Please provide a valid Bearer token.",
        headers={"WWW-Authenticate": "Bearer"},
    )


def require_role(required_role: RoleEnum) -> Callable:
    """
    Factory creating a dependency that enforces the required minimum role.
    """
    def _role_checker(user: User = Depends(get_current_user)) -> User:
        if not has_sufficient_role(user.role, required_role):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied: action requires minimum role '{required_role.value}', but operator has '{user.role}'.",
            )
        return user

    return _role_checker
