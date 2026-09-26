import importlib.util
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest
from assertpy2 import assert_that

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "drop_type_checking_survivors.py"
MODULE_SOURCE = """import typing
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # annotations only
    from pathlib import Path

if typing.TYPE_CHECKING:
    import json

if TYPE_CHECKING:
    LIMIT = 1

if TYPE_CHECKING:
    from pathlib import PurePath
else:
    PurePath = None

if enabled:
    run()
"""
GUARD_SPAN = (4, 3, 4, 16)
TYPING_GUARD_SPAN = (7, 3, 7, 23)
SESSION_SCHEMA = """
CREATE TABLE work_items (job_id TEXT PRIMARY KEY);
CREATE TABLE mutation_specs (
    module_path TEXT, operator_name TEXT, occurrence INTEGER, start_pos_row INTEGER, start_pos_col INTEGER,
    end_pos_row INTEGER, end_pos_col INTEGER, job_id TEXT PRIMARY KEY
);
CREATE TABLE work_results (worker_outcome TEXT, test_outcome TEXT, job_id TEXT PRIMARY KEY);
"""
MUTATIONS = [
    ("surviving-guard-negation", "core/AddNot", GUARD_SPAN, "NORMAL", "SURVIVED"),
    ("surviving-typing-guard-negation", "core/AddNot", TYPING_GUARD_SPAN, "NORMAL", "SURVIVED"),
    ("killed-guard-negation", "core/AddNot", GUARD_SPAN, "NORMAL", "KILLED"),
    ("abnormal-guard-negation", "core/AddNot", GUARD_SPAN, "ABNORMAL", "SURVIVED"),
    ("guard-with-assignment", "core/AddNot", (10, 3, 10, 16), "NORMAL", "SURVIVED"),
    ("guard-with-else", "core/AddNot", (13, 3, 13, 16), "NORMAL", "SURVIVED"),
    ("plain-if", "core/AddNot", (18, 3, 18, 10), "NORMAL", "SURVIVED"),
    ("other-operator-on-guard", "core/ReplaceTrueWithFalse", GUARD_SPAN, "NORMAL", "SURVIVED"),
    ("other-span-on-guard-row", "core/AddNot", (4, 0, 4, 16), "NORMAL", "SURVIVED"),
]
DROPPED = ["surviving-guard-negation", "surviving-typing-guard-negation"]
NESTED_GUARDS_SOURCE = """from typing import TYPE_CHECKING


def load():
    if TYPE_CHECKING:
        import json


if False:
    if TYPE_CHECKING:
        import json
"""
GUARD = """
if TYPE_CHECKING:
    import json
"""
REBINDING_SOURCES = [
    pytest.param("from typing import TYPE_CHECKING\nTYPE_CHECKING = True" + GUARD, id="assignment"),
    pytest.param("from settings import DEBUG as TYPE_CHECKING" + GUARD, id="aliased-import"),
    pytest.param(
        "import settings as typing" + GUARD.replace("TYPE_CHECKING", "typing.TYPE_CHECKING"), id="aliased-typing"
    ),
    pytest.param("from settings import *" + GUARD, id="star-import"),
    pytest.param("from .typing import TYPE_CHECKING" + GUARD, id="relative-import"),
    pytest.param(
        "import typing\ntyping.TYPE_CHECKING = True" + GUARD.replace("TYPE_CHECKING", "typing.TYPE_CHECKING"),
        id="attribute-assignment",
    ),
    pytest.param("from typing import TYPE_CHECKING\ndel TYPE_CHECKING" + GUARD, id="deletion"),
    pytest.param(
        "import typing\ndel typing.TYPE_CHECKING" + GUARD.replace("TYPE_CHECKING", "typing.TYPE_CHECKING"),
        id="attribute-deletion",
    ),
    pytest.param(
        "from typing import TYPE_CHECKING\ndef enable():\n    global TYPE_CHECKING" + GUARD,
        id="global",
    ),
    pytest.param("from typing import TYPE_CHECKING\ndef check(TYPE_CHECKING):\n    pass" + GUARD, id="parameter"),
]


@pytest.fixture(scope="module")
def drop_script():
    spec = importlib.util.spec_from_file_location("drop_type_checking_survivors", SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    return script


@pytest.fixture
def session(tmp_path: Path) -> sqlite3.Connection:
    module_path = tmp_path / "module.py"
    module_path.write_text(MODULE_SOURCE, encoding="utf-8")
    connection = sqlite3.connect(tmp_path / "session.sqlite")
    connection.executescript(SESSION_SCHEMA)
    for job_id, operator_name, span, worker_outcome, test_outcome in MUTATIONS:
        connection.execute("INSERT INTO work_items VALUES (?)", (job_id,))
        connection.execute(
            "INSERT INTO mutation_specs VALUES (?, ?, 0, ?, ?, ?, ?, ?)",
            (str(module_path), operator_name, *span, job_id),
        )
        connection.execute("INSERT INTO work_results VALUES (?, ?, ?)", (worker_outcome, test_outcome, job_id))
    connection.commit()
    return connection


def _job_ids(connection: sqlite3.Connection, table: str) -> set[str]:
    return {job_id for (job_id,) in connection.execute(f"SELECT job_id FROM {table}")}


def test_finds_the_conditions_of_guards_that_hold_nothing_but_imports(drop_script):
    assert_that(drop_script.find_import_only_guards(MODULE_SOURCE)).is_equal_to({GUARD_SPAN, TYPING_GUARD_SPAN})


def test_ignores_guards_below_module_level(drop_script):
    assert_that(drop_script.find_import_only_guards(NESTED_GUARDS_SOURCE)).is_empty()


@pytest.mark.parametrize("source", REBINDING_SOURCES)
def test_trusts_no_guard_in_a_module_that_rebinds_the_name(drop_script, source: str):
    assert_that(drop_script.find_import_only_guards(source)).is_empty()


def test_finds_only_the_surviving_negations_of_those_conditions(drop_script, session: sqlite3.Connection):
    with closing(session):
        assert_that(drop_script.find_surviving_guard_negations(session)).is_equal_to(DROPPED)


def test_drops_the_jobs_from_every_table(drop_script, session: sqlite3.Connection):
    with closing(session):
        drop_script.drop_jobs(session, DROPPED)
        remaining = {job_id for job_id, *_ in MUTATIONS} - set(DROPPED)
        for table in ("work_items", "mutation_specs", "work_results"):
            assert_that(_job_ids(session, table)).is_equal_to(remaining)
