"""TruLens evaluation for live Qdrant-backed RAG queries."""

import os

import numpy as np
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnablePassthrough
from langchain_openai import ChatOpenAI
from langchain_qdrant import QdrantVectorStore
from trulens.apps.langchain import TruChain
from trulens.core import Feedback, Select, TruSession
from trulens.providers.openai import OpenAI as TruOpenAI

from hybrid_rag.config import Settings


def setup_trulens_rag_evaluator(
    vector_store: QdrantVectorStore,
    app_name: str = "Docling_Qdrant_Hybrid_RAG",
    app_version: str = "v1_qwen3_768tok",
    settings: Settings | None = None,
):
    """Build a TruLens recorder for context, groundedness, and answer relevance."""
    judge_model = (
        settings.judge_model
        if settings
        else os.getenv("JUDGE_LLM_MODEL", "Qwen/Qwen2.5-72B-Instruct")
    )
    base_url = (
        settings.featherless_base_url
        if settings
        else os.getenv("FEATHERLESS_BASE_URL", "https://api.featherless.ai/v1")
    )
    api_key = settings.featherless_api_key if settings else os.environ["FEATHERLESS_API_KEY"]

    session = TruSession()
    provider = TruOpenAI(
        model_engine=judge_model,
        base_url=base_url,
        api_key=api_key,
    )

    retriever = vector_store.as_retriever(search_kwargs={"k": 5})
    prompt = ChatPromptTemplate.from_template(
        "Answer the question strictly using only the provided context:\n\n"
        "Context:\n{context}\n\nQuestion: {question}"
    )
    llm = ChatOpenAI(
        model=judge_model,
        base_url=base_url,
        api_key=api_key,
        temperature=0.0,
    )
    rag_chain = (
        {
            "context": retriever
            | (lambda documents: "\n\n".join(document.page_content for document in documents)),
            "question": RunnablePassthrough(),
        }
        | prompt
        | llm
        | StrOutputParser()
    )

    context_selector = TruChain.select_context(rag_chain)
    feedback_context = (
        Feedback(provider.context_relevance_with_cot_reasons, name="Context Relevance")
        .on_input()
        .on(context_selector)
        .aggregate(np.mean)
    )
    feedback_groundedness = (
        Feedback(provider.groundedness_measure_with_cot_reasons, name="Groundedness")
        .on(context_selector.collect())
        .on_output()
    )
    feedback_answer = (
        Feedback(provider.relevance_with_cot_reasons, name="Answer Relevance")
        .on_input()
        .on_output()
    )

    tru_recorder = TruChain(
        rag_chain,
        app_name=app_name,
        app_version=app_version,
        feedbacks=[feedback_context, feedback_groundedness, feedback_answer],
    )
    return tru_recorder, rag_chain, session