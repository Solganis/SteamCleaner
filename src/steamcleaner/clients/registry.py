from __future__ import annotations

import importlib
import pkgutil
from collections.abc import Iterator
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from steamcleaner.clients.base import GameClient
    from steamcleaner.platform.base import PlatformAdapter
    from steamcleaner.scanner.exclusions import ExclusionRegistry

_SKIP_MODULES = frozenset({"base", "registry"})


class ClientRegistry:
    _client_classes: list[type[GameClient]] = []
    _discovered: bool = False

    @classmethod
    def register(cls, client_cls: type[GameClient]) -> type[GameClient]:
        cls._client_classes.append(client_cls)
        return client_cls

    @classmethod
    def discover(cls):
        if cls._discovered:
            return
        import steamcleaner.clients as clients_package

        for module_info in pkgutil.iter_modules(clients_package.__path__):
            if module_info.name not in _SKIP_MODULES:
                importlib.import_module(f"steamcleaner.clients.{module_info.name}")
        cls._discovered = True

    @classmethod
    def create_all(cls, platform: PlatformAdapter, exclusions: ExclusionRegistry) -> Iterator[GameClient]:
        cls.discover()
        for client_cls in cls._client_classes:
            yield client_cls(platform, exclusions)

    @classmethod
    def clear(cls):
        cls._client_classes.clear()
        cls._discovered = False
