"""
API Key Authentication for CueMeet Bot API
==========================================

Security Implementation:
- API key is passed via X-API-Key header
- Each user gets a unique API key on registration
- All endpoints (except user creation) require valid API key
- User can only access their own resources (multi-tenant isolation)

Admin Authentication:
- Admin key is passed via X-Admin-Key header
- Required for user creation and admin operations
- Set via ADMIN_API_KEY environment variable

Usage:
    curl -X POST /api/bots \
         -H "X-API-Key: cm_abc123..." \
         -H "Content-Type: application/json" \
         -d '{"name": "MyBot"}'
"""

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import APIKeyHeader
from sqlalchemy.orm import Session
from server.app.db.database import get_db
from server.app.db.models import User
from server.app.config.settings import settings

# API Key header schemes - scheme_name must match OpenAPI securitySchemes
API_KEY_HEADER = APIKeyHeader(
    name="X-API-Key",
    scheme_name="ApiKeyAuth",
    auto_error=False,
    description="User API key (format: cm_xxxxxxxxxxxxx)"
)
ADMIN_KEY_HEADER = APIKeyHeader(
    name="X-Admin-Key",
    scheme_name="AdminKeyAuth",
    auto_error=False,
    description="Admin API key for user registration"
)


async def verify_admin_key(
    admin_key: str = Security(ADMIN_KEY_HEADER)
) -> bool:
    """
    Verify the admin API key for protected operations.
    
    Raises:
        HTTPException 401: If admin key is missing
        HTTPException 403: If admin key is invalid
    """
    if not settings.ADMIN_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="ADMIN_API_KEY not configured. Set it in environment variables.",
        )
    
    if not admin_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing admin key. Include 'X-Admin-Key' header.",
            headers={"WWW-Authenticate": "AdminKey"},
        )
    
    if admin_key != settings.ADMIN_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid admin key.",
        )
    
    return True


async def get_current_user(
    api_key: str = Security(API_KEY_HEADER),
    db: Session = Depends(get_db)
) -> User:
    """
    Dependency to get the current authenticated user from API key.
    
    Raises:
        HTTPException 401: If API key is missing or invalid
        HTTPException 403: If user account is deactivated
    """
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing API key. Include 'X-API-Key' header.",
            headers={"WWW-Authenticate": "ApiKey"},
        )
    
    user = db.query(User).filter(User.api_key == api_key).first()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key.",
            headers={"WWW-Authenticate": "ApiKey"},
        )
    
    if user.is_active != "true":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is deactivated.",
        )
    
    return user


async def get_optional_user(
    api_key: str = Security(API_KEY_HEADER),
    db: Session = Depends(get_db)
) -> User | None:
    """
    Optional authentication - returns None if no API key provided.
    Useful for endpoints that allow both authenticated and anonymous access.
    """
    if not api_key:
        return None
    
    user = db.query(User).filter(User.api_key == api_key).first()
    return user if user and user.is_active == "true" else None
