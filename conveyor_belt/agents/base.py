"""Base agent — LLM abstraction with Anthropic primary / Gemini fallback."""

from __future__ import annotations

import logging

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from conveyor_belt.config import AgentConfig

logger = logging.getLogger(__name__)


def _build_llm(provider: str, model: str) -> BaseChatModel:
    """Instantiate a LangChain chat model for the given provider."""
    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(model=model, max_tokens=4096, temperature=0)
    elif provider == "google":
        from langchain_google_genai import ChatGoogleGenerativeAI

        return ChatGoogleGenerativeAI(model=model, max_output_tokens=4096, temperature=0)
    else:
        raise ValueError(f"Unknown LLM provider: {provider}")


class BaseAgent:
    """LLM agent with automatic fallback from primary to secondary provider."""

    def __init__(self, config: AgentConfig, system_prompt: str = "") -> None:
        self.config = config
        self.system_prompt = system_prompt
        self._primary: BaseChatModel | None = None
        self._fallback: BaseChatModel | None = None

    @property
    def primary(self) -> BaseChatModel:
        if self._primary is None:
            self._primary = _build_llm(
                self.config.primary.provider, self.config.primary.model
            )
        return self._primary

    @property
    def fallback(self) -> BaseChatModel:
        if self._fallback is None:
            self._fallback = _build_llm(
                self.config.fallback.provider, self.config.fallback.model
            )
        return self._fallback

    async def invoke(self, user_prompt: str) -> str:
        """Send a prompt to the primary LLM; fall back on failure."""
        messages = []
        if self.system_prompt:
            messages.append(SystemMessage(content=self.system_prompt))
        messages.append(HumanMessage(content=user_prompt))

        try:
            response = await self.primary.ainvoke(messages)
            return response.content
        except Exception as exc:
            logger.warning(
                "Primary LLM (%s/%s) failed: %s — falling back to %s/%s",
                self.config.primary.provider,
                self.config.primary.model,
                exc,
                self.config.fallback.provider,
                self.config.fallback.model,
            )
            try:
                response = await self.fallback.ainvoke(messages)
                return response.content
            except Exception as fallback_exc:
                logger.error("Fallback LLM also failed: %s", fallback_exc)
                raise RuntimeError(
                    f"Both LLM providers failed. "
                    f"Primary: {exc}. Fallback: {fallback_exc}"
                ) from fallback_exc
