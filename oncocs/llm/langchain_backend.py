"""Adapter over any langchain BaseChatModel — the pluggable path."""
from __future__ import annotations

from oncocs.llm.ollama import _to_lc


class LangChainBackend:
    name = "langchain"

    def __init__(self, chat_model, name: str | None = None):
        self.chat_model = chat_model
        self.model_id = getattr(chat_model, "model", None) or getattr(
            chat_model, "model_name", type(chat_model).__name__)
        if name:
            self.name = name

    def complete(self, messages: list[dict[str, str]], *,
                 temperature: float = 0.0, seed: int | None = None) -> str:
        return self.chat_model.invoke(_to_lc(messages)).content
