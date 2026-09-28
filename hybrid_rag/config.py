"""Application configuration model.

Values are normally supplied by api.config_manager from AWS Secrets Manager.
This module defines the Settings shape and a legacy from_environment() loader.
"""

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    aws_profile: str | None
    aws_region: str
    s3_bucket_name: str
    dynamodb_table_name: str
    qdrant_url: str
    qdrant_api_key: str
    featherless_api_key: str
    featherless_base_url: str
    featherless_model: str
    embedding_model: str
    judge_model: str

    @classmethod
    def from_environment(cls) -> "Settings":
        """Legacy loader that reads from environment variables.

        Kept for backwards compatibility; the management cockpit uses
        api.config_manager to load these values from AWS Secrets Manager.
        """
        return cls(
            aws_profile=os.getenv("AWS_PROFILE"),
            aws_region=os.getenv("AWS_DEFAULT_REGION", "us-east-1"),
            s3_bucket_name=_required("S3_BUCKET_NAME"),
            dynamodb_table_name=_required("DYNAMODB_TABLE_NAME"),
            qdrant_url=_required("QDRANT_URL"),
            qdrant_api_key=_required("QDRANT_API_KEY"),
            featherless_api_key=_required("FEATHERLESS_API_KEY"),
            featherless_base_url=os.getenv("FEATHERLESS_BASE_URL", "https://api.featherless.ai/v1"),
            featherless_model=os.getenv("FEATHERLESS_MODEL", "meta-llama/Meta-Llama-3.1-8B-Instruct"),
            embedding_model=os.getenv("EMBEDDING_MODEL", "Qwen/Qwen3-Embedding-8B"),
            judge_model=os.getenv("JUDGE_LLM_MODEL", "Qwen/Qwen2.5-72B-Instruct"),
        )


def _required(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value
