from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch

import pytest
from assertpy2 import assert_that
from helpers import FakePlatformAdapter

from steamcleaner.clients.base import GameClient
from steamcleaner.clients.registry import ClientRegistry
from steamcleaner.models.junk import JunkEntry
from steamcleaner.scanner.exclusions import ExclusionRegistry


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
