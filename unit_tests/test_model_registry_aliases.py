"""Provider aliases used by the LLM profile UI and CLI."""

from testmcpy.cli.app import ModelProvider
from testmcpy.src.model_registry import get_models_by_provider


def test_claude_code_alias_uses_claude_sdk_models():
    assert get_models_by_provider("claude-code") == get_models_by_provider("claude-sdk")


def test_codex_sdk_alias_uses_codex_models():
    models = get_models_by_provider("codex-sdk")
    assert models
    assert models == get_models_by_provider("codex-cli")


def test_runtime_provider_aliases_use_canonical_registry_models():
    assert get_models_by_provider("grok") == get_models_by_provider("xai")
    assert get_models_by_provider("aws-bedrock") == get_models_by_provider("bedrock")


def test_cli_provider_choices_cover_every_runtime_factory_provider():
    assert {provider.value for provider in ModelProvider} >= {
        "anthropic",
        "assistant",
        "aws-bedrock",
        "bedrock",
        "chatbot",
        "claude-cli",
        "claude-code",
        "claude-sdk",
        "codex",
        "codex-cli",
        "codex-sdk",
        "gemini",
        "gemini-cli",
        "gemini-sdk",
        "google",
        "grok",
        "local",
        "ollama",
        "openai",
        "openrouter",
        "xai",
    }
