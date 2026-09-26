"""Remove surviving negations of import-only `if TYPE_CHECKING:` guards from a finished cosmic-ray session.

Such a guard has no `else` and nothing but imports in its body: the imports serve annotations alone.
Negating its condition only runs them at run time. A negation the suite kills stays in the session as a
kill. One that survives says nothing about the tests, so it is deleted from the session: marking it
skipped would not do, because `cr-rate` counts a skipped item as killed.

Usage, after `cosmic-ray exec` and before `cr-rate`:
    uv run python scripts/drop_type_checking_survivors.py session.sqlite
"""

import argparse
import ast
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Final

NEGATION_OPERATOR: Final = "core/AddNot"
SESSION_TABLES: Final = ("work_results", "mutation_specs", "work_items")
SURVIVOR_QUERY: Final = """
    SELECT specs.job_id, specs.module_path, specs.start_pos_row, specs.start_pos_col,
           specs.end_pos_row, specs.end_pos_col
    FROM mutation_specs AS specs JOIN work_results AS results ON results.job_id = specs.job_id
    WHERE specs.operator_name = ? AND results.worker_outcome = 'NORMAL' AND results.test_outcome = 'SURVIVED'
"""

type SourceSpan = tuple[int, int, int | None, int | None]


def _is_type_checking(condition: ast.expr) -> bool:
    match condition:
        case ast.Name(id="TYPE_CHECKING") | ast.Attribute(value=ast.Name(id="typing"), attr="TYPE_CHECKING"):
            return True
        case _:
            return False


def _is_canonical_import(statement: ast.Import | ast.ImportFrom, alias: ast.alias) -> bool:
    if isinstance(statement, ast.ImportFrom):
        return (
            statement.level == 0
            and statement.module == "typing"
            and alias.name == "TYPE_CHECKING"
            and alias.asname is None
        )
    return alias.name == "typing" and alias.asname is None


def _bound_names(node: ast.AST) -> list[str]:
    match node:
        case ast.Attribute(attr="TYPE_CHECKING", ctx=ast.Store() | ast.Del()):
            return ["TYPE_CHECKING"]
        case (
            ast.Name(id=name, ctx=ast.Store() | ast.Del())
            | ast.arg(arg=name)
            | ast.FunctionDef(name=name)
            | ast.AsyncFunctionDef(name=name)
            | ast.ClassDef(name=name)
            | ast.ExceptHandler(name=str() as name)
            | ast.MatchAs(name=str() as name)
            | ast.MatchStar(name=str() as name)
            | ast.MatchMapping(rest=str() as name)
            | ast.TypeVar(name=name)
            | ast.ParamSpec(name=name)
            | ast.TypeVarTuple(name=name)
        ):
            return [name]
        case ast.Global(names=names) | ast.Nonlocal(names=names):
            return names
        case ast.Import(names=aliases) | ast.ImportFrom(names=aliases):
            return [
                alias.asname or alias.name.partition(".")[0]
                for alias in aliases
                if not _is_canonical_import(node, alias)
            ]
        case _:
            return []


def _rebinds_type_checking(tree: ast.Module) -> bool:
    """Whether anything but `from typing import TYPE_CHECKING` or `import typing` binds or alters either name."""
    names = {name for node in ast.walk(tree) for name in _bound_names(node)}
    return bool(names & {"TYPE_CHECKING", "typing", "*"})


def find_import_only_guards(source: str) -> set[SourceSpan]:
    """Return the source spans of the `TYPE_CHECKING` conditions whose negation only runs imports.

    Only guards directly at module level count: one that runs while the module imports cannot refer to an
    unbound name, or the import would fail before cosmic-ray could run a job. A module that binds or alters
    `TYPE_CHECKING` or `typing` any other way than the canonical import, or star-imports, yields nothing:
    its guard may not be the constant from `typing`. So does one that assigns or deletes any attribute
    named `TYPE_CHECKING`, on purpose, even one that could not reach `typing`. The check is static, so
    indirect changes such as `setattr(typing, "TYPE_CHECKING", True)` are not seen.
    """
    tree = ast.parse(source)
    if _rebinds_type_checking(tree):
        return set()
    spans = set()
    for node in tree.body:
        if (
            isinstance(node, ast.If)
            and _is_type_checking(node.test)
            and not node.orelse
            and all(isinstance(statement, ast.Import | ast.ImportFrom) for statement in node.body)
        ):
            condition = node.test
            spans.add((condition.lineno, condition.col_offset, condition.end_lineno, condition.end_col_offset))
    return spans


def find_surviving_guard_negations(connection: sqlite3.Connection) -> list[str]:
    """Return the job ids of the surviving mutants that negate an import-only `TYPE_CHECKING` guard."""
    guard_spans: dict[str, set[SourceSpan]] = {}
    job_ids = []
    for job_id, module_path, *mutation_span in connection.execute(SURVIVOR_QUERY, (NEGATION_OPERATOR,)).fetchall():
        if module_path not in guard_spans:
            guard_spans[module_path] = find_import_only_guards(Path(module_path).read_text(encoding="utf-8"))
        if tuple(mutation_span) in guard_spans[module_path]:
            job_ids.append(job_id)
    return job_ids


def drop_jobs(connection: sqlite3.Connection, job_ids: list[str]) -> None:
    """Delete the given jobs from every table of the session."""
    for table in SESSION_TABLES:
        connection.executemany(f"DELETE FROM {table} WHERE job_id = ?", [(job_id,) for job_id in job_ids])
    connection.commit()


def main() -> None:
    parser = argparse.ArgumentParser(description="Drop surviving `if TYPE_CHECKING:` negations from a session")
    parser.add_argument("session", type=Path, help="cosmic-ray session database, after `cosmic-ray exec`")
    args = parser.parse_args()
    with closing(sqlite3.connect(args.session)) as connection:
        job_ids = find_surviving_guard_negations(connection)
        drop_jobs(connection, job_ids)
    print(f"Dropped {len(job_ids)} surviving `if TYPE_CHECKING:` negation(s) from {args.session}")


if __name__ == "__main__":
    main()
