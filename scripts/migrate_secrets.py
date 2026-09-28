"""Migrate secrets from a local .env file to AWS Secrets Manager.

Usage:
    source .venv/bin/activate
    python scripts/migrate_secrets.py

The script reads the project .env file and creates/updates one secret per
credential under the namespace configured in `api/config_manager.py`.
"""

import os
from pathlib import Path

import boto3
from botocore.exceptions import ClientError
from dotenv import load_dotenv

from api.config_manager import DEFAULT_SECRET_NAMESPACE, SECRET_KEYS

# Mapping from config key to the environment variable name in .env.
ENV_TO_CONFIG = {
    "qdrant_url": "QDRANT_URL",
    "qdrant_api_key": "QDRANT_API_KEY",
    "aws_profile": "AWS_PROFILE",
    "aws_region": "AWS_DEFAULT_REGION",
    "s3_bucket_name": "S3_BUCKET_NAME",
    "dynamodb_table_name": "DYNAMODB_TABLE_NAME",
    "featherless_api_key": "FEATHERLESS_API_KEY",
    "featherless_base_url": "FEATHERLESS_BASE_URL",
    "featherless_model": "FEATHERLESS_MODEL",
    "embedding_model": "EMBEDDING_MODEL",
    "judge_model": "JUDGE_LLM_MODEL",
    "cognito_user_pool_id": "COGNITO_USER_POOL_ID",
    "cognito_client_id": "COGNITO_CLIENT_ID",
    "cognito_region": "COGNITO_REGION",
}


def secret_name(namespace: str, short_name: str) -> str:
    return f"{namespace.rstrip('/')}/{short_name}"


def main() -> None:
    env_path = Path(__file__).resolve().parents[1] / ".env"
    load_dotenv(env_path, override=True)

    namespace = os.getenv("HYBRIDRAG_SECRET_NAMESPACE", DEFAULT_SECRET_NAMESPACE)
    client = boto3.Session().client("secretsmanager")

    created: list[str] = []
    updated: list[str] = []
    skipped: list[str] = []

    for config_key, env_name in ENV_TO_CONFIG.items():
        value = os.getenv(env_name)
        if value is None or value == "":
            skipped.append(config_key)
            continue

        secret_id = secret_name(namespace, SECRET_KEYS[config_key])
        try:
            client.put_secret_value(SecretId=secret_id, SecretString=value)
            updated.append(secret_id)
        except ClientError as exc:
            error_code = exc.response["Error"]["Code"]
            if error_code == "ResourceNotFoundException":
                client.create_secret(Name=secret_id, SecretString=value)
                created.append(secret_id)
            else:
                raise

    print(f"Namespace: {namespace}")
    print(f"Created ({len(created)}): {created}")
    print(f"Updated ({len(updated)}): {updated}")
    print(f"Skipped missing/empty ({len(skipped)}): {skipped}")


if __name__ == "__main__":
    main()
