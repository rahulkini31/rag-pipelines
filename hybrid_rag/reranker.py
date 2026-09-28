"""Local Qwen3 cross-encoder reranking for Qdrant candidates."""

from __future__ import annotations

from typing import Iterable

from langchain_core.documents import Document
from sentence_transformers import CrossEncoder
import torch


class Qwen3CrossEncoderReranker:
    """Rank query/document candidates with a local Qwen3 cross-encoder."""

    def __init__(
        self,
        model: str = "Qwen/Qwen3-Reranker-0.6B",
        max_length: int = 4096,
        instruction: str = (
            "Given a technical query, determine whether the passage contains the "
            "exact facts, metrics, or architecture details to answer it."
        ),
    ) -> None:
        self.device = "mps" if torch.backends.mps.is_available() else "cpu"
        self.model = model
        self.instruction = instruction
        self.reranker = CrossEncoder(
            model,
            device=self.device,
            max_length=max_length,
            trust_remote_code=True,
        )

    def rerank(
        self,
        query: str,
        documents: Iterable[Document],
        top_k: int | None = None,
    ) -> list[tuple[Document, float]]:
        """Score query/document pairs and return them in descending order."""
        document_list = list(documents)
        if not document_list:
            return []

        formatted_query = f"Instruct: {self.instruction}\nQuery: {query}"
        ranked = self.reranker.rank(
            query=formatted_query,
            documents=[document.page_content for document in document_list],
            top_k=top_k,
            return_documents=False,
        )
        return [
            (document_list[item["corpus_id"]], float(item["score"]))
            for item in ranked
        ]
