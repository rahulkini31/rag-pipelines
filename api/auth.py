"""AWS Cognito JWT authentication for FastAPI."""

import json
import os
from dataclasses import dataclass
from typing import Any
from urllib.request import urlopen

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from .config_manager import get_config_manager


security = HTTPBearer(auto_error=False)


@dataclass
class CognitoUser:
    tenant_id: str
    user_id: str
    email: str | None
    access_token: str


def _get_cognito_public_keys(user_pool_id: str, region: str) -> list[dict[str, Any]]:
    url = f"https://cognito-idp.{region}.amazonaws.com/{user_pool_id}/.well-known/jwks.json"
    with urlopen(url, timeout=10) as response:
        return json.load(response).get("keys", [])


def _get_key(token: str, keys: list[dict[str, Any]]) -> dict[str, Any] | None:
    unverified = jwt.get_unverified_header(token)
    kid = unverified.get("kid")
    for key in keys:
        if key.get("kid") == kid:
            return key
    return None


def verify_cognito_token(token: str) -> CognitoUser:
    """Verify a Cognito access token and extract tenant_id."""
    config = get_config_manager()
    user_pool_id = config.get_required("cognito_user_pool_id")
    region = config.get_required("cognito_region")

    keys = _get_cognito_public_keys(user_pool_id, region)
    key = _get_key(token, keys)
    if key is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unable to find appropriate signing key",
        )

    try:
        payload = jwt.decode(
            token,
            key,
            algorithms=["RS256"],
            audience=config.get_required("cognito_client_id"),
            issuer=f"https://cognito-idp.{region}.amazonaws.com/{user_pool_id}",
        )
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {exc}",
        )

    tenant_id = payload.get("custom:tenant_id")
    if not tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Missing tenant_id claim",
        )

    return CognitoUser(
        tenant_id=str(tenant_id),
        user_id=payload.get("sub", ""),
        email=payload.get("email"),
        access_token=token,
    )


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> CognitoUser:
    # Allow bypass in local dev if COGNITO_BYPASS_USER_ID is set.
    bypass_user_id = os.getenv("COGNITO_BYPASS_USER_ID")
    bypass_tenant_id = os.getenv("COGNITO_BYPASS_TENANT_ID")
    if bypass_user_id and bypass_tenant_id:
        return CognitoUser(
            tenant_id=bypass_tenant_id,
            user_id=bypass_user_id,
            email="local@dev",
            access_token="",
        )

    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )

    scheme = credentials.scheme.lower()
    if scheme != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication scheme",
        )

    return verify_cognito_token(credentials.credentials)
