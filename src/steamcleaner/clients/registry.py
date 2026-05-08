from __future__ import annotations

from collections.abc import Iterator
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from steamcleaner.clients.base import GameClient
    from steamcleaner.platform.base import PlatformAdapter
    from steamcleaner.scanner.exclusions import ExclusionRegistry


class ClientRegistry:
    _client_classes: list[type[GameClient]] = []

    @classmethod
    def register(cls, client_cls: type[GameClient]) -> type[GameClient]:
        cls._client_classes.append(client_cls)
        return client_cls

    @classmethod
    def create_all(cls, platform: PlatformAdapter, exclusions: ExclusionRegistry) -> Iterator[GameClient]:
        for client_cls in cls._client_classes:
            yield client_cls(platform, exclusions)

    @classmethod
    def clear(cls):
        cls._client_classes.clear()
