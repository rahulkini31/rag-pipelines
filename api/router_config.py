"""Runtime configuration endpoints backed by AWS Secrets Manager."""

import os
from typing import Any

import boto3
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from qdrant_client import QdrantClient

from hybrid_rag.config import Settings
from hybrid_rag.document_system import ProductionDocumentSystem

from .auth import CognitoUser, get_current_user
from .config_manager import (
    SECRET_KEYS,
    SecretsManagerConfig,
    get_config_manager,
    get_public_config,
    mask_value,
)
from .dependencies import get_settings

router = APIRouter(prefix="/config", tags=["config"])


class ConfigUpdateRequest(BaseModel):
    values: dict[str, str]
    reveal: bool = False


class ValidateConfigResponse(BaseModel):
    qdrant: dict[str, Any]
    aws: dict[str, Any]


def _can_reveal(user: CognitoUser) -> bool:
    # In a real system, add admin role checks here. For MVP, all authenticated users can reveal.
    return True


@router.get("")
async def get_config(
    reveal: bool = False,
    manager: SecretsManagerConfig = Depends(get_config_manager),
    user: CognitoUser = Depends(get_current_user),
) -> dict:
    if reveal and not _can_reveal(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not allowed to reveal secrets",
        )
    return get_public_config(manager, reveal=reveal)


@router.put("")
async def update_config(
    request: ConfigUpdateRequest,
    manager: SecretsManagerConfig = Depends(get_config_manager),
    user: CognitoUser = Depends(get_current_user),
) -> dict:
    updated_keys = []
    for key, value in request.values.items():
        if key not in SECRET_KEYS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unknown config key: {key}",
            )
        manager.update_secret(key, value)
        updated_keys.append(key)
    return {"updated_keys": updated_keys}


@router.post("/validate")
async def validate_config(settings: Settings = Depends(get_settings)) -> ValidateConfigResponse:
    errors: list[str] = []

    # Qdrant
    qdrant_result: dict[str, Any] = {"ok": False}
    try:
        client = QdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key, timeout=10)
        qdrant_result["ok"] = client.collection_exists("enterprise_rag_kb")
        qdrant_result["collections"] = [
            c.name for c in client.get_collections().collections
        ]
    except Exception as exc:
        qdrant_result["error"] = str(exc)
        errors.append(f"qdrant: {exc}")

    # AWS
    aws_result: dict[str, Any] = {"ok": False}
    try:
        session = boto3.Session(profile_name=settings.aws_profile, region_name=settings.aws_region)
        s3 = session.client("s3")
        s3.head_bucket(Bucket=settings.s3_bucket_name)
        dynamodb = session.resource("dynamodb")
        dynamodb.Table(settings.dynamodb_table_name).load()
        aws_result["ok"] = True
    except Exception as exc:
        aws_result["error"] = str(exc)
        errors.append(f"aws: {exc}")

    if errors:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"errors": errors, "qdrant": qdrant_result, "aws": aws_result},
        )

    return ValidateConfigResponse(qdrant=qdrant_result, aws=aws_result)
