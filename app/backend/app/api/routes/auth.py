"""
Authentication API routes.
"""
from fastapi import APIRouter, HTTPException, status
import httpx

from app.core.config import settings
from app.core.auth import create_access_token, create_refresh_token
from app.models.user import GoogleAuthRequest, NativeLoginRequest, TokenResponse, User
from app.services.user_service import UserService


router = APIRouter()


@router.get("/config")
async def get_auth_config():
    """Return auth configuration flags (public endpoint)."""
    return {"google_oauth_enabled": settings.google_oauth_enabled}


@router.post("/login", response_model=TokenResponse)
async def native_login(login_request: NativeLoginRequest):
    """
    Authenticate with email and password.
    Returns JWT tokens on success, 401 on invalid credentials.
    """
    user_service = UserService()
    user = await user_service.authenticate_user(login_request.email, login_request.password)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password"
        )

    access_token = create_access_token(
        data={"sub": str(user.id), "email": user.email}
    )
    refresh_token = create_refresh_token(
        data={"sub": str(user.id)}
    )

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        user=user
    )


@router.post("/google", response_model=TokenResponse)
async def google_auth(auth_request: GoogleAuthRequest):
    """
    Authenticate with Google OAuth 2.0.
    Exchange authorization code for tokens and create/update user.
    """
    if not settings.google_oauth_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google OAuth is not configured"
        )

    try:
        from google.oauth2 import id_token
        from google.auth.transport import requests as google_requests

        # Exchange code for tokens
        async with httpx.AsyncClient() as client:
            token_response = await client.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "code": auth_request.code,
                    "client_id": settings.GOOGLE_CLIENT_ID,
                    "client_secret": settings.GOOGLE_CLIENT_SECRET,
                    "redirect_uri": auth_request.redirect_uri,
                    "grant_type": "authorization_code",
                }
            )

            if token_response.status_code != 200:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Failed to exchange authorization code"
                )

            tokens = token_response.json()
            google_id_token = tokens.get("id_token")

            # Verify and decode ID token
            idinfo = id_token.verify_oauth2_token(
                google_id_token,
                google_requests.Request(),
                settings.GOOGLE_CLIENT_ID
            )

            # Extract user info
            google_id = idinfo["sub"]
            email = idinfo["email"]
            full_name = idinfo.get("name")
            avatar_url = idinfo.get("picture")

            # Create or update user
            user_service = UserService()
            user = await user_service.get_or_create_user(
                google_id=google_id,
                email=email,
                full_name=full_name,
                avatar_url=avatar_url
            )

            # Create JWT tokens
            access_token = create_access_token(
                data={"sub": str(user.id), "email": user.email}
            )
            refresh_token = create_refresh_token(
                data={"sub": str(user.id)}
            )

            return TokenResponse(
                access_token=access_token,
                refresh_token=refresh_token,
                user=user
            )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Authentication failed: {str(e)}"
        )


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(refresh_token: str):
    """Refresh access token using refresh token."""
    # TODO: Implement token refresh
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Not implemented"
    )


@router.post("/logout")
async def logout():
    """Logout user (invalidate tokens)."""
    # TODO: Implement token blacklisting if needed
    return {"message": "Logged out successfully"}
