"""Evaluation runner endpoints wired to hybrid_rag evaluation modules with S3 persistence."""

import glob
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any

import boto3
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from hybrid_rag.evaluation import benchmark_qdrant_with_ranx
from hybrid_rag.evaluation_ragas import (
    evaluate_qdrant_retrieval_with_ragas,
    generate_synthetic_testset_with_ragas,
)
from hybrid_rag.vector_store import HybridVectorStore

from .auth import CognitoUser, get_current_user
from .dependencies import get_document_system, get_embeddings, get_settings, get_vector_store

router = APIRouter(prefix="/evals", tags=["evaluations"])

_eval_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="eval_runner")

EVAL_S3_PREFIX = "evaluations/"


class RanxRequest(BaseModel):
    queries: dict[str, str] = {}
    qrels: dict[str, dict[str, int]] = {}
    top_k: int = 10


class RagasGenerateRequest(BaseModel):
    testset_size: int = 10


class RagasEvaluateRequest(BaseModel):
    testset_path: str | None = None
    test_records: list[dict[str, Any]] | None = None
    top_k: int = 5


class TruLensRequest(BaseModel):
    queries: list[str] = []
    app_name: str = "Docling_Qdrant_Hybrid_RAG"
    app_version: str = "v1_qwen3_768tok"


def _now_compact() -> str:
    return datetime.now(timezone.utc).isoformat().replace(":", "-")


def _get_s3_client(settings):
    session = boto3.Session(
        profile_name=settings.aws_profile,
        region_name=settings.aws_region,
    )
    return session.client("s3")


def _save_eval_result_to_s3(settings, tenant_id: str, eval_type: str, result: dict) -> str:
    s3 = _get_s3_client(settings)
    bucket = settings.s3_bucket_name
    eval_id = f"{eval_type}_{_now_compact()}"
    s3_key = f"{EVAL_S3_PREFIX}{tenant_id}/{eval_id}.json"
    payload = {
        "eval_id": eval_id,
        "eval_type": eval_type,
        "tenant_id": tenant_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "result": result,
    }
    s3.put_object(
        Bucket=bucket,
        Key=s3_key,
        Body=json.dumps(payload, indent=2, default=str).encode("utf-8"),
        ContentType="application/json",
    )
    return s3_key


def _list_eval_results_from_s3(settings, tenant_id: str) -> list[dict]:
    s3 = _get_s3_client(settings)
    bucket = settings.s3_bucket_name
    prefix = f"{EVAL_S3_PREFIX}{tenant_id}/"
    results: list[dict] = []
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            try:
                body = s3.get_object(Bucket=bucket, Key=key)["Body"].read().decode("utf-8")
                data = json.loads(body)
            except Exception:
                continue
            results.append(
                {
                    "eval_id": data.get("eval_id") or key.rsplit("/", 1)[-1].removesuffix(".json"),
                    "eval_type": data.get("eval_type", "unknown"),
                    "timestamp": data.get("timestamp", ""),
                    "status": data.get("result", {}).get("status", "unknown"),
                    "s3_key": key,
                }
            )
    results.sort(key=lambda item: item.get("timestamp", ""), reverse=True)
    return results


def _load_corpus_test_records(tenant_id: str) -> list[dict[str, Any]]:
    patterns = [
        f"ragas_testset_{tenant_id}_*.json",
        "golden_ragas_testset.json",
        "research_report_ragas_testset.json",
    ]
    for pattern in patterns:
        for path in sorted(glob.glob(pattern), reverse=True):
            try:
                with open(path, encoding="utf-8") as fh:
                    data = json.load(fh)
                if isinstance(data, list) and data:
                    return data
            except Exception:
                continue
    return []


def _keyword_grade(reference: str, chunk_text: str) -> int:
    ref_tokens = {token.lower() for token in re.findall(r"[a-zA-Z]{4,}", reference or "")}
    if not ref_tokens:
        return 0
    chunk_tokens = set(re.findall(r"[a-zA-Z0-9]{2,}", (chunk_text or "").lower()))
    overlap = sum(1 for token in ref_tokens if token in chunk_tokens) / len(ref_tokens)
    if overlap >= 0.5:
        return 2
    if overlap >= 0.25:
        return 1
    return 0


def _corpus_chunk_records(store, tenant_id: str, limit: int = 10) -> list[dict[str, Any]]:
    from qdrant_client import models as qmodels

    tenant_filter = qmodels.Filter(
        must=[
            qmodels.FieldCondition(
                key="metadata.tenant_id",
                match=qmodels.MatchValue(value=tenant_id),
            )
        ]
    )
    points, _ = store.client.scroll(
        collection_name=store.collection_name,
        limit=limit,
        scroll_filter=tenant_filter,
        with_payload=True,
    )
    records: list[dict[str, Any]] = []
    for point in points:
        payload = point.payload or {}
        metadata = payload.get("metadata", {}) or {}
        text = payload.get("page_content") or ""
        if not text:
            continue
        headings = metadata.get("headings") or []
        query = " ".join(str(h) for h in headings).strip() or text[:200]
        records.append(
            {
                "user_input": query,
                "reference": text,
                "chunk_key": f"{metadata.get('doc_id')}#chunk_{metadata.get('chunk_index')}",
            }
        )
    return records


def _build_corpus_queries_and_qrels(
    store,
    tenant_id: str,
    grade_candidates: int = 20,
) -> tuple[dict[str, str], dict[str, dict[str, int]], str]:
    from qdrant_client import models as qmodels

    records = _load_corpus_test_records(tenant_id)
    source = "ragas_testset"
    if not records:
        records = _corpus_chunk_records(store, tenant_id)
        source = "corpus_chunks"
    if not records:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No evaluation material available. Upload documents or run 'Ragas Generate' first.",
        )

    tenant_filter = qmodels.Filter(
        must=[
            qmodels.FieldCondition(
                key="metadata.tenant_id",
                match=qmodels.MatchValue(value=tenant_id),
            )
        ]
    )

    queries: dict[str, str] = {}
    qrels: dict[str, dict[str, int]] = {}
    for record in records:
        query_text = record.get("user_input")
        if not query_text:
            continue
        qid = f"q{len(queries)}"
        queries[qid] = query_text
        if source == "corpus_chunks":
            chunk_key = record.get("chunk_key")
            if chunk_key:
                qrels[qid] = {chunk_key: 2}
            continue
        reference = record.get("reference") or ""
        if not reference:
            continue
        candidates = store.similarity_search(query=query_text, k=grade_candidates, filter=tenant_filter)
        grades: dict[str, int] = {}
        for doc in candidates:
            metadata = doc.metadata or {}
            chunk_key = f"{metadata.get('doc_id')}#chunk_{metadata.get('chunk_index')}"
            grade = _keyword_grade(reference, doc.page_content)
            if grade > 0:
                grades[chunk_key] = grade
        if grades:
            qrels[qid] = grades
    return queries, qrels, source


async def _run_in_executor(fn) -> Any:
    import asyncio

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(_eval_executor, fn)


@router.post("/ranx")
async def run_ranx(
    request: RanxRequest,
    user: CognitoUser = Depends(get_current_user),
    vector_store: HybridVectorStore = Depends(get_vector_store),
    settings=Depends(get_settings),
) -> dict:
    def _run():
        queries = request.queries
        qrels = request.qrels
        source = "provided"
        if not queries or not qrels:
            auto_queries, auto_qrels, source = _build_corpus_queries_and_qrels(
                vector_store.store, user.tenant_id
            )
            queries = queries or auto_queries
            qrels = qrels or auto_qrels
        report = benchmark_qdrant_with_ranx(
            vector_store=vector_store.store,
            tenant_id=user.tenant_id,
            eval_queries=queries,
            ground_truth_qrels=qrels,
            top_k=request.top_k,
        )
        return {"report": str(report), "num_queries": len(queries), "query_source": source}

    try:
        result = await _run_in_executor(_run)
        result.update({"tenant_id": user.tenant_id, "status": "completed"})
        s3_key = _save_eval_result_to_s3(settings, user.tenant_id, "ranx", result)
        return {**result, "s3_key": s3_key}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ranx evaluation failed: {exc}",
        )


@router.post("/ragas/generate")
async def run_ragas_generate(
    request: RagasGenerateRequest,
    user: CognitoUser = Depends(get_current_user),
    system=Depends(get_document_system),
    embeddings=Depends(get_embeddings),
    settings=Depends(get_settings),
) -> dict:
    response = system.ledger_table.query(
        KeyConditionExpression="tenant_id = :t",
        ExpressionAttributeValues={":t": user.tenant_id},
    )
    items = response.get("Items", [])
    if not items:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No documents found for this tenant",
        )

    def _run():
        all_documents = []
        for item in items:
            s3_uri = item.get("s3_doclang_uri")
            if not s3_uri:
                continue
            try:
                dl_doc = system.load_doclang_from_s3(s3_uri)
                documents, _ = system.chunker.chunk_doclang_document(
                    dl_doc=dl_doc,
                    tenant_id=user.tenant_id,
                    doc_id=item.get("doc_id"),
                    version=int(item.get("current_version", 1)),
                    filename=item.get("filename", "document.pdf"),
                    s3_uri=s3_uri,
                )
                all_documents.extend(documents)
            except Exception:
                continue
        if not all_documents:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="No documents could be loaded for testset generation",
            )

        output_path = f"ragas_testset_{user.tenant_id}_{_now_compact()}.json"
        dataframe = generate_synthetic_testset_with_ragas(
            ingested_lc_docs=all_documents,
            qwen_featherless_embeddings=embeddings,
            settings=system.settings,
            testset_size=request.testset_size,
            output_path=output_path,
            max_workers=1,
        )
        return {
            "output_path": output_path,
            "documents_used": len(items),
            "chunks_used": len(all_documents),
            "rows": len(dataframe),
            "preview": json.loads(dataframe.head(5).to_json(orient="records")),
        }

    try:
        result = await _run_in_executor(_run)
        result.update({"tenant_id": user.tenant_id, "status": "completed"})
        s3_key = _save_eval_result_to_s3(settings, user.tenant_id, "ragas_generate", result)
        return {**result, "s3_key": s3_key}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ragas testset generation failed: {exc}",
        )


@router.post("/ragas/evaluate")
async def run_ragas_evaluate(
    request: RagasEvaluateRequest,
    user: CognitoUser = Depends(get_current_user),
    vector_store: HybridVectorStore = Depends(get_vector_store),
    embeddings=Depends(get_embeddings),
    settings=Depends(get_settings),
) -> dict:
    def _run():
        test_records = request.test_records
        record_source = "provided"
        if not test_records and request.testset_path and os.path.exists(request.testset_path):
            import pandas as pd

            test_records = json.loads(pd.read_json(request.testset_path).to_json(orient="records"))
            record_source = "testset_path"
        if not test_records:
            test_records = _load_corpus_test_records(user.tenant_id)
            record_source = "ragas_testset"
        if not test_records:
            test_records = _corpus_chunk_records(vector_store.store, user.tenant_id)
            record_source = "corpus_chunks"
        if not test_records:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="No test records available. Upload documents or run 'Ragas Generate' first.",
            )
        dataframe = evaluate_qdrant_retrieval_with_ragas(
            vector_store=vector_store.store,
            qwen_featherless_embeddings=embeddings,
            test_records=test_records,
            top_k=request.top_k,
            tenant_id=user.tenant_id,
            settings=settings,
        )
        return {
            "num_records": len(test_records),
            "record_source": record_source,
            "results": json.loads(dataframe.to_json(orient="records")),
        }

    try:
        result = await _run_in_executor(_run)
        result.update({"tenant_id": user.tenant_id, "status": "completed"})
        s3_key = _save_eval_result_to_s3(settings, user.tenant_id, "ragas_evaluate", result)
        return {**result, "s3_key": s3_key}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ragas evaluation failed: {exc}",
        )


@router.post("/trulens")
async def run_trulens(
    request: TruLensRequest,
    user: CognitoUser = Depends(get_current_user),
    vector_store: HybridVectorStore = Depends(get_vector_store),
    settings=Depends(get_settings),
) -> dict:
    def _run():
        from hybrid_rag.evaluation_trulens import setup_trulens_rag_evaluator

        queries = request.queries
        source = "provided"
        if not queries:
            records = _load_corpus_test_records(user.tenant_id)
            source = "ragas_testset"
            queries = [record["user_input"] for record in records if record.get("user_input")][:10]
        if not queries:
            chunk_records = _corpus_chunk_records(vector_store.store, user.tenant_id)
            source = "corpus_chunks"
            queries = [record["user_input"] for record in chunk_records if record.get("user_input")][:10]
        if not queries:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="No queries available. Upload documents or run 'Ragas Generate' first.",
            )
        tru_recorder, rag_chain, session = setup_trulens_rag_evaluator(
            vector_store=vector_store.store,
            app_name=request.app_name,
            app_version=request.app_version,
            settings=settings,
        )
        feedbacks = []
        with tru_recorder as recording:
            for query in queries:
                answer = rag_chain.invoke(query)
                feedbacks.append({"query": query, "answer": answer})
        return {
            "num_queries": len(queries),
            "queries": queries,
            "query_source": source,
            "feedbacks": feedbacks,
        }

    try:
        result = await _run_in_executor(_run)
        result.update({"tenant_id": user.tenant_id, "status": "completed"})
        s3_key = _save_eval_result_to_s3(settings, user.tenant_id, "trulens", result)
        return {**result, "s3_key": s3_key}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"TruLens evaluation failed: {exc}",
        )


@router.get("/history")
async def list_eval_history(
    user: CognitoUser = Depends(get_current_user),
    settings=Depends(get_settings),
) -> dict:
    try:
        results = _list_eval_results_from_s3(settings, user.tenant_id)
        return {"tenant_id": user.tenant_id, "results": results}
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list evaluation history: {exc}",
        )


@router.get("/result/{eval_id}")
async def get_eval_result(
    eval_id: str,
    user: CognitoUser = Depends(get_current_user),
    settings=Depends(get_settings),
) -> dict:
    try:
        s3_key = f"{EVAL_S3_PREFIX}{user.tenant_id}/{eval_id}.json"
        s3 = _get_s3_client(settings)
        body = s3.get_object(Bucket=settings.s3_bucket_name, Key=s3_key)["Body"].read().decode("utf-8")
        return json.loads(body)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Evaluation result not found: {exc}",
        )


@router.get("/results")
async def list_eval_results_alias(
    user: CognitoUser = Depends(get_current_user),
    settings=Depends(get_settings),
) -> dict:
    return await list_eval_history(user=user, settings=settings)
