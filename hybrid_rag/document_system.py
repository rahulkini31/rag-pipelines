"""Document lifecycle orchestration across Docling, AWS, and Qdrant."""

import hashlib
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from boto3.dynamodb.conditions import Key
from docling_core.types.doc.document import DoclingDocument
from langchain_core.documents import Document
from qdrant_client import models

from .aws_clients import create_aws_session, create_ledger_table, create_s3_client
from .config import Settings
from .docling_pipeline import QwenDoclingChunkingEngine, create_converter
from .telemetry_phoenix import init_phoenix_telemetry, trace_pipeline_stage
from .vector_store import HybridVectorStore


class ProductionDocumentSystem:
    def __init__(
        self,
        collection_name: str = "enterprise_rag_kb",
        dense_dim: int = 4096,
        settings: Settings | None = None,
    ):
        self.settings = settings if settings is not None else Settings.from_environment()
        self.tracer = init_phoenix_telemetry()
        self.bucket_name = self.settings.s3_bucket_name
        self.table_name = self.settings.dynamodb_table_name
        self.collection_name = collection_name

        aws_session = create_aws_session(self.settings)
        self.s3 = create_s3_client(aws_session)
        self.ledger_table = create_ledger_table(aws_session, self.table_name)

        vector_store = HybridVectorStore(self.settings, collection_name, dense_dim)
        self.hybrid_vector_store = vector_store
        self.qdrant_client = vector_store.client
        self.vector_store = vector_store.store

        self.converter = create_converter()
        self.chunker = QwenDoclingChunkingEngine(
            tokenizer_model_id=self.settings.embedding_model
        )

    @staticmethod
    def _compute_sha256(file_path: Path) -> str:
        hasher = hashlib.sha256()
        with file_path.open("rb") as file_handle:
            while chunk := file_handle.read(65536):
                hasher.update(chunk)
        return hasher.hexdigest()

    def _upload_doclang_to_s3(
        self, document: DoclingDocument, tenant_id: str, doc_id: str, version: int
    ) -> str:
        s3_key = f"tenants/{tenant_id}/documents/{doc_id}/v{version}/artifact.dclx"
        with tempfile.NamedTemporaryFile(suffix=".dclx") as temporary_file:
            document.save_as_doclang_archive(Path(temporary_file.name))
            self.s3.upload_file(temporary_file.name, self.bucket_name, s3_key)
        return f"s3://{self.bucket_name}/{s3_key}"

    def load_doclang_from_s3(self, s3_uri: str) -> DoclingDocument:
        prefix = f"s3://{self.bucket_name}/"
        if not s3_uri.startswith(prefix):
            raise ValueError(f"S3 URI does not belong to configured bucket: {s3_uri}")
        s3_key = s3_uri.removeprefix(prefix)
        with tempfile.NamedTemporaryFile(suffix=".dclx") as temporary_file:
            self.s3.download_file(self.bucket_name, s3_key, temporary_file.name)
            return DoclingDocument.load_from_doclang_archive(Path(temporary_file.name))

    def _build_chunks(
        self,
        document: DoclingDocument,
        tenant_id: str,
        doc_id: str,
        version: int,
        filename: str,
        s3_uri: str,
    ) -> tuple[list[Document], list[str]]:
        return self.chunker.chunk_doclang_document(
            dl_doc=document,
            tenant_id=tenant_id,
            doc_id=doc_id,
            version=version,
            filename=filename,
            s3_uri=s3_uri,
        )

    def _delete_qdrant_points(self, tenant_id: str, doc_id: str) -> None:
        self.qdrant_client.delete(
            collection_name=self.collection_name,
            points_selector=models.FilterSelector(
                filter=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="metadata.tenant_id",
                            match=models.MatchValue(value=tenant_id),
                        ),
                        models.FieldCondition(
                            key="metadata.doc_id",
                            match=models.MatchValue(value=doc_id),
                        ),
                    ]
                )
            ),
        )

    def upload_document(
        self, file_path: str | Path, tenant_id: str, doc_id: str | None = None
    ) -> dict[str, Any]:
        path = Path(file_path)
        if not path.is_file():
            raise FileNotFoundError(path)
        document_id = doc_id or str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        self.ledger_table.put_item(
            Item={
                "tenant_id": tenant_id,
                "doc_id": document_id,
                "filename": path.name,
                "current_version": 1,
                "sha256_hash": self._compute_sha256(path),
                "status": "PROCESSING",
                "updated_at": now,
            }
        )
        try:
            with trace_pipeline_stage(
                "ingest_document_workflow",
                attributes={
                    "tenant_id": tenant_id,
                    "doc_id": document_id,
                    "filename": path.name,
                },
            ):
                with trace_pipeline_stage(
                    "docling_pdf_extraction", span_kind="TOOL"
                ) as parse_span:
                    docling_document = self.converter.convert(path).document
                    parse_span.set_attribute("docling.num_tables", len(docling_document.tables))
                    parse_span.set_attribute("docling.num_pages", len(docling_document.pages))

                with trace_pipeline_stage(
                    "s3_doclang_upload", span_kind="TOOL"
                ) as s3_span:
                    s3_uri = self._upload_doclang_to_s3(
                        docling_document, tenant_id, document_id, 1
                    )
                    s3_span.set_attribute("s3.uri", s3_uri)

                with trace_pipeline_stage(
                    "qwen3_hybrid_chunking", span_kind="PREPROCESSOR"
                ) as chunk_span:
                    documents, chunk_ids = self._build_chunks(
                        docling_document, tenant_id, document_id, 1, path.name, s3_uri
                    )
                    chunk_span.set_attribute("chunker.total_chunks", len(documents))

                with trace_pipeline_stage(
                    "qdrant_hybrid_upsert", span_kind="RETRIEVER"
                ):
                    self.vector_store.add_documents(
                        documents=documents, ids=chunk_ids, batch_size=32
                    )

                with trace_pipeline_stage(
                    "dynamodb_active_state_write", span_kind="TOOL"
                ):
                    self.ledger_table.update_item(
                        Key={"tenant_id": tenant_id, "doc_id": document_id},
                        UpdateExpression="SET #s = :status, s3_doclang_uri = :uri, chunk_count = :cnt, updated_at = :u",
                        ExpressionAttributeNames={"#s": "status"},
                        ExpressionAttributeValues={
                            ":status": "ACTIVE",
                            ":uri": s3_uri,
                            ":cnt": len(documents),
                            ":u": datetime.now(timezone.utc).isoformat(),
                        },
                    )
            return {
                "status": "ACTIVE",
                "doc_id": document_id,
                "version": 1,
                "s3_uri": s3_uri,
                "chunks": len(documents),
            }
        except Exception as error:
            self.ledger_table.update_item(
                Key={"tenant_id": tenant_id, "doc_id": document_id},
                UpdateExpression="SET #s = :status, error_msg = :err",
                ExpressionAttributeNames={"#s": "status"},
                ExpressionAttributeValues={":status": "FAILED", ":err": str(error)},
            )
            raise

    def delete_document(self, doc_id: str, tenant_id: str) -> dict[str, Any]:
        self._delete_qdrant_points(tenant_id, doc_id)
        prefix = f"tenants/{tenant_id}/documents/{doc_id}/"
        objects = [
            {"Key": item["Key"]}
            for page in self.s3.get_paginator("list_objects_v2").paginate(
                Bucket=self.bucket_name, Prefix=prefix
            )
            for item in page.get("Contents", [])
        ]
        if objects:
            self.s3.delete_objects(Bucket=self.bucket_name, Delete={"Objects": objects})
        self.ledger_table.delete_item(Key={"tenant_id": tenant_id, "doc_id": doc_id})
        return {"status": "DELETED", "doc_id": doc_id, "s3_objects_removed": len(objects)}

    def list_documents(self, tenant_id: str) -> list[dict[str, Any]]:
        response = self.ledger_table.query(KeyConditionExpression=Key("tenant_id").eq(tenant_id))
        return response.get("Items", [])