from pathlib import Path

import pytest

from loom_app.catalog import build_provider, default_catalog_path, get_entry, load_catalog
from loom_provider.anthropic_messages import AnthropicMessagesProvider
from loom_provider.openai_compatible import OpenAICompatibleProvider


def test_default_catalog_has_fifteen_providers() -> None:
    catalog = load_catalog()
    assert len(catalog) == 15
    assert {entry.id for entry in catalog} == {
        "openai",
        "anthropic",
        "deepseek",
        "qwen",
        "kimi",
        "minimax",
        "zai",
        "openrouter",
        "groq",
        "together",
        "fireworks",
        "xai",
        "nvidia",
        "huggingface",
        "local",
    }


def test_load_catalog_from_explicit_path(tmp_path: Path) -> None:
    catalog_file = tmp_path / "providers.toml"
    catalog_file.write_text(
        """
[[provider]]
id = "demo"
protocol = "openai-compatible"
base_url = "https://example.invalid/v1"
env_key = "DEMO_API_KEY"
models = ["demo-model"]
""".strip(),
        encoding="utf-8",
    )
    catalog = load_catalog(catalog_file)
    assert len(catalog) == 1
    assert catalog[0].id == "demo"
    assert catalog[0].models == ("demo-model",)


def test_build_provider_selects_implementation_by_protocol(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog = load_catalog()
    openai_entry = get_entry(catalog, "openai")
    anthropic_entry = get_entry(catalog, "anthropic")
    local_entry = get_entry(catalog, "local")

    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "anthropic-key")
    monkeypatch.delenv("LOCAL_API_KEY", raising=False)

    openai_provider = build_provider(openai_entry, openai_entry.models[0])
    anthropic_provider = build_provider(anthropic_entry, anthropic_entry.models[0])
    local_provider = build_provider(local_entry, local_entry.models[0])

    assert isinstance(openai_provider, OpenAICompatibleProvider)
    assert openai_provider.api_key == "openai-key"
    assert isinstance(anthropic_provider, AnthropicMessagesProvider)
    assert anthropic_provider.api_key == "anthropic-key"
    assert isinstance(local_provider, OpenAICompatibleProvider)
    assert local_provider.api_key == ""


def test_build_provider_rejects_unknown_protocol() -> None:
    from loom_app.catalog import CatalogEntry

    entry = CatalogEntry(
        id="bad",
        protocol="gemini-native",
        base_url="https://example.invalid",
        env_key="BAD_KEY",
        models=("x",),
    )
    with pytest.raises(ValueError, match="unknown protocol"):
        build_provider(entry, "x")


def test_bundled_catalog_path_exists() -> None:
    assert default_catalog_path().is_file()
