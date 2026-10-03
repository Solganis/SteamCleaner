from unittest.mock import patch

import pytest
from helpers import FakePlatformAdapter


@pytest.fixture(autouse=True)
def machine_with_a_trash():
    """Keep an engine built without a platform from asking the Recycle Bin of the machine that runs the tests."""
    with patch("steamcleaner.cleaner.engine.create_adapter", FakePlatformAdapter):
        yield
