"""Two-step Windows build: flet build -> patch -> flutter rebuild.

Flet's Flutter runner shows the window before Python gets control, causing a
visible flash on startup. `hide_window_on_start` under `[tool.flet.windows.app]`
in pyproject.toml stops both the Dart side and the native runner from showing
it (the app shows it when ready). This script checks that the setting reached
the generated sources, then patches what flet does not expose:

1. windows/runner/win32_window.cpp: sets BLACK_BRUSH background to prevent white flash
2. windows/runner/resources/app_icon.ico: replaced with assets/icon.ico

Then rebuilds via flutter build to compile the patches into the final binary.

Usage:
    uv run python scripts/build_windows.py
    uv run python scripts/build_windows.py --skip-flet-build
    uv run python scripts/build_windows.py --flutter-sdk C:\\flutter\\3.44.8
"""

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILD_FLUTTER = ROOT / "build" / "flutter"
BUILD_OUTPUT = ROOT / "build" / "windows"

FLET_GENERATED_DART = BUILD_FLUTTER / "lib" / "flet_generated.dart"
FLUTTER_WINDOW_CPP = BUILD_FLUTTER / "windows" / "runner" / "flutter_window.cpp"
WIN32_WINDOW_CPP = BUILD_FLUTTER / "windows" / "runner" / "win32_window.cpp"
FLUTTER_RELEASE = BUILD_FLUTTER / "build" / "windows" / "x64" / "runner" / "Release"
FLUTTER_APP_ICON = BUILD_FLUTTER / "windows" / "runner" / "resources" / "app_icon.ico"
CUSTOM_ICON = ROOT / "assets" / "icon.ico"

HIDDEN_START_DART = 'bool.tryParse("True".toLowerCase())'
HIDDEN_START_CPP = (
    '  const bool hide_window_on_start =\n      true ||\n      HasEnvironmentVariable(L"FLET_HIDE_WINDOW_ON_START");'
)


# shutil.which() carries a PathLike-as-cmd deprecation note for Windows before Python 3.12; we pass a str
# noinspection PyDeprecation
def find_flutter_sdk(hint: Path | None = None) -> Path:
    if hint and (hint / "bin" / "flutter.bat").exists():
        return hint
    if hint and (hint / "bin" / "flutter").exists():
        return hint

    flutter_bin = shutil.which("flutter")
    if flutter_bin:
        return Path(flutter_bin).resolve().parent.parent

    home = Path.home()
    flutter_dir = home / "flutter"
    if flutter_dir.exists():
        for version_dir in sorted(flutter_dir.iterdir(), reverse=True):
            if (version_dir / "bin" / "flutter.bat").exists():
                return version_dir
            if (version_dir / "bin" / "flutter").exists():
                return version_dir

    print("ERROR: Flutter SDK not found.", file=sys.stderr)
    print("  Pass --flutter-sdk <path> or add flutter to PATH.", file=sys.stderr)
    sys.exit(1)


def flutter_executable(sdk: Path) -> str:
    bat = sdk / "bin" / "flutter.bat"
    if bat.exists():
        return str(bat)
    return str(sdk / "bin" / "flutter")


# shutil.which() carries a PathLike-as-cmd deprecation note for Windows before Python 3.12; we pass a str
# noinspection PyDeprecation
def flet_build() -> None:
    print("=== Step 1/4: flet build windows ===")
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
    flet_bin = shutil.which("flet") or "flet"
    subprocess.run(
        [flet_bin, "build", "windows"],
        cwd=ROOT,
        check=True,
        env=env,
    )
    print()


def patch_sources() -> None:
    print("=== Step 2/4: Patching build sources ===")
    patched = False

    dart_hidden = HIDDEN_START_DART in FLET_GENERATED_DART.read_text(encoding="utf-8")
    cpp_hidden = HIDDEN_START_CPP in FLUTTER_WINDOW_CPP.read_text(encoding="utf-8")
    if not (dart_hidden and cpp_hidden):
        print("  ERROR: hide_window_on_start is not set in the generated sources", file=sys.stderr)
        print("  Check [tool.flet.windows.app] in pyproject.toml and rerun flet build.", file=sys.stderr)
        sys.exit(1)
    print("  hide_window_on_start: set in flet_generated.dart and flutter_window.cpp")

    win32_text = WIN32_WINDOW_CPP.read_text(encoding="utf-8")
    if "window_class.hbrBackground = 0;" in win32_text:
        win32_text = win32_text.replace(
            "window_class.hbrBackground = 0;",
            "window_class.hbrBackground = reinterpret_cast<HBRUSH>(GetStockObject(BLACK_BRUSH));",
        )
        WIN32_WINDOW_CPP.write_text(win32_text, encoding="utf-8")
        print("  win32_window.cpp: set black background brush to prevent white flash")
        patched = True
    elif "BLACK_BRUSH" in win32_text:
        print("  win32_window.cpp: already patched")
    else:
        print("  ERROR: win32_window.cpp hbrBackground pattern not found", file=sys.stderr)
        sys.exit(1)

    if CUSTOM_ICON.exists() and FLUTTER_APP_ICON.exists():
        shutil.copy2(CUSTOM_ICON, FLUTTER_APP_ICON)
        print("  app_icon.ico: replaced with custom icon")
        patched = True
    elif not CUSTOM_ICON.exists():
        print("  WARNING: assets/icon.ico not found, using default Flutter icon", file=sys.stderr)

    if not patched:
        print("  (no changes needed)")
    print()


def flutter_rebuild(sdk: Path) -> None:
    print("=== Step 3/4: flutter build windows --release ===")
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
    subprocess.run(
        [flutter_executable(sdk), "build", "windows", "--release"],
        cwd=BUILD_FLUTTER,
        check=True,
        env=env,
    )
    print()


def copy_patched_binaries() -> None:
    print("=== Step 4/4: Copying patched binaries ===")
    exe_src = FLUTTER_RELEASE / "steamcleaner.exe"
    exe_dst = BUILD_OUTPUT / "steamcleaner.exe"
    shutil.copy2(exe_src, exe_dst)
    print(f"  {exe_dst}")

    app_so_src = FLUTTER_RELEASE / "data" / "app.so"
    app_so_dst = BUILD_OUTPUT / "data" / "app.so"
    shutil.copy2(app_so_src, app_so_dst)
    print(f"  {app_so_dst}")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(description="Two-step Windows build with startup-flash fix")
    parser.add_argument("--flutter-sdk", type=Path, help="Path to Flutter SDK root")
    parser.add_argument("--skip-flet-build", action="store_true", help="Skip flet build, patch and rebuild only")
    args = parser.parse_args()

    if not args.skip_flet_build:
        flet_build()
    elif not BUILD_FLUTTER.exists():
        print("ERROR: build/flutter not found. Run without --skip-flet-build first.", file=sys.stderr)
        sys.exit(1)

    sdk = find_flutter_sdk(args.flutter_sdk)
    print(f"Flutter SDK: {sdk}\n")

    patch_sources()
    flutter_rebuild(sdk)
    copy_patched_binaries()

    print(f"Build complete: {BUILD_OUTPUT}")


if __name__ == "__main__":
    main()
