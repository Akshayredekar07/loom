import os

import pytest

from loom_app.catalog import build_provider, get_entry, load_catalog
from loom_provider.events import StreamError
from loom_provider.provider import ProviderMessage


@pytest.mark.parametrize(
    "provider_id",
    [
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
    ],
)
def test_catalog_row_smoke_when_api_key_present(provider_id: str) -> None:
    if not os.environ.get("LOOM_TEST_API_KEY"):
        pytest.skip("LOOM_TEST_API_KEY not set")

    catalog = load_catalog()
    entry = get_entry(catalog, provider_id)
    if entry.env_key and not os.environ.get(entry.env_key):
        pytest.skip(f"{entry.env_key} not set for {provider_id}")

    model = entry.models[0]
    if model.startswith("<"):
        pytest.skip(f"no concrete model configured for {provider_id}")

    provider = build_provider(entry, model)
    try:
        events = list(
            provider.stream(
                (ProviderMessage(role="user", content="Reply with exactly: ok"),),
                system="Reply in one word.",
            )
        )
    finally:
        provider.close()

    assert events
    assert not any(isinstance(event, StreamError) for event in events)


def test_local_catalog_row_smoke_when_endpoint_reachable() -> None:
    if os.environ.get("LOOM_TEST_LOCAL") != "1":
        pytest.skip("LOOM_TEST_LOCAL not set")

    catalog = load_catalog()
    entry = get_entry(catalog, "local")
    provider = build_provider(entry, entry.models[0])
    try:
        events = list(
            provider.stream(
                (ProviderMessage(role="user", content="Reply with exactly: ok"),),
                system="Reply in one word.",
            )
        )
    finally:
        provider.close()

    assert events
    assert not any(isinstance(event, StreamError) for event in events)
