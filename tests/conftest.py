from pathlib import Path

import pytest
from helpers import FakePlatformAdapter

from steamcleaner.scanner.exclusions import ExclusionRegistry


@pytest.fixture
def exclusion_registry() -> ExclusionRegistry:
    return ExclusionRegistry()


@pytest.fixture
def fake_platform(tmp_path: Path) -> FakePlatformAdapter:
    return FakePlatformAdapter(install_path=None)
