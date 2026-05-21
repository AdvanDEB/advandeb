"""
Authentication API routes.
"""
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request, status
import httpx

from app.core.config import settings
from app.core.auth import (
    create_access_token,
    create_refresh_token,
    is_refresh_token_revoked,
    revoke_refresh_token,
    verify_token,
)
from app.core.limiter import limiter
from app.models.user import GoogleAuthRequest, NativeLoginRequest, RefreshTokenRequest, TokenResponse, User
from app.services.user_service import UserService


logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/config")
async def get_auth_config():
    """Return auth configuration flags (public endpoint)."""
    return {"google_oauth_enabled": settings.google_oauth_enabled}


@router.post("/login", response_model=TokenResponse)
@limiter.limit("10/minute")
async def native_login(request: Request, login_request: NativeLoginRequest):
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


@router.post("/token", response_model=TokenResponse)
async def token_endpoint(request: Request, login_request: NativeLoginRequest):
    """Alias for /login used by OAuth2PasswordBearer (Swagger 'Authorize')."""
    return await native_login(request, login_request)


@router.post("/google", response_model=TokenResponse)
@limiter.limit("10/minute")
async def google_auth(request: Request, auth_request: GoogleAuthRequest):
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
    except Exception:
        logger.exception("Google OAuth failed")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication failed"
        )


@router.post("/refresh", response_model=TokenResponse)
@limiter.limit("10/minute")
async def refresh_token(request: Request, body: RefreshTokenRequest):
    """Refresh access token using a valid refresh token.

    On success, the OLD refresh token's ``jti`` is immediately revoked
    (refresh-token rotation), so a stolen refresh token can only be used once.
    """
    try:
        payload = verify_token(body.refresh_token)
    except HTTPException:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )

    if payload.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token type",
        )

    # Refresh-token revocation check (S9). Tokens minted before the jti rollout
    # have no jti claim — treat those as not-revoked for backwards compatibility.
    old_jti = payload.get("jti")
    if old_jti and await is_refresh_token_revoked(old_jti):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token has been revoked",
        )

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
        )

    user_service = UserService()
    user = await user_service.get_user_by_id(user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )

    # Rotation: revoke the OLD refresh token before minting the new pair so
    # it cannot be replayed. Skip for legacy tokens without a jti.
    if old_jti:
        exp_claim = payload.get("exp")
        if isinstance(exp_claim, (int, float)):
            old_exp_dt = datetime.fromtimestamp(exp_claim, tz=timezone.utc)
        else:
            old_exp_dt = datetime.now(timezone.utc)
        await revoke_refresh_token(old_jti, old_exp_dt)

    new_access_token = create_access_token(
        data={"sub": str(user.id), "email": user.email}
    )
    new_refresh_token = create_refresh_token(
        data={"sub": str(user.id)}
    )

    return TokenResponse(
        access_token=new_access_token,
        refresh_token=new_refresh_token,
        user=user,
    )


@router.post("/logout")
async def logout(body: RefreshTokenRequest):
    """Logout user by revoking the supplied refresh token.

    Idempotent: always returns 200 with the same payload, regardless of
    whether the token was valid, already revoked, or already expired. This
    prevents leaking information about whether a given token string is
    currently active.
    """
    try:
        payload = verify_token(body.refresh_token, expected_type="refresh")
    except HTTPException:
        return {"message": "Logged out"}
    except Exception:
        # Defensive: any decode error → still respond OK.
        return {"message": "Logged out"}

    jti = payload.get("jti")
    exp_claim = payload.get("exp")
    if jti and isinstance(exp_claim, (int, float)):
        exp_dt = datetime.fromtimestamp(exp_claim, tz=timezone.utc)
        try:
            await revoke_refresh_token(jti, exp_dt)
        except Exception:
            logger.exception("Failed to record refresh-token revocation for jti=%s", jti)

    return {"message": "Logged out"}
