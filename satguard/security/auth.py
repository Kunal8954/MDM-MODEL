"""
satguard/security/auth.py
Government Authentication, Password Hashing, JWT Issuance, and Operator Seeding.
"""

from typing import Optional, Dict, Any
from datetime import datetime, timezone, timedelta
import uuid
import logging
import bcrypt
import jwt
from sqlalchemy.orm import Session

from satguard.config import settings
from satguard.models.entities import User
from satguard.security.schemas import RoleEnum

logger = logging.getLogger("satguard.security")


def hash_password(password: str) -> str:
    """Hash password securely using bcrypt."""
    pwd_bytes = password.encode("utf-8")
    salt = bcrypt.gensalt(rounds=12)
    return bcrypt.hashpw(pwd_bytes, salt).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify password against bcrypt hash."""
    try:
        return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))
    except Exception:
        return False


def create_access_token(
    data: Dict[str, Any],
    expires_delta: Optional[timedelta] = None,
    expires_minutes: Optional[int] = None,
) -> str:
    """Generate signed JWT access token."""
    to_encode = data.copy()
    if expires_minutes is not None:
        expires_delta = timedelta(minutes=expires_minutes)
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode.update({"exp": expire, "iat": datetime.now(timezone.utc)})
    return jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)



def decode_access_token(token: str) -> Optional[Dict[str, Any]]:
    """Decode and validate signed JWT access token."""
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
            options={"require": ["exp", "sub"]},
        )
        return payload
    except Exception as e:
        logger.debug(f"JWT decode failed: {e}")
        return None


def authenticate_user(db: Session, username: str, password: str) -> Optional[User]:
    """Authenticates operator credentials against database."""
    user = db.query(User).filter(User.username == username).first()
    if not user or not user.is_active:
        return None
    if not verify_password(password, user.hashed_password):
        return None
    
    # Update last login
    user.last_login = datetime.now(timezone.utc)
    db.commit()
    db.refresh(user)
    return user


def seed_default_users(db: Session) -> None:
    """
    Seeds standard government operational accounts if none exist.
    """
    count = db.query(User).count()
    if count > 0:
        return

    default_accounts = [
        ("admin", "admin@satguard.gov.in", "SatguardAdmin@2026!", RoleEnum.ADMIN.value, "Chief Intelligence Officer", "National Disaster Operations"),
        ("supervisor", "supervisor@satguard.gov.in", "Supervisor@2026!", RoleEnum.SUPERVISOR.value, "Surveillance Supervisor", "Critical Infrastructure Monitoring"),
        ("operator", "operator@satguard.gov.in", "Operator@2026!", RoleEnum.OPERATOR.value, "Tactical Operator", "Surveillance Operations Desk"),
        ("analyst", "analyst@satguard.gov.in", "Analyst@2026!", RoleEnum.ANALYST.value, "Satellite Remote Sensing Analyst", "Geospatial Intelligence Unit"),
        ("viewer", "viewer@satguard.gov.in", "Viewer@2026!", RoleEnum.VIEWER.value, "Government Auditor", "Cabinet Secretariat Inspection"),
    ]

    for uname, email, raw_pwd, role, fname, dept in default_accounts:
        u = User(
            id=f"usr-{uuid.uuid4().hex[:8]}",
            username=uname,
            email=email,
            hashed_password=hash_password(raw_pwd),
            full_name=fname,
            department=dept,
            role=role,
            is_active=True,
            created_at=datetime.now(timezone.utc),
        )
        db.add(u)

    try:
        db.commit()
        logger.info(f"Seeded {len(default_accounts)} standard government operator accounts.")
    except Exception as e:
        db.rollback()
        logger.warning(f"Default user seeding skipped or failed: {e}")
