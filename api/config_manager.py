"""AWS Secrets Manager backed configuration with TTL caching.

The management cockpit reads every runtime secret from AWS Secrets Manager.
Bootstrap AWS credentials (e.g. AWS_PROFILE or a default credential chain) are
still required so the application can call Secrets Manager for the first time.
"""

import os
import time
from typing import Any

import boto3
from botocore.exceptions import ClientError


DEFAULT_SECRET_NAMESPACE = "hybridrag/dev"

# One secret per credential. Each secret stores a single plaintext string value.
SECRET_KEYS = {
    "qdrant_url": "qdrant/url",
    "qdrant_api_key": "qdrant/api_key",
    "aws_profile": "aws/profile",
    "aws_region": "aws/region",
    "s3_bucket_name": "aws/s3_bucket",
    "dynamodb_table_name": "aws/dynamodb_table",
    "featherless_api_key": "featherless/api_key",
    "featherless_base_url": "featherless/base_url",
    "featherless_model": "featherless/model",
    "embedding_model": "embedding/model",
    "judge_model": "judge/model",
    "cognito_user_pool_id": "cognito/user_pool_id",
    "cognito_client_id": "cognito/client_id",
    "cognito_region": "cognito/region",
}

SENSITIVE_KEYS = {
    "qdrant_api_key",
    "featherless_api_key",
}


class SecretsManagerConfig:
    """Loads runtime configuration from AWS Secrets Manager with TTL caching."""

    def __init__(
        self,
        namespace: str | None = None,
        ttl_seconds: float = 60.0,
    ) -> None:
        self.namespace = (namespace or os.getenv("HYBRIDRAG_SECRET_NAMESPACE", DEFAULT_SECRET_NAMESPACE)).rstrip("/")
        self.ttl_seconds = ttl_seconds
        self._cache: dict[str, Any] = {}
        self._cached_at: float = 0.0
        # Bootstrap AWS session uses local credentials/profile to read Secrets Manager.
        self._bootstrap_session = boto3.Session()
        self._client = self._bootstrap_session.client("secretsmanager")

    def _secret_name(self, short_name: str) -> str:
        return f"{self.namespace}/{short_name}"

    def _fetch_secret(self, short_name: str) -> str | None:
        secret_id = self._secret_name(short_name)
        try:
            response = self._client.get_secret_value(SecretId=secret_id)
            return response.get("SecretString")
        except ClientError as exc:
            error_code = exc.response.get("Error", {}).get("Code", "Unknown")
            if error_code == "ResourceNotFoundException":
                return None
            raise

    def _load_all(self) -> dict[str, str | None]:
        return {
            config_key: self._fetch_secret(short_name)
            for config_key, short_name in SECRET_KEYS.items()
        }

    def refresh(self) -> dict[str, str | None]:
        """Force refresh from Secrets Manager."""
        self._cache = self._load_all()
        # Secrets Manager does not return a value for namespace itself.
        self._cache["secret_namespace"] = self.namespace
        self._cached_at = time.monotonic()
        return self._cache

    def get_all(self) -> dict[str, str | None]:
        """Return all config values, using cache if still fresh."""
        now = time.monotonic()
        if not self._cache or (now - self._cached_at) > self.ttl_seconds:
            self.refresh()
        return self._cache.copy()

    def get(self, key: str) -> str | None:
        return self.get_all().get(key)

    def get_required(self, key: str) -> str:
        value = self.get(key)
        if value is None:
            raise RuntimeError(f"Missing required secret/config value: {key}")
        return value

    def update_secret(self, key: str, value: str) -> None:
        """Update a single secret value in Secrets Manager and invalidate cache."""
        if key not in SECRET_KEYS:
            raise KeyError(f"Unknown config key: {key}")
        secret_id = self._secret_name(SECRET_KEYS[key])
        try:
            self._client.put_secret_value(SecretId=secret_id, SecretString=value)
        except ClientError as exc:
            error_code = exc.response.get("Error", {}).get("Code", "Unknown")
            if error_code == "ResourceNotFoundException":
                self._client.create_secret(Name=secret_id, SecretString=value)
            else:
                raise
        self._cache.pop(key, None)


def mask_value(value: str | None, visible_tail: int = 4) -> str | None:
    """Return a masked representation of a sensitive value."""
    if not value:
        return value
    if len(value) <= visible_tail * 2:
        return "*" * len(value)
    return "*" * (len(value) - visible_tail) + value[-visible_tail:]


def get_public_config(config: SecretsManagerConfig, reveal: bool = False) -> dict[str, Any]:
    """Return config suitable for the UI; sensitive keys are masked unless revealed."""
    values = config.get_all()
    result: dict[str, Any] = {}
    for key in SECRET_KEYS:
        value = values.get(key)
        if key in SENSITIVE_KEYS and not reveal:
            result[key] = mask_value(value)
        else:
            result[key] = value
    result["secret_namespace"] = config.namespace
    return result


# Global singleton used by the FastAPI application.
_config_manager: SecretsManagerConfig | None = None


def get_config_manager() -> SecretsManagerConfig:
    global _config_manager
    if _config_manager is None:
        _config_manager = SecretsManagerConfig()
    return _config_manager


def set_config_manager(manager: SecretsManagerConfig) -> None:
    global _config_manager
    _config_manager = manager
