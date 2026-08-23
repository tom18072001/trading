import secrets
from datetime import datetime
from typing import Optional

from fastapi import Security, HTTPException, Depends
from fastapi.security import APIKeyHeader
from passlib.hash import bcrypt
from sqlalchemy.orm import Session
from sqlalchemy import select

from database.models import APIUser, APIKey
from api.dependencies import get_db

API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)

RATE_LIMITS = {
    "free": "60/minute",
    "basic": "300/minute",
    "pro": "1000/minute",
}


def generate_api_key() -> str:
    """Generate a new API key with 'vn_' prefix."""
    return "vn_" + secrets.token_urlsafe(32)


def hash_key(key: str) -> str:
    return bcrypt.hash(key)


def verify_key(key: str, key_hash: str) -> bool:
    return bcrypt.verify(key, key_hash)


class APIKeyManager:
    """Manage API keys."""

    def __init__(self, session: Session):
        self.session = session

    def create_user(self, email: str, tier: str = "free") -> APIUser:
        existing = self.session.execute(
            select(APIUser).where(APIUser.email == email)
        ).scalar_one_or_none()
        if existing:
            raise ValueError(f"User with email {email} already exists")
        user = APIUser(email=email, tier=tier)
        self.session.add(user)
        self.session.flush()
        return user

    def create_key(self, user_id: int, name: str = "default") -> str:
        """Create a new API key. Returns the plaintext key (shown once)."""
        plaintext = generate_api_key()
        key_prefix = plaintext[:8]
        key_hash_val = hash_key(plaintext)

        api_key = APIKey(
            user_id=user_id,
            key_prefix=key_prefix,
            key_hash=key_hash_val,
            name=name,
        )
        self.session.add(api_key)
        self.session.flush()
        return plaintext

    def validate_key(self, key: str) -> Optional[dict]:
        """Validate an API key. Returns user info or None."""
        if not key or not key.startswith("vn_"):
            return None

        prefix = key[:8]
        stmt = (
            select(APIKey, APIUser)
            .join(APIUser, APIKey.user_id == APIUser.id)
            .where(APIKey.key_prefix == prefix,
                   APIKey.is_active.is_(True), APIUser.is_active.is_(True))
        )
        results = self.session.execute(stmt).all()

        for api_key, user in results:
            if verify_key(key, api_key.key_hash):
                api_key.last_used = datetime.now()
                self.session.flush()
                return {
                    "user_id": user.id,
                    "email": user.email,
                    "tier": user.tier,
                    "key_id": api_key.id,
                    "rate_limit": RATE_LIMITS.get(user.tier, RATE_LIMITS["free"]),
                }
        return None

    def revoke_key(self, key_id: int, user_id: int) -> bool:
        api_key = self.session.get(APIKey, key_id)
        if not api_key or api_key.user_id != user_id:
            return False
        api_key.is_active = False
        self.session.flush()
        return True

    def list_keys(self, user_id: int) -> list[dict]:
        stmt = select(APIKey).where(APIKey.user_id == user_id, APIKey.is_active.is_(True))
        keys = self.session.execute(stmt).scalars().all()
        return [{
            "id": k.id, "name": k.name, "prefix": k.key_prefix,
            "created_at": str(k.created_at), "last_used": str(k.last_used) if k.last_used else None,
        } for k in keys]


async def require_api_key(
    key: str = Security(API_KEY_HEADER),
    db: Session = Depends(get_db),
) -> dict:
    """FastAPI dependency: require valid API key."""
    if not key:
        raise HTTPException(status_code=401, detail="API key required. Pass via X-API-Key header.")
    manager = APIKeyManager(db)
    user = manager.validate_key(key)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid or revoked API key.")
    return user


async def optional_api_key(
    key: str = Security(API_KEY_HEADER),
    db: Session = Depends(get_db),
) -> Optional[dict]:
    """FastAPI dependency: optional API key (for mixed public/auth endpoints)."""
    if not key:
        return None
    manager = APIKeyManager(db)
    return manager.validate_key(key)
