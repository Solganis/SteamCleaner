from pathlib import Path

import pytest

from steamcleaner.clients.registry import ClientRegistry
from steamcleaner.scanner.exclusions import ExclusionRegistry
from tests.conftest import FakePlatformAdapter


@pytest.fixture(autouse=True)
def _restore_registry():
    """Ensure registry state is restored after each test."""
    saved_classes = list(ClientRegistry._client_classes)
    saved_discovered = ClientRegistry._discovered
    yield
    ClientRegistry._client_classes = saved_classes
    ClientRegistry._discovered = saved_discovered


class TestClientRegistry:
    def test_clear_removes_all_clients(self):
        ClientRegistry.discover()
        assert len(ClientRegistry._client_classes) > 0
        ClientRegistry.clear()
        assert len(ClientRegistry._client_classes) == 0
        assert ClientRegistry._discovered is False

    def test_discover_is_idempotent(self):
        ClientRegistry.clear()
        ClientRegistry.discover()
        count_after_first = len(ClientRegistry._client_classes)
        ClientRegistry.discover()
        assert len(ClientRegistry._client_classes) == count_after_first

    def test_create_all_yields_instances(self, tmp_path: Path):
        platform = FakePlatformAdapter(home_dir=tmp_path)
        exclusions = ExclusionRegistry()
        clients = list(ClientRegistry.create_all(platform, exclusions))
        assert len(clients) > 0
        for client in clients:
            assert hasattr(client, "name")
            assert hasattr(client, "is_installed")
