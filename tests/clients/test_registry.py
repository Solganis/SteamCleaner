import importlib.util
import logging
import sys
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest
from assertpy2 import assert_that
from helpers import FakePlatformAdapter

import steamcleaner.clients as clients_package
from steamcleaner.clients import ea_app, epic, gog, steam, ubisoft
from steamcleaner.clients.base import GameClient
from steamcleaner.clients.registry import ClientRegistry
from steamcleaner.scanner.exclusions import ExclusionRegistry

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path
    from types import ModuleType

    from steamcleaner.models.junk import JunkEntry

CLIENT_MODULES = (ea_app, epic, gog, steam, ubisoft)


def _load_fresh_registry(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    """Load a second copy of the registry module and make the client modules import against it."""
    spec = importlib.util.find_spec("steamcleaner.clients.registry")
    assert spec is not None
    assert spec.loader is not None
    fresh_registry = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "steamcleaner.clients.registry", fresh_registry)
    spec.loader.exec_module(fresh_registry)
    for client_module in CLIENT_MODULES:
        monkeypatch.setattr(clients_package, client_module.__name__.rsplit(".", 1)[1], client_module)
        monkeypatch.delitem(sys.modules, client_module.__name__)
    return fresh_registry


# test deliberately accesses a protected member
# noinspection PyProtectedMember
@pytest.fixture(autouse=True)
def _restore_registry():
    """Ensure registry state is restored after each test."""
    saved_classes = list(ClientRegistry._client_classes)
    saved_discovered = ClientRegistry._discovered
    yield
    ClientRegistry._client_classes = saved_classes
    ClientRegistry._discovered = saved_discovered


# test deliberately accesses a protected member
# noinspection PyProtectedMember
class TestClientRegistry:
    def test_clear_removes_all_clients(self):
        ClientRegistry.discover()
        assert_that(len(ClientRegistry._client_classes)).is_greater_than(0)
        ClientRegistry.clear()
        assert_that(ClientRegistry._client_classes).is_length(0)
        assert_that(ClientRegistry._discovered).is_false()

    def test_discover_is_idempotent(self):
        ClientRegistry.clear()
        ClientRegistry.discover()
        count_after_first = len(ClientRegistry._client_classes)
        ClientRegistry.discover()
        assert_that(len(ClientRegistry._client_classes)).is_equal_to(count_after_first)

    def test_discover_swallows_import_failure(self):
        ClientRegistry.clear()
        with patch("steamcleaner.clients.registry.importlib.import_module", side_effect=ImportError("boom")):
            ClientRegistry.discover()
        assert_that(ClientRegistry._discovered).is_true()
        assert_that(ClientRegistry._client_classes).is_length(0)

    def test_import_failure_is_logged_with_its_traceback(self, caplog):
        ClientRegistry.clear()
        with (
            caplog.at_level(logging.ERROR, logger="steamcleaner.clients.registry"),
            patch("steamcleaner.clients.registry.importlib.import_module", side_effect=ImportError("boom")),
        ):
            ClientRegistry.discover()
        exception_types = [record.exc_info[0] if record.exc_info else None for record in caplog.records]
        assert_that(exception_types).is_not_empty().contains_only(ImportError)

    def test_first_discovery_registers_every_client(self, monkeypatch):
        fresh_registry = _load_fresh_registry(monkeypatch)
        fresh_registry.ClientRegistry.discover()
        registered_modules = sorted(client.__module__ for client in fresh_registry.ClientRegistry._client_classes)
        assert_that(registered_modules).is_equal_to(sorted(client_module.__name__ for client_module in CLIENT_MODULES))

    def test_create_all_yields_instances(self, tmp_path: Path):
        platform = FakePlatformAdapter(home_dir=tmp_path)
        exclusions = ExclusionRegistry()
        clients = list(ClientRegistry.create_all(platform, exclusions))
        assert_that(clients).is_not_empty()
        for client in clients:
            assert_that(hasattr(client, "name")).is_true()
            assert_that(hasattr(client, "is_installed")).is_true()


class TestGameClientDefaults:
    def test_game_install_paths_default(self, tmp_path: Path):
        class StubClient(GameClient):
            @property
            def name(self) -> str:
                return "Stub"

            def is_installed(self) -> bool:
                return False

            def scan_junk(self) -> Iterator[JunkEntry]:
                yield from ()

        client = StubClient(FakePlatformAdapter(home_dir=tmp_path), ExclusionRegistry())
        assert_that(client.game_install_paths()).is_equal_to([])
