"""AWS client construction using the configured local role profile."""

import boto3

from .config import Settings


def create_aws_session(settings: Settings) -> boto3.Session:
    return boto3.Session(
        profile_name=settings.aws_profile,
        region_name=settings.aws_region,
    )


def create_s3_client(session: boto3.Session):
    return session.client("s3")


def create_ledger_table(session: boto3.Session, table_name: str):
    return session.resource("dynamodb").Table(table_name)