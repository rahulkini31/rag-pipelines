"""Featherless AI client using its OpenAI-compatible API."""

from langchain_openai import ChatOpenAI

from .config import Settings


def create_llm(settings: Settings) -> ChatOpenAI:
    return ChatOpenAI(
        model=settings.featherless_model,
        api_key=settings.featherless_api_key,
        base_url=settings.featherless_base_url,
    )