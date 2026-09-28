"""FastAPI dependencies for auth, config, document system, and vector store."""

from typing import Any

import boto3
from fastapi import Depends

from hybrid_rag.config import Settings
from hybrid_rag.document_system import ProductionDocumentSystem
from hybrid_rag.vector_store import HybridVectorStore, Qwen3FeatherlessEmbeddings

from .auth import CognitoUser, get_current_user
from .config_manager import SecretsManagerConfig, get_config_manager


def get_settings(config: SecretsManagerConfig = Depends(get_config_manager)) -> Settings:
    """Build a Settings object from Secrets Manager values with sensible defaults."""
    return Settings(
        aws_profile=config.get("aws_profile"),
        aws_region=config.get_required("aws_region"),
        s3_bucket_name=config.get_required("s3_bucket_name"),
        dynamodb_table_name=config.get_required("dynamodb_table_name"),
        qdrant_url=config.get_required("qdrant_url"),
        qdrant_api_key=config.get_required("qdrant_api_key"),
        featherless_api_key=config.get_required("featherless_api_key"),
        featherless_base_url=config.get("featherless_base_url"),
        featherless_model=config.get("featherless_model"),
        embedding_model=config.get("embedding_model") or "Qwen/Qwen3-Embedding-8B",
        judge_model=config.get("judge_model") or "Qwen/Qwen2.5-72B-Instruct",
    )


def get_document_system(
    settings: Settings = Depends(get_settings),
) -> ProductionDocumentSystem:
    return ProductionDocumentSystem(settings=settings)


def get_vector_store(settings: Settings = Depends(get_settings)) -> HybridVectorStore:
    return HybridVectorStore(settings, "enterprise_rag_kb")


def get_embeddings(settings: Settings = Depends(get_settings)) -> Qwen3FeatherlessEmbeddings:
    return Qwen3FeatherlessEmbeddings(
        model=settings.embedding_model,
        api_key=settings.featherless_api_key,
        base_url=settings.featherless_base_url,
        check_embedding_ctx_length=False,
        chunk_size=32,
    )


def get_current_user_tenant(user: CognitoUser = Depends(get_current_user)) -> str:
    return user.tenant_id


def get_ledger_table(config: SecretsManagerConfig = Depends(get_config_manager)) -> Any:
    """Return only the DynamoDB ledger table, without initializing Qdrant."""
    session = boto3.Session(
        profile_name=config.get("aws_profile") or None,
        region_name=config.get_required("aws_region"),
    )
    table_name = config.get_required("dynamodb_table_name")
    return session.resource("dynamodb").Table(table_name)
