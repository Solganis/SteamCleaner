"""Remove from a finished cosmic-ray session the survivors this project exempts from the survival rate.

Two kinds are exempt, each only when the mutant ran and survived, so a mutant the suite kills stays a kill:

- The negation of an import-only `if TYPE_CHECKING:` guard. Such a guard has no `else` and nothing but
  imports in its body, so negating it only makes the module run imports it otherwise skips.
- A replaced `|` inside an annotation whose operands are written as types: a name, an attribute, a
  subscript, `None`, or such a union. An annotation is evaluated lazily (PEP 649), so the mutated union runs
  only when something reads it. That of a local variable is never evaluated.

These are exemptions by decision, not proofs that no test could kill the mutant: a test that asserted an
effect of the guarded import, or that evaluated the annotation, would. The union rule is syntactic. A name
is taken for a type without looking at what it is bound to.

The work items are deleted rather than marked skipped, because `cr-rate` counts a skipped item as killed.
A session in which some mutant has no result is refused: `cr-rate` would rate the finished part alone.

Usage, after `cosmic-ray exec` and before `cr-rate`:
    uv run python scripts/drop_exempt_survivors.py session.sqlite
"""

import argparse
import ast
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Iterator

NEGATION_OPERATOR: Final = "core/AddNot"
UNION_OPERATOR_PREFIX: Final = "core/ReplaceBinaryOperator_BitOr_"
SESSION_TABLES: Final = ("work_results", "mutation_specs", "work_items")
VALUE_HOLDERS: Final = frozenset({"Literal", "Annotated"})
SURVIVOR_QUERY: Final = """
    SELECT specs.job_id, specs.module_path, specs.operator_name, specs.start_pos_row, specs.start_pos_col,
           specs.end_pos_row, specs.end_pos_col
    FROM mutation_specs AS specs JOIN work_results AS results ON results.job_id = specs.job_id
    WHERE results.worker_outcome = 'NORMAL' AND results.test_outcome = 'SURVIVED'
"""

type Position = tuple[int, int]


@dataclass(frozen=True, slots=True, kw_only=True)
class SourceSpan:
    """Where a piece of source starts and ends: 1-based rows, 0-based character columns, as cosmic-ray stores them."""

    start: Position
    end: Position

    def contains(self, other: SourceSpan) -> bool:
        return self.start <= other.start and other.end <= self.end


def _character_position(row: int, byte_column: int, lines: list[str]) -> Position:
    """Convert the UTF-8 byte column `ast` reports to a character column."""
    return row, len(lines[row - 1].encode()[:byte_column].decode())


def _span_of(node: ast.expr, lines: list[str]) -> SourceSpan:
    assert node.end_lineno is not None
    assert node.end_col_offset is not None
    return SourceSpan(
        start=_character_position(node.lineno, node.col_offset, lines),
        end=_character_position(node.end_lineno, node.end_col_offset, lines),
    )


def _span_between(left: ast.expr, right: ast.expr, lines: list[str]) -> SourceSpan:
    """Return the span from the end of one expression to the start of the next: where their operator is."""
    assert left.end_lineno is not None
    assert left.end_col_offset is not None
    return SourceSpan(
        start=_character_position(left.end_lineno, left.end_col_offset, lines),
        end=_character_position(right.lineno, right.col_offset, lines),
    )


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


def _canonically_bound(tree: ast.Module) -> set[type[ast.expr]]:
    """Return the guard spellings a module-level canonical import backs: a bare name, a `typing.` attribute."""
    spellings: set[type[ast.expr]] = set()
    for statement in tree.body:
        if isinstance(statement, ast.Import | ast.ImportFrom):
            for alias in statement.names:
                if _is_canonical_import(statement, alias):
                    spellings.add(ast.Name if isinstance(statement, ast.ImportFrom) else ast.Attribute)
    return spellings


@cache
def find_import_only_guards(source: str) -> set[SourceSpan]:
    """Return the spans of the `TYPE_CHECKING` conditions whose negation only runs imports.

    Only guards directly at module level count: one that runs while the module imports cannot refer to an
    unbound name, or the import would fail before cosmic-ray could run a job. The guard's name has to come
    from a canonical import at module level, `from typing import TYPE_CHECKING` for a bare name and
    `import typing` for `typing.TYPE_CHECKING`. A module that binds or alters `TYPE_CHECKING` or `typing`
    any other way, or star-imports, yields nothing: its guard may not be the constant from `typing`. So does
    one that assigns or deletes any attribute named `TYPE_CHECKING`, on purpose, even one that could not
    reach `typing`. The check is static, so indirect changes such as
    `setattr(typing, "TYPE_CHECKING", True)` are not seen.
    """
    tree = ast.parse(source)
    if _rebinds_type_checking(tree):
        return set()
    backed_spellings = _canonically_bound(tree)
    lines = source.splitlines()
    spans = set()
    for node in tree.body:
        if (
            isinstance(node, ast.If)
            and _is_type_checking(node.test)
            and type(node.test) in backed_spellings
            and not node.orelse
            and all(isinstance(statement, ast.Import | ast.ImportFrom) for statement in node.body)
        ):
            spans.add(_span_of(node.test, lines))
    return spans


def _annotations_of(node: ast.AST) -> list[ast.expr | None]:
    """Return the type expressions a node carries in annotation position."""
    match node:
        case ast.arg(annotation=annotation) | ast.AnnAssign(annotation=annotation):
            return [annotation]
        case ast.FunctionDef(returns=returns) | ast.AsyncFunctionDef(returns=returns):
            return [returns]
        case ast.TypeAlias(value=value):
            return [value]
        case ast.TypeVar(bound=bound, default_value=default_value):
            return [bound, default_value]
        case _:
            return []


def _is_type_expression(node: ast.expr) -> bool:
    """Whether the expression is written the way a type is. What its names are bound to is not looked at."""
    match node:
        case ast.Name() | ast.Attribute() | ast.Subscript() | ast.Constant(value=None):
            return True
        case ast.BinOp(op=ast.BitOr(), left=left, right=right):
            return _is_type_expression(left) and _is_type_expression(right)
        case _:
            return False


def _find_value_holders(tree: ast.Module) -> dict[str, str]:
    """Map every name `Literal` or `Annotated` is imported under to the one it stands for.

    Scopes are not told apart. A name imported for both anywhere in the module counts as `Literal`, whose
    subscript is never entered.
    """
    holders = {name: name for name in VALUE_HOLDERS}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name in VALUE_HOLDERS:
                    local_name = alias.asname or alias.name
                    unambiguous = holders.get(local_name, alias.name) == alias.name
                    holders[local_name] = alias.name if unambiguous else "Literal"
    return holders


def _subscripted_holder(node: ast.Subscript, holders: dict[str, str]) -> str | None:
    match node.value:
        case ast.Name(id=name) | ast.Attribute(attr=name):
            return holders.get(name)
        case _:
            return None


def _type_unions(node: ast.expr, holders: dict[str, str]) -> Iterator[ast.BinOp]:
    """Yield the `|` operations between type expressions in an annotation.

    The values of a `Literal[...]` and the metadata of an `Annotated[...]` are ordinary expressions, where a
    replaced `|` can give another valid value, so they are not entered.
    """
    match node:
        case ast.BinOp(op=ast.BitOr(), left=left, right=right):
            if _is_type_expression(node):
                yield node
            yield from _type_unions(left, holders)
            yield from _type_unions(right, holders)
        case ast.Subscript(slice=subscript):
            match _subscripted_holder(node, holders), subscript:
                case "Literal", _:
                    return
                case "Annotated", ast.Tuple(elts=[annotated_type, *_]):
                    yield from _type_unions(annotated_type, holders)
                case _:
                    yield from _type_unions(subscript, holders)
        case ast.Tuple(elts=elements) | ast.List(elts=elements):
            for element in elements:
                yield from _type_unions(element, holders)
        case _:
            return


@cache
def find_annotation_unions(source: str) -> set[SourceSpan]:
    """Return where the `|` of every union of types in an annotation sits: between its two operands.

    Annotations are those of parameters, returns and annotated assignments, the values of `type` aliases,
    and the bound, constraints and default of a `TypeVar` type parameter. The default of a `ParamSpec` or a
    `TypeVarTuple` is not looked at. `Literal` and `Annotated` are recognized under any name an import gives
    them, not under one made by assignment.
    """
    tree = ast.parse(source)
    holders = _find_value_holders(tree)
    lines = source.splitlines()
    return {
        _span_between(union.left, union.right, lines)
        for node in ast.walk(tree)
        for annotation in _annotations_of(node)
        if annotation is not None
        for union in _type_unions(annotation, holders)
    }


@cache
def _read_module(module_path: str) -> str:
    return Path(module_path).read_text(encoding="utf-8")


def _is_exempt(operator_name: str, mutation: SourceSpan, source: str) -> bool:
    if operator_name == NEGATION_OPERATOR:
        return mutation in find_import_only_guards(source)
    if operator_name.startswith(UNION_OPERATOR_PREFIX):
        return any(union.contains(mutation) for union in find_annotation_unions(source))
    return False


def find_exempt_survivors(connection: sqlite3.Connection) -> list[str]:
    """Return the job ids of the surviving mutants that are exempt from the survival rate."""
    job_ids = []
    for job_id, module_path, operator_name, *positions in connection.execute(SURVIVOR_QUERY).fetchall():
        start_row, start_column, end_row, end_column = positions
        mutation = SourceSpan(start=(start_row, start_column), end=(end_row, end_column))
        if _is_exempt(operator_name, mutation, _read_module(module_path)):
            job_ids.append(job_id)
    return job_ids


def find_unfinished_jobs(connection: sqlite3.Connection) -> list[str]:
    """Return the job ids that are not in all three tables of the session: a mutant without a spec or a result."""
    job_ids_by_table = [
        {job_id for (job_id,) in connection.execute(f"SELECT job_id FROM {table}")} for table in SESSION_TABLES
    ]
    return sorted(set.union(*job_ids_by_table) - set.intersection(*job_ids_by_table))


def drop_jobs(connection: sqlite3.Connection, job_ids: list[str]) -> None:
    """Delete the given jobs from every table of the session."""
    for table in SESSION_TABLES:
        connection.executemany(f"DELETE FROM {table} WHERE job_id = ?", [(job_id,) for job_id in job_ids])
    connection.commit()


def main() -> None:
    parser = argparse.ArgumentParser(description="Drop the exempt survivors from a finished cosmic-ray session")
    parser.add_argument("session", type=Path, help="cosmic-ray session database, after `cosmic-ray exec`")
    args = parser.parse_args()
    with closing(sqlite3.connect(args.session)) as connection:
        unfinished = find_unfinished_jobs(connection)
        if unfinished:
            raise SystemExit(f"{args.session} is unfinished: {len(unfinished)} mutant(s) lack a spec or a result")
        job_ids = find_exempt_survivors(connection)
        drop_jobs(connection, job_ids)
    print(f"Dropped {len(job_ids)} exempt survivor(s) from {args.session}")


if __name__ == "__main__":
    main()
