"""
User Management API
===================

Endpoints for user registration and API key management.

SECURITY NOTE:
- User registration requires ADMIN_API_KEY (X-Admin-Key header)
- Only the dashboard/admin can create new users
- Users can manage their own accounts with their X-API-Key
"""

from fastapi import APIRouter, Depends, HTTPException, Security
from sqlalchemy.orm import Session
from typing import List
from server.app.db.database import get_db
from server.app.db.models import User
from server.app.models.bot import UserCreate, UserResponse
from server.app.api.auth import get_current_user, verify_admin_key
import secrets

router = APIRouter()

# ============ ADMIN USER REGISTRATION ENDPOINT (Requires X-Admin-Key) ============

@router.post(
    "/register",
    response_model=UserResponse,
    responses={
        200: {"description": "User registered successfully"},
        403: {"description": "Invalid admin key"},
        500: {"description": "Admin key not configured"}
    }
)
def register_user(
    user_data: UserCreate,
    _: bool = Depends(verify_admin_key),  # Requires admin key!
    db: Session = Depends(get_db)
):
    """
    [ADMIN ONLY] Register a new user and get an API key.
    
    This endpoint is protected by admin authentication.
    The Dashboard should call this to provision users.
    
    Headers Required:
        X-Admin-Key: {ADMIN_API_KEY}
    
    Request:
        {
            "user_id": "user123",  # Required - provided by client
            "email": "user@example.com"  # Optional
        }
    
    Response:
        {
            "user_id": "user123",
            "api_key": "cm_abc123...",  # Give this to the user
            "created_at": "2024-01-01T00:00:00",
            "is_active": "true"
        }
    """
    # Check if user_id already exists
    existing = db.query(User).filter(User.user_id == user_data.user_id).first()
    if existing:
        raise HTTPException(
            status_code=400, 
            detail="User ID already registered."
        )
    
    # Check if email already exists (if provided)
    if user_data.email:
        existing_email = db.query(User).filter(User.email == user_data.email).first()
        if existing_email:
            raise HTTPException(
                status_code=400, 
                detail="Email already registered."
            )
    
    new_user = User(
        user_id=user_data.user_id,
        email=user_data.email
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    
    return new_user


# ============ USER SELF-SERVICE ENDPOINTS (Require X-API-Key) ============

@router.get(
    "/me",
    response_model=UserResponse,
    responses={
        200: {"description": "User information retrieved"},
        401: {"description": "Invalid or missing API key"}
    }
)
def get_current_user_info(current_user: User = Depends(get_current_user)):
    """
    Get current user's information.
    
    Requires: X-API-Key header
    """
    return current_user


@router.post("/regenerate-key", response_model=UserResponse)
def regenerate_api_key(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Generate a new API key (invalidates the old one).
    
    Requires: X-API-Key header
    
    Warning: The old API key will immediately stop working.
    """
    current_user.api_key = f"cm_{secrets.token_urlsafe(32)}"
    db.commit()
    db.refresh(current_user)
    
    return current_user


@router.delete("/me")
def deactivate_account(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Deactivate user account.
    
    This doesn't delete data, just prevents API access.
    """
    current_user.is_active = "false"
    db.commit()
    
    return {"status": "deactivated", "user_id": current_user.user_id}
