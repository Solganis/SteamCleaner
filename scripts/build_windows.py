"""Two-step Windows build: flet build -> patch -> flutter rebuild.

Flet's Flutter runner shows the window before Python gets control, causing a
visible flash on startup. This script patches two files after flet build:

1. lib/main.dart: sets hideWindowOnStart = true so Dart skips windowManager.show()
2. windows/runner/flutter_window.cpp: removes SetNextFrameCallback -> Show()
3. windows/runner/win32_window.cpp: sets BLACK_BRUSH background to prevent white flash

Then rebuilds via flutter build to compile the patches into the final binary.

Usage:
    uv run python scripts/build_windows.py
    uv run python scripts/build_windows.py --skip-flet-build
    uv run python scripts/build_windows.py --flutter-sdk C:\\flutter\\3.41.7
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

MAIN_DART = BUILD_FLUTTER / "lib" / "main.dart"
FLUTTER_WINDOW_CPP = BUILD_FLUTTER / "windows" / "runner" / "flutter_window.cpp"
WIN32_WINDOW_CPP = BUILD_FLUTTER / "windows" / "runner" / "win32_window.cpp"
FLUTTER_RELEASE = BUILD_FLUTTER / "build" / "windows" / "x64" / "runner" / "Release"

SHOW_CALLBACK_BLOCK = """\
  flutter_controller_->engine()->SetNextFrameCallback([&]() {
    this->Show();
  });

  // Flutter can complete the first frame before the "show window" callback is
  // registered. The following call ensures a frame is pending to ensure the
  // window is shown. It is a no-op if the first frame hasn't completed yet.
  flutter_controller_->ForceRedraw();"""

SHOW_CALLBACK_REPLACEMENT = """\
  flutter_controller_->ForceRedraw();"""


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


# noinspection PyDeprecation
def flet_build():
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


def patch_sources():
    print("=== Step 2/4: Patching build sources ===")
    patched = False

    dart_text = MAIN_DART.read_text(encoding="utf-8")
    if '"None".toLowerCase()' in dart_text:
        dart_text = dart_text.replace(
            'bool.tryParse("None".toLowerCase()) ?? false;',
            'bool.tryParse("True".toLowerCase()) ?? false;',
        )
        MAIN_DART.write_text(dart_text, encoding="utf-8")
        print("  main.dart: hideWindowOnStart -> true")
        patched = True
    elif '"True".toLowerCase()' in dart_text:
        print("  main.dart: already patched")
    else:
        print("  WARNING: main.dart hideWindowOnStart pattern not found", file=sys.stderr)

    cpp_text = FLUTTER_WINDOW_CPP.read_text(encoding="utf-8")
    if "SetNextFrameCallback" in cpp_text:
        cpp_text = cpp_text.replace(SHOW_CALLBACK_BLOCK, SHOW_CALLBACK_REPLACEMENT)
        FLUTTER_WINDOW_CPP.write_text(cpp_text, encoding="utf-8")
        print("  flutter_window.cpp: removed SetNextFrameCallback -> Show()")
        patched = True
    else:
        print("  flutter_window.cpp: already patched")

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
        print("  WARNING: win32_window.cpp hbrBackground pattern not found", file=sys.stderr)

    if not patched:
        print("  (no changes needed)")
    print()


def flutter_rebuild(sdk: Path):
    print("=== Step 3/4: flutter build windows --release ===")
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
    subprocess.run(
        [flutter_executable(sdk), "build", "windows", "--release"],
        cwd=BUILD_FLUTTER,
        check=True,
        env=env,
    )
    print()


def copy_patched_binaries():
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


def main():
    parser = argparse.ArgumentParser(description="Two-step Windows build with startup-flash fix")
    parser.add_argument("--flutter-sdk", type=Path, help="Path to Flutter SDK root")
    parser.add_argument("--skip-flet-build", action="store_true", help="Skip flet build, patch and rebuild only")
    args = parser.parse_args()

    sdk = find_flutter_sdk(args.flutter_sdk)
    print(f"Flutter SDK: {sdk}\n")

    if not args.skip_flet_build:
        flet_build()
    elif not BUILD_FLUTTER.exists():
        print("ERROR: build/flutter not found. Run without --skip-flet-build first.", file=sys.stderr)
        sys.exit(1)

    patch_sources()
    flutter_rebuild(sdk)
    copy_patched_binaries()

    print(f"Build complete: {BUILD_OUTPUT}")


if __name__ == "__main__":
    main()
