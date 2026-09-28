"""Auth verification endpoint."""

from fastapi import APIRouter, Depends

from .auth import CognitoUser, get_current_user

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/verify")
async def verify_auth(user: CognitoUser = Depends(get_current_user)) -> dict:
    return {
        "tenant_id": user.tenant_id,
        "user_id": user.user_id,
        "email": user.email,
    }
