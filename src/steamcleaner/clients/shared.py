import re
from collections.abc import Callable, Iterator
from pathlib import Path

from steamcleaner.models.junk import JunkCategory, JunkEntry
from steamcleaner.utils.fs import walk_files

REDIST_DIR_RE = re.compile(r"(directx|redist|_commonredist|miles|support|installer)", re.IGNORECASE)
JUNK_EXTENSIONS = frozenset({".cab", ".exe", ".msi", ".so", ".dll"})
DUMP_EXTENSIONS = frozenset({".dmp", ".mdmp"})
DEFAULT_LOG_MIN_SIZE = 1024 * 1024


def has_redist_ancestor(file_path: Path, root: Path, pattern: re.Pattern[str] = REDIST_DIR_RE) -> bool:
    current = file_path.parent
    while current != root:
        if pattern.search(current.name):
            return True
        current = current.parent
    return False


def find_redist_root(file_path: Path, root: Path, pattern: re.Pattern[str] = REDIST_DIR_RE) -> Path | None:
    current = file_path.parent
    topmost = None
    while current != root:
        if pattern.search(current.name):
            topmost = current
        current = current.parent
    return topmost


def scan_launcher_logs(
    log_dirs: list[Path],
    client_name: str,
    cancel_check: Callable[[], bool],
    description: str,
    game_root: Path | None = None,
    log_min_size: int = DEFAULT_LOG_MIN_SIZE,
) -> Iterator[JunkEntry]:
    """Scan launcher log directories for large .log files."""
    for logs_dir in log_dirs:
        if not logs_dir.is_dir():
            continue
        root = game_root or logs_dir.parent
        for file_path, size in walk_files(logs_dir):
            if cancel_check():
                return
            if file_path.suffix.lower() == ".log" and size >= log_min_size:
                yield JunkEntry(
                    path=file_path,
                    category=JunkCategory.OLD_LOG,
                    size_bytes=size,
                    client_name=client_name,
                    description=description,
                    game_root=root,
                )


def scan_game(
    game_dir: Path,
    client_name: str,
    cancel_check: Callable[[], bool],
    pattern: re.Pattern[str] = REDIST_DIR_RE,
    log_min_size: int = DEFAULT_LOG_MIN_SIZE,
) -> Iterator[JunkEntry]:
    """Single-pass scan of a game directory for redist, dumps, and logs."""
    found_redist: list[Path] = []
    for file_path, size in walk_files(game_dir):
        if cancel_check():
            return
        extension = file_path.suffix.lower()

        if extension in DUMP_EXTENSIONS and size > 0:
            yield JunkEntry(
                path=file_path,
                category=JunkCategory.CRASH_DUMP,
                size_bytes=size,
                client_name=client_name,
                description=f"Crash dump in {game_dir.name}",
                game_root=game_dir,
            )
            continue

        if extension == ".log" and size >= log_min_size:
            yield JunkEntry(
                path=file_path,
                category=JunkCategory.OLD_LOG,
                size_bytes=size,
                client_name=client_name,
                description=f"Log file in {game_dir.name}",
                game_root=game_dir,
            )
            continue

        if extension in JUNK_EXTENSIONS and has_redist_ancestor(file_path, game_dir, pattern):
            redist_dir = find_redist_root(file_path, game_dir, pattern)
            if redist_dir and not any(redist_dir.is_relative_to(existing) for existing in found_redist):
                junk_size = sum(
                    file_size
                    for file_item, file_size in walk_files(redist_dir)
                    if file_item.suffix.lower() in JUNK_EXTENSIONS
                )
                if junk_size > 0:
                    found_redist.append(redist_dir)
                    rel = redist_dir.relative_to(game_dir)
                    yield JunkEntry(
                        path=redist_dir,
                        category=JunkCategory.REDISTRIBUTABLE,
                        size_bytes=junk_size,
                        client_name=client_name,
                        description=f"{game_dir.name}/{rel}",
                        game_root=game_dir,
                    )
