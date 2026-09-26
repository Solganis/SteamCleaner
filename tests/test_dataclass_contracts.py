import dataclasses
import re
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from assertpy2 import assert_that

from steamcleaner.cleaner.engine import CleanStats
from steamcleaner.models.junk import JunkCategory, JunkEntry
from steamcleaner.models.scan_result import ScanResult
from steamcleaner.scanner.exclusions import Exclusion, ExclusionRegistry
from steamcleaner.scanner.patterns import JunkPattern

if TYPE_CHECKING:
    from collections.abc import Callable

    from _typeshed import DataclassInstance

RECORDS = [
    pytest.param(
        lambda: JunkEntry(
            path=Path("C:/Games/Redist"),
            category=JunkCategory.REDISTRIBUTABLE,
            size_bytes=1024,
            client_name="Steam",
        ),
        id="JunkEntry",
    ),
    pytest.param(
        lambda: JunkPattern(
            dir_regex=re.compile("redist"),
            file_extensions=frozenset({".exe"}),
            category=JunkCategory.REDISTRIBUTABLE,
            description="Redistributable installers",
        ),
        id="JunkPattern",
    ),
    pytest.param(lambda: Exclusion(pattern="Steamworks Shared", reason="Shared pool"), id="Exclusion"),
    pytest.param(lambda: CleanStats(deleted=1, skipped=2, errors=["denied"], bytes_freed=3), id="CleanStats"),
]

CONTAINERS = [
    pytest.param(ScanResult, id="ScanResult"),
    pytest.param(ExclusionRegistry, id="ExclusionRegistry"),
]


@pytest.mark.parametrize("build_record", RECORDS)
def test_record_rejects_field_assignment(build_record: Callable[[], DataclassInstance]):
    record = build_record()
    first_field = dataclasses.fields(record)[0].name
    assert_that(setattr).raises(dataclasses.FrozenInstanceError).when_called_with(record, first_field, None)


@pytest.mark.parametrize("build_record", RECORDS)
def test_record_rejects_positional_arguments(build_record: Callable[[], DataclassInstance]):
    record = build_record()
    construct: Callable[..., object] = type(record)
    field_values = [getattr(record, field.name) for field in dataclasses.fields(record)]
    assert_that(construct).raises(TypeError).when_called_with(*field_values).contains("positional argument")


@pytest.mark.parametrize("build_record", RECORDS)
def test_record_keeps_no_instance_dict(build_record: Callable[[], DataclassInstance]):
    assert_that(hasattr(build_record(), "__dict__")).is_false()


@pytest.mark.parametrize("container_type", CONTAINERS)
def test_container_keeps_no_instance_dict(container_type: Callable[[], object]):
    assert_that(hasattr(container_type(), "__dict__")).is_false()
