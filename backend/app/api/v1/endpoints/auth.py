from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import timedelta
from pydantic import BaseModel
import httpx
from typing import Optional

from app.core.config import settings
from app.core.auth import verify_password, create_access_token
from app.db.session import get_db
from app.services.user_service import user_service
from app.schemas.user import UserCreate, User
from app.models.user import User as UserModel

router = APIRouter()


class GitHubLoginRequest(BaseModel):
    code: str
    redirect_uri: Optional[str] = None


@router.post("/login", response_model=dict)
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db)
):
    user = await user_service.get_by_email(db, form_data.username)
    if not user or not verify_password(form_data.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    access_token_expires = timedelta(minutes=60 * 24)
    access_token = create_access_token(
        subject=user.id, expires_delta=access_token_expires
    )
    
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": {
            "id": str(user.id),
            "email": user.email,
            "name": user.name,
            "role": user.role,
            "image": user.avatar_url
        }
    }


@router.post("/register", response_model=User, status_code=status.HTTP_201_CREATED)
async def register(
    user_in: UserCreate,
    db: AsyncSession = Depends(get_db)
):
    user = await user_service.get_by_email(db, email=user_in.email)
    if user:
        raise HTTPException(
            status_code=400,
            detail="The user with this email already exists in the system.",
        )
    user = await user_service.create(db, user_in=user_in)
    return user


@router.post("/github", response_model=dict)
async def github_login(
    payload: GitHubLoginRequest,
    db: AsyncSession = Depends(get_db)
):
    """Exchanges a GitHub OAuth code for a JWT, linking or registering the user."""
    if not settings.GITHUB_CLIENT_ID or not settings.GITHUB_CLIENT_SECRET:
        raise HTTPException(
            status_code=500,
            detail="GitHub OAuth is not configured on the server."
        )

    # 1. Exchange code for access token
    async with httpx.AsyncClient() as client:
        exchange_data = {
            "client_id": settings.GITHUB_CLIENT_ID,
            "client_secret": settings.GITHUB_CLIENT_SECRET,
            "code": payload.code
        }
        if payload.redirect_uri:
            exchange_data["redirect_uri"] = payload.redirect_uri

        token_res = await client.post(
            "https://github.com/login/oauth/access_token",
            headers={"Accept": "application/json"},
            data=exchange_data
        )
        if not token_res.is_success:
            raise HTTPException(
                status_code=400,
                detail="Failed to exchange GitHub authorization code. Please verify GITHUB_CLIENT_ID and GITHUB_CLIENT_SECRET in backend/.env match your GitHub App."
            )
        
        token_data = token_res.json()
        access_token = token_data.get("access_token")
        if not access_token:
            err_desc = token_data.get("error_description") or ""
            err_code = token_data.get("error") or ""
            if "incorrect or expired" in err_desc.lower() or "bad_verification_code" in err_code.lower():
                raise HTTPException(
                    status_code=400,
                    detail="GitHub returned: Invalid or expired code. This usually happens because GITHUB_CLIENT_ID or GITHUB_CLIENT_SECRET in your backend/.env does not match the GitHub App you are authorizing with, or because you need to restart uvicorn after modifying the .env file."
                )
            raise HTTPException(status_code=400, detail=token_data.get("error_description", "Invalid GitHub authorization code."))

        # 2. Fetch GitHub user profile
        user_res = await client.get(
            "https://api.github.com/user",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/json"
            }
        )
        if not user_res.is_success:
            raise HTTPException(status_code=400, detail="Failed to retrieve user profile from GitHub.")
        
        gh_user = user_res.json()
        github_id = gh_user.get("id")
        github_username = gh_user.get("login")
        name = gh_user.get("name") or github_username
        avatar_url = gh_user.get("avatar_url")
        email = gh_user.get("email")

        # 3. Fetch user email if not public in profile
        if not email:
            emails_res = await client.get(
                "https://api.github.com/user/emails",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Accept": "application/json"
                }
            )
            if emails_res.is_success:
                emails_list = emails_res.json()
                # Find primary email
                primary_email = next((e["email"] for e in emails_list if e.get("primary")), None)
                if not primary_email and emails_list:
                    primary_email = emails_list[0]["email"]
                email = primary_email

        if not email:
            raise HTTPException(status_code=400, detail="Unable to retrieve user email from GitHub.")

    # 4. Authenticate, link, or register user in DB
    # Check by github_id
    result = await db.execute(select(UserModel).where(UserModel.github_id == github_id))
    user = result.scalars().first()

    if not user:
        # Check by email to link existing user
        result = await db.execute(select(UserModel).where(UserModel.email == email))
        user = result.scalars().first()
        if user:
            user.github_id = github_id
            user.github_username = github_username
            user.avatar_url = avatar_url
            db.add(user)
            await db.commit()
            await db.refresh(user)
        else:
            # Register new user
            user = UserModel(
                name=name,
                email=email,
                github_id=github_id,
                github_username=github_username,
                avatar_url=avatar_url,
                is_verified=True
            )
            db.add(user)
            await db.commit()
            await db.refresh(user)

    # 5. Generate JWT token
    access_token_expires = timedelta(minutes=60 * 24)
    jwt_token = create_access_token(
        subject=user.id, expires_delta=access_token_expires
    )

    return {
        "access_token": jwt_token,
        "token_type": "bearer",
        "user": {
            "id": str(user.id),
            "email": user.email,
            "name": user.name,
            "role": user.role,
            "image": user.avatar_url
        }
    }


@router.get("/config", response_model=dict)
async def get_auth_config():
    """Returns public authentication configurations, like the GitHub Client ID."""
    return {"github_client_id": settings.GITHUB_CLIENT_ID}
