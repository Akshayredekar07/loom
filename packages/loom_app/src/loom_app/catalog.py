from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

from loom_provider.anthropic_messages import AnthropicMessagesProvider
from loom_provider.openai_compatible import OpenAICompatibleProvider
from loom_provider.provider import Provider


@dataclass(frozen=True, slots=True)
class CatalogEntry:
    id: str
    protocol: str
    base_url: str
    env_key: str
    models: tuple[str, ...]


def default_catalog_path() -> Path:
    return Path(__file__).with_name("providers.toml")


def load_catalog(path: Path | None = None) -> tuple[CatalogEntry, ...]:
    catalog_path = path or default_catalog_path()
    with catalog_path.open("rb") as handle:
        data = tomllib.load(handle)
    entries: list[CatalogEntry] = []
    for row in data.get("provider", []):
        entries.append(
            CatalogEntry(
                id=str(row["id"]),
                protocol=str(row["protocol"]),
                base_url=str(row["base_url"]),
                env_key=str(row.get("env_key", "")),
                models=tuple(str(model) for model in row.get("models", [])),
            )
        )
    return tuple(entries)


def get_entry(catalog: tuple[CatalogEntry, ...], provider_id: str) -> CatalogEntry:
    for entry in catalog:
        if entry.id == provider_id:
            return entry
    raise KeyError(f"unknown provider id: {provider_id}")


def build_provider(entry: CatalogEntry, model: str) -> Provider:
    api_key = os.environ.get(entry.env_key, "") if entry.env_key else ""
    match entry.protocol:
        case "openai-compatible":
            return OpenAICompatibleProvider(
                base_url=entry.base_url,
                api_key=api_key,
                model=model,
            )
        case "anthropic-messages":
            return AnthropicMessagesProvider(
                base_url=entry.base_url,
                api_key=api_key,
                model=model,
            )
        case _:
            raise ValueError(f"unknown protocol: {entry.protocol}")
