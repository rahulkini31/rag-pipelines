"""Cross-tenant document sharing backed by a DynamoDB table."""

from datetime import datetime, timezone
from typing import Any

import boto3
from boto3.dynamodb.conditions import Attr
from botocore.exceptions import ClientError

from .config_manager import SecretsManagerConfig, get_config_manager


SHARES_TABLE_NAME = "rag_document_shares"


def _make_table(config: SecretsManagerConfig) -> Any:
    session = boto3.Session(
        profile_name=config.get("aws_profile") or None,
        region_name=config.get_required("aws_region"),
    )
    return session.resource("dynamodb").Table(SHARES_TABLE_NAME)


def ensure_shares_table(config: SecretsManagerConfig | None = None) -> Any:
    """Create the shares table and recipient GSI if they do not exist."""
    config = config or get_config_manager()
    session = boto3.Session(
        profile_name=config.get("aws_profile") or None,
        region_name=config.get_required("aws_region"),
    )
    client = session.client("dynamodb")
    resource = session.resource("dynamodb")
    try:
        table = resource.Table(SHARES_TABLE_NAME)
        table.load()
        return table
    except ClientError as exc:
        code = exc.response["Error"]["Code"]
        if code == "AccessDeniedException":
            # The application role may not have permission to describe/create the
            # shares table. Return the table resource; downstream calls will also
            # fail, but the rest of the app can still function.
            return resource.Table(SHARES_TABLE_NAME)
        if code != "ResourceNotFoundException":
            raise

    client.create_table(
        TableName=SHARES_TABLE_NAME,
        AttributeDefinitions=[
            {"AttributeName": "shared_doc_id", "AttributeType": "S"},
            {"AttributeName": "recipient_tenant_id", "AttributeType": "S"},
        ],
        KeySchema=[
            {"AttributeName": "shared_doc_id", "KeyType": "HASH"},
            {"AttributeName": "recipient_tenant_id", "KeyType": "RANGE"},
        ],
        GlobalSecondaryIndexes=[
            {
                "IndexName": "recipient_tenant_id-index",
                "KeySchema": [
                    {"AttributeName": "recipient_tenant_id", "KeyType": "HASH"},
                    {"AttributeName": "shared_doc_id", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
                "ProvisionedThroughput": {
                    "ReadCapacityUnits": 2,
                    "WriteCapacityUnits": 2,
                },
            }
        ],
        ProvisionedThroughput={"ReadCapacityUnits": 2, "WriteCapacityUnits": 2},
    )
    waiter = client.get_waiter("table_exists")
    waiter.wait(TableName=SHARES_TABLE_NAME)
    return resource.Table(SHARES_TABLE_NAME)


class DocumentSharesStore:
    """Manages read-only document shares across tenants."""

    def __init__(self, config: SecretsManagerConfig | None = None):
        self.config = config or get_config_manager()
        self.table = _make_table(self.config)

    def share(
        self,
        owner_tenant_id: str,
        doc_id: str,
        recipient_tenant_id: str,
    ) -> dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat()
        self.table.put_item(
            Item={
                "shared_doc_id": doc_id,
                "recipient_tenant_id": recipient_tenant_id,
                "owner_tenant_id": owner_tenant_id,
                "shared_at": now,
            },
            ConditionExpression=Attr("shared_doc_id").not_exists()
            | Attr("recipient_tenant_id").not_exists(),
        )
        return {
            "doc_id": doc_id,
            "recipient_tenant_id": recipient_tenant_id,
            "shared_at": now,
        }

    def revoke(
        self,
        owner_tenant_id: str,
        doc_id: str,
        recipient_tenant_id: str,
    ) -> dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat()
        self.table.update_item(
            Key={
                "shared_doc_id": doc_id,
                "recipient_tenant_id": recipient_tenant_id,
            },
            UpdateExpression="SET revoked_at = :r",
            ConditionExpression=Attr("owner_tenant_id").eq(owner_tenant_id),
            ExpressionAttributeValues={":r": now},
        )
        return {
            "doc_id": doc_id,
            "recipient_tenant_id": recipient_tenant_id,
            "revoked_at": now,
        }

    def list_shares(self, doc_id: str, owner_tenant_id: str | None = None) -> list[dict[str, Any]]:
        kwargs: dict[str, Any] = {
            "KeyConditionExpression": "shared_doc_id = :d",
            "FilterExpression": "attribute_not_exists(revoked_at)",
            "ExpressionAttributeValues": {":d": doc_id},
        }
        if owner_tenant_id:
            kwargs["FilterExpression"] += " AND owner_tenant_id = :o"
            kwargs["ExpressionAttributeValues"][":o"] = owner_tenant_id
        response = self.table.query(**kwargs)
        return response.get("Items", [])

    def list_shared_with(self, recipient_tenant_id: str) -> list[dict[str, Any]]:
        response = self.table.query(
            IndexName="recipient_tenant_id-index",
            KeyConditionExpression="recipient_tenant_id = :r",
            FilterExpression="attribute_not_exists(revoked_at)",
            ExpressionAttributeValues={":r": recipient_tenant_id},
        )
        return response.get("Items", [])


_shares_store: DocumentSharesStore | None = None


def get_shares_store() -> DocumentSharesStore:
    global _shares_store
    if _shares_store is None:
        _shares_store = DocumentSharesStore()
    return _shares_store


def set_shares_store(store: DocumentSharesStore) -> None:
    global _shares_store
    _shares_store = store


def create_shares_table(config: SecretsManagerConfig | None = None) -> Any:
    """Explicitly create the shares table; call once during environment setup."""
    return ensure_shares_table(config)
