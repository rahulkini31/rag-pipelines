"""Ranx evaluation for Qdrant sparse, dense, and hybrid retrieval."""

from typing import Dict

from langchain_qdrant import QdrantVectorStore, RetrievalMode
from qdrant_client import models
from ranx import Qrels, Run, compare


def run_qdrant_mode_for_ranx(
    vector_store: QdrantVectorStore,
    mode: RetrievalMode,
    queries: Dict[str, str],
    tenant_id: str,
    top_k: int = 10,
) -> Run:
    """Run evaluation queries in one Qdrant retrieval mode."""
    original_mode = vector_store.retrieval_mode
    vector_store.retrieval_mode = mode

    tenant_filter = models.Filter(
        must=[
            models.FieldCondition(
                key="metadata.tenant_id",
                match=models.MatchValue(value=tenant_id),
            )
        ]
    )

    run_dict: Dict[str, Dict[str, float]] = {}
    try:
        for query_id, query_text in queries.items():
            results_with_scores = vector_store.similarity_search_with_score(
                query=query_text,
                k=top_k,
                filter=tenant_filter,
            )
            scored_hits: Dict[str, float] = {}
            for rank_idx, (document, score) in enumerate(results_with_scores):
                chunk_key = (
                    f"{document.metadata['doc_id']}#chunk_"
                    f"{document.metadata['chunk_index']}"
                )
                scored_hits[chunk_key] = (
                    float(score) if score > 0 else 1.0 / (rank_idx + 1)
                )
            run_dict[query_id] = scored_hits
    finally:
        vector_store.retrieval_mode = original_mode

    return Run(run_dict, name=mode.value)


def benchmark_qdrant_with_ranx(
    vector_store: QdrantVectorStore,
    tenant_id: str,
    eval_queries: Dict[str, str],
    ground_truth_qrels: Dict[str, Dict[str, int]],
    top_k: int = 10,
):
    """Compare BM25, Qwen dense, and hybrid RRF retrieval with Ranx."""
    qrels = Qrels(ground_truth_qrels)
    runs = [
        run_qdrant_mode_for_ranx(
            vector_store, mode, eval_queries, tenant_id, top_k=top_k
        )
        for mode in (
            RetrievalMode.SPARSE,
            RetrievalMode.DENSE,
            RetrievalMode.HYBRID,
        )
    ]
    return compare(
        qrels=qrels,
        runs=runs,
        metrics=["hit_rate@5", "recall@5", "mrr@10", "ndcg@5", "map@5"],
        max_p=0.05,
    )