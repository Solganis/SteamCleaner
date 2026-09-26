from typing import TYPE_CHECKING

import pytest
from helpers import FakePlatformAdapter

from steamcleaner.scanner.exclusions import ExclusionRegistry

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def exclusion_registry() -> ExclusionRegistry:
    return ExclusionRegistry()


@pytest.fixture
def fake_platform(tmp_path: Path) -> FakePlatformAdapter:
    return FakePlatformAdapter(install_path=None)
