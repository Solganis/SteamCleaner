import importlib.util
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

import pytest
from assertpy2 import assert_that

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "drop_exempt_survivors.py"
MODULE_SOURCE = """import typing
from typing import TYPE_CHECKING, Annotated, Literal
from typing import Annotated as Noted, Literal as Exactly

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

type Alias = int | str
type Boxed[T: float | complex = bytes | None] = list[T]
MASK = READ | WRITE


def load(path: Path | None = None, flags: int = READ | WRITE) -> dict[str, int | None]:
    limit: bool | None = None
    return {} | {}


def label(text: str = "имя", count: int | None = None) -> bool: ...


def choose(mode: typing.Literal[READ | WRITE] | None, size: Annotated[bytes | None, LOW | HIGH]) -> None: ...


def weigh(grams: 4 | 8, name: "str" | None, ceiling: range | bytearray | None = None) -> None: ...


def merge(parts: None | list[memoryview | None]) -> None: ...


def pick(kind: Exactly[OPEN | SHUT], speed: Noted[int, FAST | SLOW]) -> None: ...


def convert[Item: (set | None, str)](handler: Callable[[Item | None], tuple | None]) -> None: ...
"""
SOURCE_LINES = MODULE_SOURCE.splitlines()
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
TYPING_GUARD = GUARD.replace("TYPE_CHECKING", "typing.TYPE_CHECKING")
CANONICAL_NAME = "from typing import TYPE_CHECKING\n"
CANONICAL_MODULE = "import typing\n"
REBINDING_SOURCES = [
    pytest.param("from typing import TYPE_CHECKING\nTYPE_CHECKING = True" + GUARD, id="assignment"),
    pytest.param(CANONICAL_NAME + "from settings import DEBUG as TYPE_CHECKING" + GUARD, id="aliased-import"),
    pytest.param(CANONICAL_MODULE + "import settings as typing" + TYPING_GUARD, id="aliased-typing"),
    pytest.param(CANONICAL_NAME + "from settings import *" + GUARD, id="star-import"),
    pytest.param(CANONICAL_NAME + "from .typing import TYPE_CHECKING" + GUARD, id="relative-import"),
    pytest.param("import typing\ntyping.TYPE_CHECKING = True" + TYPING_GUARD, id="attribute-assignment"),
    pytest.param("from typing import TYPE_CHECKING\ndel TYPE_CHECKING" + GUARD, id="deletion"),
    pytest.param("import typing\ndel typing.TYPE_CHECKING" + TYPING_GUARD, id="attribute-deletion"),
    pytest.param(
        CANONICAL_NAME + "def enable():\n    global TYPE_CHECKING\n    TYPE_CHECKING = True" + GUARD,
        id="assignment-through-global",
    ),
    pytest.param(CANONICAL_NAME + "def enable():\n    global TYPE_CHECKING" + GUARD, id="global-declaration-alone"),
    pytest.param("from typing import TYPE_CHECKING\ndef check(TYPE_CHECKING):\n    pass" + GUARD, id="parameter"),
]
UNBACKED_SOURCES = [
    pytest.param(GUARD, id="no-import-at-all"),
    pytest.param("import typing" + GUARD, id="bare-name-with-only-the-module-imported"),
    pytest.param("from typing import TYPE_CHECKING" + TYPING_GUARD, id="attribute-with-only-the-name-imported"),
    pytest.param("def later():\n    from typing import TYPE_CHECKING\n" + GUARD, id="import-inside-a-function"),
]
SESSION_SCHEMA = """
CREATE TABLE work_items (job_id TEXT PRIMARY KEY);
CREATE TABLE mutation_specs (
    module_path TEXT, operator_name TEXT, occurrence INTEGER, start_pos_row INTEGER, start_pos_col INTEGER,
    end_pos_row INTEGER, end_pos_col INTEGER, job_id TEXT PRIMARY KEY
);
CREATE TABLE work_results (worker_outcome TEXT, test_outcome TEXT, job_id TEXT PRIMARY KEY);
"""
NEGATION = "core/AddNot"
UNION_TO_ADD = "core/ReplaceBinaryOperator_BitOr_Add"

type Span = tuple[int, int, int, int]


def _row_of(marker: str) -> int:
    rows = [row for row, line in enumerate(SOURCE_LINES, start=1) if marker in line]
    assert len(rows) == 1, marker
    return rows[0]


def _text_span(marker: str, text: str) -> Span:
    row = _row_of(marker)
    column = SOURCE_LINES[row - 1].index(text)
    return row, column, row, column + len(text)


def _pipe_span(union_text: str) -> Span:
    """Return the span of the `|` in a union that is written once in the source, as cosmic-ray reports it."""
    row, column, _, _ = _text_span(union_text, union_text)
    pipe_column = column + union_text.index(" | ") + 1
    return row, pipe_column, row, pipe_column + 1


def _between_span(union_text: str) -> Span:
    """Return the span between the operands of a union written once in the source: the `|` with its spaces."""
    row, pipe_column, _, _ = _pipe_span(union_text)
    return row, pipe_column - 1, row, pipe_column + 2


GUARD_SPAN = _text_span("# annotations only", "TYPE_CHECKING")
TYPING_GUARD_SPAN = _text_span("if typing.TYPE_CHECKING:", "typing.TYPE_CHECKING")
TYPE_UNIONS = [
    "int | str",
    "float | complex",
    "bytes | None] = list",
    "Path | None",
    "int | None]",
    "bool | None",
    "int | None = None) -> bool",
    "] | None, size",
    "bytes | None, LOW",
    "range | bytearray",
    "bytearray | None",
    "None | list",
    "memoryview | None",
    "set | None",
    "Item | None",
    "tuple | None",
]
OTHER_UNIONS = [
    "MASK = READ | WRITE",
    "int = READ | WRITE",
    "{} | {}",
    "READ | WRITE]",
    "LOW | HIGH",
    "OPEN | SHUT",
    "FAST | SLOW",
    "4 | 8",
    '"str" | None',
]
GUARD_WITH_ELSE_ROW = SOURCE_LINES.index("    from pathlib import PurePath")
GUARD_WITH_ELSE_SPAN = (GUARD_WITH_ELSE_ROW, 3, GUARD_WITH_ELSE_ROW, 16)
GUARD_WITH_ASSIGNMENT_ROW = SOURCE_LINES.index("    LIMIT = 1")
GUARD_WITH_ASSIGNMENT_SPAN = (GUARD_WITH_ASSIGNMENT_ROW, 3, GUARD_WITH_ASSIGNMENT_ROW, 16)
ANNOTATION_UNION = _pipe_span("Path | None")
EXEMPT = [
    ("surviving-guard-negation", NEGATION, GUARD_SPAN, "NORMAL", "SURVIVED"),
    ("surviving-typing-guard-negation", NEGATION, TYPING_GUARD_SPAN, "NORMAL", "SURVIVED"),
    *[(f"type-union {union}", UNION_TO_ADD, _pipe_span(union), "NORMAL", "SURVIVED") for union in TYPE_UNIONS],
]
NOT_EXEMPT = [
    ("killed-guard-negation", NEGATION, GUARD_SPAN, "NORMAL", "KILLED"),
    ("abnormal-guard-negation", NEGATION, GUARD_SPAN, "ABNORMAL", "SURVIVED"),
    ("guard-with-assignment", NEGATION, GUARD_WITH_ASSIGNMENT_SPAN, "NORMAL", "SURVIVED"),
    ("guard-with-else", NEGATION, GUARD_WITH_ELSE_SPAN, "NORMAL", "SURVIVED"),
    ("plain-if", NEGATION, _text_span("if enabled:", "enabled"), "NORMAL", "SURVIVED"),
    ("other-operator-on-guard", "core/ReplaceTrueWithFalse", GUARD_SPAN, "NORMAL", "SURVIVED"),
    ("other-span-on-guard-row", NEGATION, (GUARD_SPAN[0], 0, GUARD_SPAN[0], 16), "NORMAL", "SURVIVED"),
    ("killed-type-union", UNION_TO_ADD, ANNOTATION_UNION, "NORMAL", "KILLED"),
    ("abnormal-type-union", UNION_TO_ADD, ANNOTATION_UNION, "ABNORMAL", "SURVIVED"),
    ("other-operator-in-annotation", "core/ReplaceBinaryOperator_Div_BitOr", ANNOTATION_UNION, "NORMAL", "SURVIVED"),
    *[(f"other-union {union}", UNION_TO_ADD, _pipe_span(union), "NORMAL", "SURVIVED") for union in OTHER_UNIONS],
]
MUTATIONS = [*EXEMPT, *NOT_EXEMPT]
DROPPED = [job_id for job_id, *_ in EXEMPT]


@pytest.fixture(scope="module")
def drop_script():
    spec = importlib.util.spec_from_file_location("drop_exempt_survivors", SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    return script


@pytest.fixture
def session_path(tmp_path: Path) -> Path:
    module_path = tmp_path / "module.py"
    module_path.write_text(MODULE_SOURCE, encoding="utf-8")
    path = tmp_path / "session.sqlite"
    with closing(sqlite3.connect(path)) as connection:
        connection.executescript(SESSION_SCHEMA)
        for job_id, operator_name, span, worker_outcome, test_outcome in MUTATIONS:
            connection.execute("INSERT INTO work_items VALUES (?)", (job_id,))
            connection.execute(
                "INSERT INTO mutation_specs VALUES (?, ?, 0, ?, ?, ?, ?, ?)",
                (str(module_path), operator_name, *span, job_id),
            )
            connection.execute("INSERT INTO work_results VALUES (?, ?, ?)", (worker_outcome, test_outcome, job_id))
        connection.commit()
    return path


@pytest.fixture
def session(session_path: Path) -> sqlite3.Connection:
    return sqlite3.connect(session_path)


def _job_ids(connection: sqlite3.Connection, table: str) -> set[str]:
    return {job_id for (job_id,) in connection.execute(f"SELECT job_id FROM {table}")}


def _as_tuples(spans) -> set[Span]:
    return {(*span.start, *span.end) for span in spans}


def test_finds_the_conditions_of_guards_that_hold_nothing_but_imports(drop_script):
    guards = drop_script.find_import_only_guards(MODULE_SOURCE)
    assert_that(_as_tuples(guards)).is_equal_to({GUARD_SPAN, TYPING_GUARD_SPAN})


def test_ignores_guards_below_module_level(drop_script):
    assert_that(drop_script.find_import_only_guards(NESTED_GUARDS_SOURCE)).is_empty()


@pytest.mark.parametrize("source", REBINDING_SOURCES)
def test_trusts_no_guard_in_a_module_that_rebinds_the_name(drop_script, source: str):
    assert_that(drop_script.find_import_only_guards(source)).is_empty()


@pytest.mark.parametrize("source", UNBACKED_SOURCES)
def test_trusts_no_guard_whose_name_no_module_level_import_from_typing_binds(drop_script, source: str):
    assert_that(drop_script.find_import_only_guards(source)).is_empty()


def test_finds_the_unions_of_types_in_annotations_and_nothing_else(drop_script):
    unions = _as_tuples(drop_script.find_annotation_unions(MODULE_SOURCE))
    assert_that(unions).is_equal_to({_between_span(union) for union in TYPE_UNIONS})


def test_name_imported_for_both_literal_and_annotated_is_never_entered(drop_script):
    source = (
        "from typing import Literal as Holder\n\n\n"
        "def first(flags: Holder[READ | WRITE]) -> None: ...\n\n\n"
        "def second() -> None:\n"
        "    from typing import Annotated as Holder\n"
    )
    assert_that(drop_script.find_annotation_unions(source)).is_empty()


def test_finds_only_the_normal_survivors_that_are_exempt(drop_script, session: sqlite3.Connection):
    with closing(session):
        assert_that(drop_script.find_exempt_survivors(session)).is_equal_to(DROPPED)


def test_drops_the_jobs_from_every_table(drop_script, session: sqlite3.Connection):
    with closing(session):
        drop_script.drop_jobs(session, DROPPED)
        remaining = {job_id for job_id, *_ in MUTATIONS} - set(DROPPED)
        for table in ("work_items", "mutation_specs", "work_results"):
            assert_that(_job_ids(session, table)).is_equal_to(remaining)


def test_finished_session_has_no_unfinished_jobs(drop_script, session: sqlite3.Connection):
    with closing(session):
        assert_that(drop_script.find_unfinished_jobs(session)).is_empty()


@pytest.mark.parametrize("emptied_table", ["work_results", "mutation_specs", "work_items"])
def test_job_missing_from_any_table_is_unfinished(drop_script, session: sqlite3.Connection, emptied_table: str):
    with closing(session):
        session.execute(f"DELETE FROM {emptied_table} WHERE job_id IN ('plain-if', 'killed-type-union')")
        assert_that(drop_script.find_unfinished_jobs(session)).is_equal_to(["killed-type-union", "plain-if"])


def test_main_drops_the_exempt_survivors_and_says_how_many(drop_script, session_path: Path, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["drop_exempt_survivors.py", str(session_path)])

    drop_script.main()

    assert_that(capsys.readouterr().out).is_equal_to(f"Dropped {len(DROPPED)} exempt survivor(s) from {session_path}\n")
    with closing(sqlite3.connect(session_path)) as connection:
        assert_that(_job_ids(connection, "work_results")).is_equal_to({job_id for job_id, *_ in NOT_EXEMPT})


def test_main_refuses_a_session_with_a_mutant_that_has_no_result(drop_script, session_path: Path, monkeypatch):
    with closing(sqlite3.connect(session_path)) as connection:
        connection.execute("DELETE FROM work_results WHERE job_id = 'plain-if'")
        connection.commit()
    monkeypatch.setattr(sys, "argv", ["drop_exempt_survivors.py", str(session_path)])

    assert_that(drop_script.main).raises(SystemExit).when_called_with().is_equal_to(
        f"{session_path} is unfinished: 1 mutant(s) lack a spec or a result"
    )
    with closing(sqlite3.connect(session_path)) as connection:
        assert_that(_job_ids(connection, "work_items")).is_equal_to({job_id for job_id, *_ in MUTATIONS})
