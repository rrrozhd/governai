from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from governai.integrations.tool_calls import NormalizedToolCall, extract_tool_calls


class NormalizedLLMResponse(BaseModel):
    content: str | None = None
    tool_calls: list[NormalizedToolCall] = Field(default_factory=list)
    raw: Any = None


class GovernedLLM:
    """Small wrapper around LangChain chat models with normalized outputs."""

    def __init__(self, model: Any) -> None:
        """Initialize GovernedLLM."""
        self._model = model

    @property
    def model(self) -> Any:
        """Model."""
        return self._model

    def bind_tools(self, tools: list[Any], *, tool_choice: Any = None, **kwargs: Any) -> "GovernedLLM":
        """Bind tools."""
        binder = getattr(self._model, "bind_tools", None)
        if not callable(binder):
            raise RuntimeError("Underlying model does not support bind_tools(...)")
        options = dict(kwargs)
        if tool_choice is not None:
            options["tool_choice"] = tool_choice
        return GovernedLLM(binder(tools, **options))

    async def ainvoke(self, messages: Any, **kwargs: Any) -> NormalizedLLMResponse:
        """Ainvoke."""
        invoker = getattr(self._model, "ainvoke", None)
        if not callable(invoker):
            raise RuntimeError("Underlying model does not support ainvoke(...)")
        raw = await invoker(messages, **kwargs)
        return self._normalize(raw)

    def invoke(self, messages: Any, **kwargs: Any) -> NormalizedLLMResponse:
        """Invoke."""
        invoker = getattr(self._model, "invoke", None)
        if not callable(invoker):
            raise RuntimeError("Underlying model does not support invoke(...)")
        raw = invoker(messages, **kwargs)
        return self._normalize(raw)

    @classmethod
    def from_chat_openai(cls, **kwargs: Any) -> "GovernedLLM":
        """From chat openai."""
        try:
            from langchain_openai import ChatOpenAI  # type: ignore
        except Exception as exc:
            raise RuntimeError("GovernedLLM.from_chat_openai requires langchain-openai") from exc
        return cls(ChatOpenAI(**kwargs))

    def _normalize(self, raw: Any) -> NormalizedLLMResponse:
        """Internal helper to normalize."""
        content = getattr(raw, "content", None)
        if content is not None and not isinstance(content, str):
            content = str(content)
        return NormalizedLLMResponse(
            content=content,
            tool_calls=extract_tool_calls(raw),
            raw=raw,
        )

