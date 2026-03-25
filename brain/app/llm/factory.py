from app.config import Settings
from app.llm.base import LLMProvider
from app.llm.anthropic_provider import AnthropicProvider
from app.llm.local_vllm import LocalVLLMProvider
from app.llm.openai_provider import OpenAIProvider


def build_llm_provider(settings: Settings) -> LLMProvider:
    if settings.llm_mode == "cloud":
        if settings.resolved_cloud_provider == "anthropic":
            return AnthropicProvider(settings)
        return OpenAIProvider(settings)
    return LocalVLLMProvider(settings)
