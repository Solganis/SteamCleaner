import importlib
import logging
import pkgutil
from collections.abc import Iterator
from typing import ClassVar

from steamcleaner.clients.base import GameClient
from steamcleaner.platform.base import PlatformAdapter
from steamcleaner.scanner.exclusions import ExclusionRegistry

_logger = logging.getLogger(__name__)

_SKIP_MODULES = frozenset({"base", "registry"})


class ClientRegistry:
    _client_classes: ClassVar[list[type[GameClient]]] = []
    _discovered: ClassVar[bool] = False

    @classmethod
    def register[T: GameClient](cls, client_cls: type[T]) -> type[T]:
        cls._client_classes.append(client_cls)
        return client_cls

    @classmethod
    def discover(cls) -> None:
        if cls._discovered:
            return
        import steamcleaner.clients as clients_package

        for module_info in pkgutil.iter_modules(clients_package.__path__):
            if module_info.name not in _SKIP_MODULES:
                try:
                    importlib.import_module(f"steamcleaner.clients.{module_info.name}")
                except (ImportError, SyntaxError, AttributeError):  # fmt: skip  # parens: flet bundles 3.12
                    _logger.error("Failed to import client: %s", module_info.name, exc_info=True)
        _logger.debug("Discovery complete: %d clients", len(cls._client_classes))
        cls._discovered = True

    @classmethod
    def create_all(cls, platform: PlatformAdapter, exclusions: ExclusionRegistry) -> Iterator[GameClient]:
        cls.discover()
        for client_cls in cls._client_classes:
            yield client_cls(platform, exclusions)

    @classmethod
    def clear(cls) -> None:
        cls._client_classes.clear()
        cls._discovered = False
