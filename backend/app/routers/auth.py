"""
Authentication API endpoints.
"""

from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from slowapi import Limiter
from slowapi.util import get_remote_address

from ..database import get_db
from ..models import User, LoginCode
from ..schemas import (
    Token,
    UserResponse,
    LoginCodeRequest,
    LoginCodeResponse,
    VerifyCodeRequest,
    AuthResponse,
    RefreshTokenRequest,
    BotInfoResponse
)

from ..auth import (
    create_access_token,
    create_refresh_token,
    verify_token,
    verify_token_payload,
    get_current_user,
)

# FIXED IMPORT
from .. import telegram

# Get limiter from main app
limiter = Limiter(key_func=get_remote_address)

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.get("/bot/info", response_model=BotInfoResponse)
async def get_bot_info_endpoint():
    """Get bot username and name for the login screen."""

    try:
        # Ensure telegram client exists
        if telegram.tg_client is None:
            raise HTTPException(
                status_code=503,
                detail="Telegram client not ready"
            )

        me = await telegram.tg_client.get_me()

        return BotInfoResponse(
            username=me.username,
            name=f"{me.first_name} {me.last_name or ''}".strip(),
            server_version="1.0.0"
        )

    except HTTPException:
        raise

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Bot info error: {str(e)}"
        )


@router.post("/refresh", response_model=Token)
async def refresh_token(
    request: RefreshTokenRequest,
    db: AsyncSession = Depends(get_db),
):
    """Refresh access token using refresh token."""

    payload = verify_token_payload(
        request.refresh_token,
        token_type="refresh"
    )

    telegram_id = (
        int(payload.get("sub"))
        if payload and payload.get("sub")
        else None
    )

    token_version = payload.get("ver") if payload else None

    if not telegram_id:
        raise HTTPException(
            status_code=401,
            detail="Invalid refresh token"
        )

    result = await db.execute(
        select(User).where(User.telegram_id == telegram_id)
    )

    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=401,
            detail="User not found"
        )

    if (
        token_version is not None
        and token_version < user.auth_version
    ):
        raise HTTPException(
            status_code=401,
            detail="Refresh token has been invalidated"
        )

    new_access_token = create_access_token(
        telegram_id,
        version=user.auth_version
    )

    new_refresh_token = create_refresh_token(
        telegram_id,
        version=user.auth_version
    )

    return Token(
        access_token=new_access_token,
        refresh_token=new_refresh_token,
    )


@router.post("/logout-all")
async def logout_all(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Invalidate all active sessions."""

    current_user.auth_version += 1

    db.add(current_user)
    await db.commit()

    return {
        "message": "All sessions have been invalidated"
    }


@router.get("/me", response_model=UserResponse)
async def get_current_user_info(
    current_user: User = Depends(get_current_user),
):
    """Get current authenticated user information."""

    return UserResponse(
        id=current_user.id,
        telegram_id=current_user.telegram_id,
        username=current_user.username,
        first_name=current_user.first_name,
        last_name=current_user.last_name,
        created_at=current_user.created_at,
        last_active=current_user.last_active,
    )


@router.post("/generate-code", response_model=LoginCodeResponse)
async def generate_login_code(
    db: AsyncSession = Depends(get_db),
):
    """
    Generate a new login code.
    """

    import secrets
    import string
    from datetime import timedelta

    alphabet = string.ascii_uppercase + string.digits

    code = ''.join(
        secrets.choice(alphabet)
        for _ in range(6)
    )

    expires_at = datetime.utcnow() + timedelta(minutes=5)

    login_code = LoginCode(
        code=code,
        telegram_id=None,
        expires_at=expires_at
    )

    db.add(login_code)

    await db.commit()
    await db.refresh(login_code)

    return LoginCodeResponse(
        code=code,
        expires_at=expires_at
    )


@router.post("/verify-code", response_model=AuthResponse)
@limiter.limit("40/minute")
async def verify_login_code(
    request: Request,
    code_request: VerifyCodeRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Verify login code.
    """

    result = await db.execute(
        select(LoginCode).where(
            LoginCode.code == code_request.code.upper()
        )
    )

    login_code = result.scalar_one_or_none()

    if not login_code:
        raise HTTPException(
            status_code=400,
            detail="Invalid login code"
        )

    if login_code.expires_at < datetime.utcnow():
        await db.delete(login_code)
        await db.commit()

        raise HTTPException(
            status_code=400,
            detail="Login code expired"
        )

    if not login_code.telegram_id:
        raise HTTPException(
            status_code=400,
            detail="Code not yet verified"
        )

    result = await db.execute(
        select(User).where(
            User.telegram_id == login_code.telegram_id
        )
    )

    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=404,
            detail="User not found"
        )

    access_token = create_access_token(
        user.telegram_id,
        version=user.auth_version
    )

    refresh_token = create_refresh_token(
        user.telegram_id,
        version=user.auth_version
    )

    await db.delete(login_code)
    await db.commit()

    return AuthResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        user=UserResponse.model_validate(
            user,
            from_attributes=True
        )
    )


@router.post("/code", response_model=Token)
async def login_with_code(
    request: Request,
    code_request: LoginCodeRequest,
    db: AsyncSession = Depends(get_db),
):
    """Legacy endpoint."""

    return await verify_login_code(
        request,
        VerifyCodeRequest(code=code_request.code),
        db
    )