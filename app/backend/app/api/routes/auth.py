"""
Authentication API routes.
"""
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
import httpx

from app.core.config import settings
from app.core.auth import (
    ACTIVE_STATUS,
    TICKET_TTL_SECONDS,
    consume_jti,
    create_socket_ticket,
    create_token_pair,
    get_current_user,
    ensure_account_active,
    load_user_doc,
    revoke_refresh_token,
    token_revoked,
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

    # Checked only after the password: the answer reveals nothing to someone
    # who does not already hold the credentials.
    _refuse_if_suspended(user)

    access_token, refresh_token = create_token_pair(str(user.id), user.email, user.token_version)

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        user=user
    )


def _refuse_if_suspended(user: User) -> None:
    if (user.status or ACTIVE_STATUS) != ACTIVE_STATUS:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account suspended",
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

    Exchanges the authorization code (with its PKCE verifier) for tokens and
    signs in the existing account it belongs to. Accounts are never created
    here — see UserService.get_google_user.
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
        exchange = {
            "code": auth_request.code,
            "client_id": settings.GOOGLE_CLIENT_ID,
            "client_secret": settings.GOOGLE_CLIENT_SECRET,
            "redirect_uri": auth_request.redirect_uri,
            "grant_type": "authorization_code",
        }
        if auth_request.code_verifier:
            exchange["code_verifier"] = auth_request.code_verifier
        async with httpx.AsyncClient() as client:
            token_response = await client.post(
                "https://oauth2.googleapis.com/token",
                data=exchange,
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

            # Invitation only: resolves to an existing account or raises 403.
            user_service = UserService()
            user = await user_service.get_google_user(
                google_id=google_id,
                email=email,
                email_verified=idinfo.get("email_verified") in (True, "true"),
                full_name=full_name,
                avatar_url=avatar_url
            )

            _refuse_if_suspended(user)

            # Create JWT tokens
            access_token, refresh_token = create_token_pair(str(user.id), user.email, user.token_version)

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

    On success, the OLD refresh token's ``jti`` is consumed (refresh-token
    rotation), so a stolen refresh token can only be used once.
    """
    invalid = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired refresh token",
    )
    try:
        # A refresh token carries type="refresh"; verify_token's default is
        # "access", which rejected every refresh from 2026-05-21 (8fa44bf8).
        payload = verify_token(body.refresh_token, expected_type="refresh")
    except HTTPException:
        raise invalid

    user_doc = await load_user_doc(payload.get("sub"))
    if user_doc is None:
        raise invalid
    ensure_account_active(user_doc)
    if token_revoked(payload, user_doc):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token has been revoked",
        )

    # Rotation. Consuming the jti is the revocation check and the revocation in
    # one atomic step, so two requests racing with the same token cannot both
    # succeed. Every refresh token has carried a jti since 2026-05-21 and they
    # live 30 days, so one without it is forged or long expired.
    old_jti = payload.get("jti")
    exp_claim = payload.get("exp")
    if not old_jti or not isinstance(exp_claim, (int, float)):
        raise invalid
    old_exp_dt = datetime.fromtimestamp(exp_claim, tz=timezone.utc)
    if not await consume_jti(old_jti, old_exp_dt):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token has been revoked",
        )

    user_doc["_id"] = str(user_doc["_id"])
    user = User(**user_doc)
    new_access_token, new_refresh_token = create_token_pair(str(user.id), user.email, user.token_version)

    return TokenResponse(
        access_token=new_access_token,
        refresh_token=new_refresh_token,
        user=user,
    )


@router.post("/ws-ticket")
@limiter.limit("60/minute")
async def socket_ticket(request: Request, current_user: dict = Depends(get_current_user)):
    """A one-time credential for a WebSocket or EventSource URL.

    Those browser APIs cannot send an Authorization header, so whatever
    authenticates them ends up in a URL, and URLs end up in logs. The ticket
    is what goes there: good for one connection within TICKET_TTL_SECONDS,
    and not accepted as a bearer token. Pass it as ``?ticket=``.
    """
    user_doc = await load_user_doc(current_user["id"])
    if user_doc is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return {"ticket": create_socket_ticket(user_doc), "expires_in": TICKET_TTL_SECONDS}


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
