"""
satguard/security/schemas.py
Pydantic Schemas for Authentication, RBAC, and Audit Logging.
"""

from typing import Optional, Dict, Any, List
from datetime import datetime
from enum import Enum
from pydantic import BaseModel, EmailStr, Field


class RoleEnum(str, Enum):
    VIEWER = "VIEWER"          # Read-only surveillance viewing
    ANALYST = "ANALYST"        # Technical multi-sensor analysis & evidence view
    OPERATOR = "OPERATOR"      # Tactical alert acknowledgement & continuous monitoring trigger
    SUPERVISOR = "SUPERVISOR"  # Alert resolution, escalation, and supervisory review
    ADMIN = "ADMIN"            # System configuration & operator management


class UserLoginRequest(BaseModel):
    username: str = Field(..., description="Government operator username")
    password: str = Field(..., description="Account password")


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in_seconds: int
    user_id: str
    username: str
    role: RoleEnum
    full_name: Optional[str] = None


class UserProfileResponse(BaseModel):
    id: str
    username: str
    email: str
    full_name: Optional[str] = None
    department: Optional[str] = None
    role: RoleEnum
    is_active: bool
    last_login: Optional[str] = None
    created_at: Optional[str] = None


class UserCreateRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    email: EmailStr
    password: str = Field(..., min_length=8)
    full_name: Optional[str] = None
    department: Optional[str] = None
    role: RoleEnum = RoleEnum.OPERATOR


class AuditLogResponse(BaseModel):
    id: str
    event_id: str
    timestamp: str
    actor: str
    role: str
    action: str
    resource: str
    resource_id: Optional[str] = None
    result: str
    ip_address: Optional[str] = None
    request_id: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
