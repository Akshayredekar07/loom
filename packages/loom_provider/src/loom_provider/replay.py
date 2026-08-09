from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass

from loom_provider.events import StreamEvent
from loom_provider.provider import ProviderMessage, ProviderToolSchema


@dataclass
class FakeProvider:
    script: Sequence[StreamEvent]

    def stream(
        self,
        messages: tuple[ProviderMessage, ...],
        *,
        system: str | None = None,
        tools: tuple[ProviderToolSchema, ...] = (),
    ) -> Iterator[StreamEvent]:
        yield from self.script

    def close(self) -> None:
        return None

    def __enter__(self) -> FakeProvider:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()
