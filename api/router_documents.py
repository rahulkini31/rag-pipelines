"""Document management endpoints."""

import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from pydantic import BaseModel

from hybrid_rag.document_system import ProductionDocumentSystem

from .auth import CognitoUser, get_current_user
from .dependencies import get_document_system, get_ledger_table
from .events import publish_status_update
from .sharing import DocumentSharesStore
from .sharing import get_shares_store

router = APIRouter(prefix="/documents", tags=["documents"])


class BulkDeleteRequest(BaseModel):
    doc_ids: list[str]


class RenameRequest(BaseModel):
    new_filename: str


class ShareRequest(BaseModel):
    recipient_tenant_id: str


def _is_owner(doc: dict[str, Any], user: CognitoUser) -> bool:
    return doc.get("tenant_id") == user.tenant_id


async def _is_accessible(
    doc_id: str,
    user: CognitoUser,
    system: ProductionDocumentSystem,
    shares: DocumentSharesStore,
) -> tuple[bool, dict[str, Any] | None]:
    doc = system.ledger_table.get_item(
        Key={"tenant_id": user.tenant_id, "doc_id": doc_id}
    ).get("Item")
    if doc:
        return True, doc
    shares_list = shares.list_shares(doc_id)
    for share in shares_list:
        if share.get("recipient_tenant_id") == user.tenant_id:
            # Fetch the owner's copy of the ledger item.
            owner_doc = system.ledger_table.get_item(
                Key={
                    "tenant_id": share.get("owner_tenant_id"),
                    "doc_id": doc_id,
                }
            ).get("Item")
            return True, owner_doc
    return False, None


@router.get("")
async def list_documents(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    status_filter: str | None = Query(None, alias="status"),
    search: str | None = Query(None),
    user: CognitoUser = Depends(get_current_user),
    ledger_table: Any = Depends(get_ledger_table),
    shares: DocumentSharesStore = Depends(get_shares_store),
) -> dict:
    # Owned documents
    response = ledger_table.query(
        KeyConditionExpression="tenant_id = :t",
        ExpressionAttributeValues={":t": user.tenant_id},
    )
    items = response.get("Items", [])

    # Shared documents
    try:
        shared = shares.list_shared_with(user.tenant_id)
        owner_keys = [
            {
                "tenant_id": share.get("owner_tenant_id"),
                "doc_id": share.get("shared_doc_id"),
            }
            for share in shared
        ]
        # DynamoDB BatchGetItem supports up to 100 keys.
        if owner_keys:
            batch = ledger_table.meta.client.batch_get_item(
                RequestItems={
                    ledger_table.name: {
                        "Keys": owner_keys[:100],
                    }
                }
            )
            shared_items = batch.get("Responses", {}).get(ledger_table.name, [])
            for item in shared_items:
                item["_shared"] = True
            items.extend(shared_items)
    except Exception:
        # If the shares table does not exist yet, continue with owned docs.
        pass

    if status_filter:
        items = [item for item in items if item.get("status") == status_filter]
    if search:
        term = search.lower()
        items = [
            item for item in items if term in (item.get("filename") or "").lower()
        ]

    total = len(items)
    start = (page - 1) * limit
    end = start + limit
    return {"total": total, "page": page, "limit": limit, "items": items[start:end]}


@router.post("/upload")
async def upload_documents(
    files: list[UploadFile] = File(...),
    user: CognitoUser = Depends(get_current_user),
    system: ProductionDocumentSystem = Depends(get_document_system),
) -> dict:
    results = []
    errors = []
    for upload in files:
        suffix = Path(upload.filename or "document.pdf").suffix or ".pdf"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            content = await upload.read()
            tmp.write(content)
            tmp_path = Path(tmp.name)
        try:
            publish_status_update(
                user.tenant_id,
                "upload_started",
                {"filename": upload.filename},
            )
            result = system.upload_document(tmp_path, user.tenant_id)
            system.ledger_table.update_item(
                Key={"tenant_id": user.tenant_id, "doc_id": result["doc_id"]},
                UpdateExpression="SET filename = :fname",
                ExpressionAttributeValues={":fname": upload.filename},
            )
            result["filename"] = upload.filename
            results.append(result)
            publish_status_update(
                user.tenant_id,
                "upload_completed",
                {"doc_id": result["doc_id"], "filename": upload.filename},
            )
        except Exception as exc:
            errors.append({"filename": upload.filename, "error": str(exc)})
            publish_status_update(
                user.tenant_id,
                "upload_failed",
                {"filename": upload.filename, "error": str(exc)},
            )
        finally:
            tmp_path.unlink(missing_ok=True)
    return {"uploaded": results, "errors": errors}


@router.delete("/{doc_id}")
async def delete_document(
    doc_id: str,
    user: CognitoUser = Depends(get_current_user),
    system: ProductionDocumentSystem = Depends(get_document_system),
    shares: DocumentSharesStore = Depends(get_shares_store),
) -> dict:
    accessible, doc = await _is_accessible(doc_id, user, system, shares)
    if not accessible or not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    if not _is_owner(doc, user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not document owner")
    result = system.delete_document(doc_id, user.tenant_id)
    # Clean up shares for this document.
    try:
        for share in shares.list_shares(doc_id):
            shares.revoke(
                share.get("owner_tenant_id"),
                doc_id,
                share.get("recipient_tenant_id"),
            )
    except Exception:
        pass
    publish_status_update(
        user.tenant_id,
        "document_deleted",
        {"doc_id": doc_id},
    )
    return result


@router.post("/bulk-delete")
async def bulk_delete_documents(
    request: BulkDeleteRequest,
    user: CognitoUser = Depends(get_current_user),
    system: ProductionDocumentSystem = Depends(get_document_system),
    shares: DocumentSharesStore = Depends(get_shares_store),
) -> dict:
    deleted = []
    errors = []
    for doc_id in request.doc_ids:
        accessible, doc = await _is_accessible(doc_id, user, system, shares)
        if not accessible or not doc:
            errors.append({"doc_id": doc_id, "error": "not found"})
            continue
        if not _is_owner(doc, user):
            errors.append({"doc_id": doc_id, "error": "not owner"})
            continue
        try:
            system.delete_document(doc_id, user.tenant_id)
            deleted.append(doc_id)
            publish_status_update(user.tenant_id, "document_deleted", {"doc_id": doc_id})
        except Exception as exc:
            errors.append({"doc_id": doc_id, "error": str(exc)})
    return {"deleted": deleted, "errors": errors}


@router.patch("/{doc_id}/rename")
async def rename_document(
    doc_id: str,
    request: RenameRequest,
    user: CognitoUser = Depends(get_current_user),
    system: ProductionDocumentSystem = Depends(get_document_system),
    shares: DocumentSharesStore = Depends(get_shares_store),
) -> dict:
    accessible, doc = await _is_accessible(doc_id, user, system, shares)
    if not accessible or not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    if not _is_owner(doc, user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not document owner")
    system.ledger_table.update_item(
        Key={"tenant_id": user.tenant_id, "doc_id": doc_id},
        UpdateExpression="SET filename = :fname, updated_at = :u",
        ExpressionAttributeValues={
            ":fname": request.new_filename,
            ":u": datetime.now(timezone.utc).isoformat(),
        },
    )
    publish_status_update(
        user.tenant_id,
        "document_renamed",
        {"doc_id": doc_id, "filename": request.new_filename},
    )
    return {"doc_id": doc_id, "filename": request.new_filename}


@router.get("/{doc_id}")
async def get_document(
    doc_id: str,
    user: CognitoUser = Depends(get_current_user),
    system: ProductionDocumentSystem = Depends(get_document_system),
    shares: DocumentSharesStore = Depends(get_shares_store),
) -> dict:
    accessible, doc = await _is_accessible(doc_id, user, system, shares)
    if not accessible or not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    presigned_url = None
    s3_uri = doc.get("s3_doclang_uri")
    if s3_uri and _is_owner(doc, user):
        prefix = f"s3://{system.bucket_name}/"
        if s3_uri.startswith(prefix):
            key = s3_uri[len(prefix):]
            try:
                presigned_url = system.s3.generate_presigned_url(
                    "get_object",
                    Params={"Bucket": system.bucket_name, "Key": key.replace(".dclx", ".pdf")},
                    ExpiresIn=300,
                )
            except Exception:
                pass
    doc["presigned_url"] = presigned_url
    return doc


@router.get("/{doc_id}/preview")
async def preview_document(
    doc_id: str,
    user: CognitoUser = Depends(get_current_user),
    system: ProductionDocumentSystem = Depends(get_document_system),
    shares: DocumentSharesStore = Depends(get_shares_store),
) -> dict:
    accessible, doc = await _is_accessible(doc_id, user, system, shares)
    if not accessible or not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    s3_uri = doc.get("s3_doclang_uri")
    if not s3_uri:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No document artifact")

    try:
        dl_doc = system.load_doclang_from_s3(s3_uri)
        markdown = dl_doc.export_to_markdown()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to load preview: {exc}",
        )

    return {
        "doc_id": doc_id,
        "chunk_count": doc.get("chunk_count"),
        "markdown": markdown,
    }


@router.get("/{doc_id}/versions")
async def get_document_versions(
    doc_id: str,
    user: CognitoUser = Depends(get_current_user),
    system: ProductionDocumentSystem = Depends(get_document_system),
    shares: DocumentSharesStore = Depends(get_shares_store),
) -> dict:
    accessible, doc = await _is_accessible(doc_id, user, system, shares)
    if not accessible or not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    return {"versions": [{"version": doc.get("current_version", 1), "updated_at": doc.get("updated_at")}]}


@router.post("/{doc_id}/share")
async def share_document(
    doc_id: str,
    request: ShareRequest,
    user: CognitoUser = Depends(get_current_user),
    ledger_table=Depends(get_ledger_table),
    shares: DocumentSharesStore = Depends(get_shares_store),
) -> dict:
    doc = ledger_table.get_item(Key={"tenant_id": user.tenant_id, "doc_id": doc_id}).get("Item")
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    if not _is_owner(doc, user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not document owner")
    try:
        result = shares.share(user.tenant_id, doc_id, request.recipient_tenant_id)
        publish_status_update(
            user.tenant_id,
            "document_shared",
            {
                "doc_id": doc_id,
                "recipient_tenant_id": request.recipient_tenant_id,
            },
        )
        return {**result, "status": "shared"}
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create share: {exc}",
        )


@router.delete("/{doc_id}/share/{recipient_tenant_id}")
async def revoke_share(
    doc_id: str,
    recipient_tenant_id: str,
    user: CognitoUser = Depends(get_current_user),
    ledger_table=Depends(get_ledger_table),
    shares: DocumentSharesStore = Depends(get_shares_store),
) -> dict:
    doc = ledger_table.get_item(Key={"tenant_id": user.tenant_id, "doc_id": doc_id}).get("Item")
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    if not _is_owner(doc, user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not document owner")
    try:
        result = shares.revoke(user.tenant_id, doc_id, recipient_tenant_id)
        publish_status_update(
            user.tenant_id,
            "share_revoked",
            {"doc_id": doc_id, "recipient_tenant_id": recipient_tenant_id},
        )
        return {**result, "status": "revoked"}
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to revoke share: {exc}",
        )


@router.get("/{doc_id}/shares")
async def list_shares(
    doc_id: str,
    user: CognitoUser = Depends(get_current_user),
    ledger_table=Depends(get_ledger_table),
    shares: DocumentSharesStore = Depends(get_shares_store),
) -> dict:
    doc = ledger_table.get_item(Key={"tenant_id": user.tenant_id, "doc_id": doc_id}).get("Item")
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    if not _is_owner(doc, user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not document owner")
    try:
        items = shares.list_shares(doc_id, owner_tenant_id=user.tenant_id)
        return {"shares": items}
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list shares: {exc}",
        )
