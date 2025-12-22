#!/usr/bin/env bash
set -euo pipefail

# Build script for macOS that reuses existing build version (does NOT update it).
# Usage: ./build_exe_mac.sh

root="$(cd "$(dirname "$0")" && pwd)"
cd "$root"

build_py="$root/src/sgm/_build.py"
if [ ! -f "$build_py" ]; then
  echo "Missing $build_py. Please build Windows first to generate the version file." >&2
  exit 1
fi

# Prefer venv python if available
if [ -x "$root/.venv/bin/python" ]; then
  python="$root/.venv/bin/python"
else
  if command -v python3 >/dev/null 2>&1; then
    python="$(command -v python3)"
  else
    python="$(command -v python)"
  fi
fi

echo "Using python: $python"

# Ensure PyInstaller is available
if ! "$python" -m pip show pyinstaller >/dev/null 2>&1; then
  echo "PyInstaller not found in environment; installing..."
  "$python" -m pip install --upgrade pyinstaller
fi

# Clean prior outputs
rm -rf "$root/dist" "$root/build"

# Icon handling (.icns recommended for mac). If missing, continue without icon.
icon_icns="$root/resources/icon.icns"
if [ -f "$icon_icns" ]; then
  echo "Using icon: $icon_icns"
  ICON_PRESENT=true
else
  echo "Warning: $icon_icns not found. Build will proceed without .icns icon."
  ICON_PRESENT=false
fi

# PyInstaller add-data separator on mac (POSIX) is ':'
addData="resources:resources"

echo "Running PyInstaller to create a .app (no version file will be modified)..."

# Build argument array so we can safely add icon only when present
PYI_ARGS=(--noconfirm --clean --windowed --name "SprintGameManager" --paths "src" --add-data "$addData" "main.py")
if [ "$ICON_PRESENT" = true ]; then
  PYI_ARGS+=(--icon "$icon_icns")
fi

# Do NOT use --onefile so PyInstaller produces a .app bundle
"$python" -m PyInstaller "${PYI_ARGS[@]}"

echo "Built: $root/dist/SprintGameManager.app"
