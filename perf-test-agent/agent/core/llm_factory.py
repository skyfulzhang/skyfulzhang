"""
agent/core/llm_factory.py
LLM 工厂模块 - 支持 OpenAI、Azure OpenAI 和 Ollama，带重试和超时配置。
"""

from typing import Any, Type

from langchain_core.language_models import BaseLanguageModel
from langchain_core.runnables import Runnable
from pydantic import BaseModel

from agent.utils.config import Settings
from agent.utils.logger import get_logger

logger = get_logger(__name__)


class LLMFactory:
    """LLM 工厂类。

    根据配置创建对应的 LangChain LLM 实例，统一处理 retry 和 timeout 配置。
    """

    @staticmethod
    def create(config: Settings) -> BaseLanguageModel:
        """创建 LLM 实例。

        Args:
            config: 全局配置对象。

        Returns:
            BaseLanguageModel: 对应提供商的 LLM 实例。

        Raises:
            ValueError: 不支持的 LLM 提供商。
        """
        provider = config.llm_provider.lower()
        logger.info("llm_creating", provider=provider)

        if provider == "openai":
            return LLMFactory._create_openai(config)
        elif provider == "azure":
            return LLMFactory._create_azure(config)
        elif provider == "ollama":
            return LLMFactory._create_ollama(config)
        else:
            raise ValueError(
                f"不支持的 LLM 提供商: {provider!r}，可选: openai / azure / ollama"
            )

    @staticmethod
    def create_with_structured_output(
        config: Settings,
        output_schema: Type[BaseModel],
    ) -> Runnable:
        """创建带结构化输出的 LLM Runnable。

        使用 LangChain 的 ``with_structured_output`` 特性，确保 LLM 返回
        符合 Pydantic schema 的结构化数据。

        Args:
            config: 全局配置对象。
            output_schema: 目标 Pydantic 模型类。

        Returns:
            Runnable: 带结构化输出的 LLM Runnable。
        """
        llm = LLMFactory.create(config)
        if hasattr(llm, "with_structured_output"):
            return llm.with_structured_output(output_schema)  # type: ignore[attr-defined]
        # Ollama 等不支持 function calling 的模型，降级为普通模式
        logger.warning(
            "structured_output_not_supported",
            provider=config.llm_provider,
        )
        return llm  # type: ignore[return-value]

    @staticmethod
    def _create_openai(config: Settings) -> BaseLanguageModel:
        """创建 OpenAI LLM。"""
        from langchain_openai import ChatOpenAI

        if not config.openai_api_key:
            raise ValueError("使用 OpenAI 时必须设置 OPENAI_API_KEY")

        return ChatOpenAI(
            model=config.openai_model,
            api_key=config.openai_api_key,  # type: ignore[arg-type]
            temperature=0.1,
            timeout=120,
            max_retries=3,
        )

    @staticmethod
    def _create_azure(config: Settings) -> BaseLanguageModel:
        """创建 Azure OpenAI LLM。"""
        from langchain_openai import AzureChatOpenAI

        if not all(
            [
                config.azure_openai_endpoint,
                config.azure_openai_api_key,
                config.azure_openai_deployment,
            ]
        ):
            raise ValueError(
                "使用 Azure OpenAI 时必须设置 AZURE_OPENAI_ENDPOINT、"
                "AZURE_OPENAI_API_KEY 和 AZURE_OPENAI_DEPLOYMENT"
            )

        return AzureChatOpenAI(
            azure_endpoint=config.azure_openai_endpoint,  # type: ignore[arg-type]
            api_key=config.azure_openai_api_key,  # type: ignore[arg-type]
            azure_deployment=config.azure_openai_deployment,  # type: ignore[arg-type]
            api_version="2024-08-01-preview",
            temperature=0.1,
            timeout=120,
            max_retries=3,
        )

    @staticmethod
    def _create_ollama(config: Settings) -> BaseLanguageModel:
        """创建 Ollama 本地 LLM。"""
        try:
            from langchain_community.chat_models import ChatOllama
        except ImportError as exc:
            raise ImportError(
                "使用 Ollama 需要安装 langchain-community: "
                "pip install langchain-community"
            ) from exc

        return ChatOllama(
            model=config.ollama_model,
            base_url=config.ollama_base_url,
            temperature=0.1,
            timeout=300,
        )
