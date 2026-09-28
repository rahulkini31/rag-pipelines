"""Ragas testset generation and retrieval evaluation."""

import os
import json
from typing import Any, List

from langchain_core.documents import Document
from langchain_core.language_models import BaseLanguageModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, LLMResult
from langchain_openai import ChatOpenAI
from langchain_qdrant import QdrantVectorStore
from qdrant_client import models
from ragas import EvaluationDataset, SingleTurnSample, evaluate
from ragas.embeddings import LangchainEmbeddingsWrapper
from ragas.llms import LangchainLLMWrapper
from ragas.metrics import LLMContextPrecisionWithReference, LLMContextRecall
from ragas.run_config import RunConfig
from ragas.testset import TestsetGenerator

from .config import Settings
from .vector_store import Qwen3FeatherlessEmbeddings


class _JsonModeLanguageModelAdapter(BaseLanguageModel):
    """Expose a LangChain JSON-mode runnable through Ragas's legacy LLM API."""

    runnable: Any
    temperature: float = 0.0

    @property
    def _llm_type(self) -> str:
        return "featherless-json-mode"

    def invoke(self, input, config=None, **kwargs):
        return self.runnable.invoke(input, config=config, **kwargs)

    async def ainvoke(self, input, config=None, **kwargs):
        return await self.runnable.ainvoke(input, config=config, **kwargs)

    def generate_prompt(self, prompts, stop=None, callbacks=None, **kwargs):
        generations = []
        for prompt in prompts:
            value = self.runnable.invoke(prompt)
            content = value if isinstance(value, str) else json.dumps(value)
            generations.append(
                [ChatGeneration(message=AIMessage(content=content))]
            )
        return LLMResult(generations=generations)

    async def agenerate_prompt(self, prompts, stop=None, callbacks=None, **kwargs):
        generations = []
        for prompt in prompts:
            value = await self.runnable.ainvoke(prompt)
            content = value if isinstance(value, str) else json.dumps(value)
            generations.append(
                [ChatGeneration(message=AIMessage(content=content))]
            )
        return LLMResult(generations=generations)


def get_ragas_judge_models(
    qwen_featherless_embeddings: Qwen3FeatherlessEmbeddings,
    settings: Settings | None = None,
) -> tuple[LangchainLLMWrapper, LangchainEmbeddingsWrapper]:
    """Build the Featherless judge LLM and embedding adapters used by Ragas."""
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
    judge_chat_model = ChatOpenAI(
        model=judge_model,
        base_url=base_url,
        api_key=api_key,
        temperature=0.0,
        max_tokens=4096,
    )
    json_mode_model = judge_chat_model.with_structured_output(
        method="json_mode",
        include_raw=False,
    )
    judge_llm = LangchainLLMWrapper(
        _JsonModeLanguageModelAdapter(runnable=json_mode_model),
        bypass_n=True,
    )
    return (
        judge_llm,
        LangchainEmbeddingsWrapper(qwen_featherless_embeddings),
    )


def generate_synthetic_testset_with_ragas(
    ingested_lc_docs: List[Document],
    qwen_featherless_embeddings: Qwen3FeatherlessEmbeddings,
    settings: Settings | None = None,
    testset_size: int = 10,
    output_path: str = "golden_ragas_testset.json",
    max_workers: int = 1,
    max_wait: int = 180,
    max_retries: int = 5,
    checkpoint_path: str | None = None,
):
    """Generate a resilient golden testset and persist run checkpoints."""
    evaluator_llm, evaluator_embeddings = get_ragas_judge_models(
        qwen_featherless_embeddings, settings=settings
    )
    generator = TestsetGenerator(
        llm=evaluator_llm,
        embedding_model=evaluator_embeddings,
    )
    run_config = RunConfig(
        max_workers=max_workers,
        max_wait=max_wait,
        max_retries=max_retries,
    )
    checkpoint_path = checkpoint_path or f"{output_path}.checkpoint.json"
    checkpoint = {
        "status": "running",
        "output_path": output_path,
        "testset_size": testset_size,
        "max_workers": max_workers,
        "max_wait": max_wait,
        "max_retries": max_retries,
    }
    with open(checkpoint_path, "w", encoding="utf-8") as checkpoint_file:
        json.dump(checkpoint, checkpoint_file, indent=2)

    try:
        testset = generator.generate_with_langchain_docs(
            documents=ingested_lc_docs,
            testset_size=testset_size,
            run_config=run_config,
            raise_exceptions=True,
        )
        dataframe = testset.to_pandas()
        dataframe.to_json(output_path, orient="records", indent=2)
    except Exception as exc:
        checkpoint.update({"status": "failed", "error": str(exc)})
        with open(checkpoint_path, "w", encoding="utf-8") as checkpoint_file:
            json.dump(checkpoint, checkpoint_file, indent=2)
        print(f"Ragas run encountered an error: {exc}")
        raise

    checkpoint.update({"status": "completed", "rows": len(dataframe)})
    with open(checkpoint_path, "w", encoding="utf-8") as checkpoint_file:
        json.dump(checkpoint, checkpoint_file, indent=2)
    return dataframe


def evaluate_qdrant_retrieval_with_ragas(
    vector_store: QdrantVectorStore,
    qwen_featherless_embeddings: Qwen3FeatherlessEmbeddings,
    test_records: List[dict[str, Any]],
    top_k: int = 5,
    tenant_id: str | None = None,
    settings: Settings | None = None,
):
    """Evaluate live Qdrant retrieval with Ragas context precision and recall."""
    evaluator_llm, _ = get_ragas_judge_models(qwen_featherless_embeddings, settings=settings)
    search_kwargs: dict[str, Any] = {"k": top_k}
    if tenant_id is not None:
        search_kwargs["filter"] = models.Filter(
            must=[
                models.FieldCondition(
                    key="metadata.tenant_id",
                    match=models.MatchValue(value=tenant_id),
                )
            ]
        )
    retriever = vector_store.as_retriever(search_kwargs=search_kwargs)

    samples = []
    for row in test_records:
        query = row["user_input"]
        retrieved_docs = retriever.invoke(query)
        samples.append(
            SingleTurnSample(
                user_input=query,
                retrieved_contexts=[doc.page_content for doc in retrieved_docs],
                reference=row["reference"],
            )
        )

    results = evaluate(
        dataset=EvaluationDataset(samples=samples),
        metrics=[
            LLMContextPrecisionWithReference(llm=evaluator_llm),
            LLMContextRecall(llm=evaluator_llm),
        ],
    )
    return results.to_pandas()