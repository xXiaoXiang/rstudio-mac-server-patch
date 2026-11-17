#!/bin/bash
# Build a complete Server PKG; the optional account/service test scripts are not run.
set -euo pipefail
if [ "$#" -ne 3 ]; then
  echo 'Usage: bash tools/build-macos.sh SOURCE UPSTREAM_TAG OUTPUT_DIRECTORY' >&2
  exit 2
fi
if [ "$(uname -sm)" != 'Darwin arm64' ]; then
  echo 'This build requires native arm64 macOS.' >&2
  exit 1
fi
PATCH_ROOT=$(cd "$(dirname "$0")/.." && pwd -P)
SOURCE=$(cd "$1" && pwd -P)
UPSTREAM_TAG=$2
mkdir -p "$3"
OUTPUT=$(cd "$3" && pwd -P)
METADATA=$(python3 - "$PATCH_ROOT" "$UPSTREAM_TAG" <<'PY'
import sys
sys.path.insert(0, sys.argv[1] + '/tools')
from release import Release, manifest
data = manifest()
release = Release.parse(sys.argv[2], data['minimum_release'])
print('\n'.join(release.fields))
print(release.item(data['revision'])['package'])
PY
)
RSTUDIO_VERSION_MAJOR=$(printf '%s\n' "$METADATA" | sed -n '1p')
RSTUDIO_VERSION_MINOR=$(printf '%s\n' "$METADATA" | sed -n '2p')
RSTUDIO_VERSION_PATCH=$(printf '%s\n' "$METADATA" | sed -n '3p')
RSTUDIO_VERSION_SUFFIX=+$(printf '%s\n' "$METADATA" | sed -n '4p')
PACKAGE=$(printf '%s\n' "$METADATA" | sed -n '5p')
export RSTUDIO_VERSION_MAJOR RSTUDIO_VERSION_MINOR RSTUDIO_VERSION_PATCH RSTUDIO_VERSION_SUFFIX
export PATH="/opt/homebrew/bin:$PATH"
export RSTUDIO_TOOLS_ROOT="${RSTUDIO_TOOLS_ROOT:-${RUNNER_TEMP:-$PATCH_ROOT/.cache}/rstudio-tools/arm64}"
export INSTALL_DIR="$RSTUDIO_TOOLS_ROOT/bin"
export R_LIBS_USER="$RSTUDIO_TOOLS_ROOT/r-library"
export npm_config_cache="${RUNNER_TEMP:-$PATCH_ROOT/.cache}/npm-cache"
export CMAKE_BUILD_PARALLEL_LEVEL="${BUILD_JOBS:-3}"
export MAKEFLAGS="-j$CMAKE_BUILD_PARALLEL_LEVEL"
mkdir -p "$INSTALL_DIR" "$R_LIBS_USER"
BUILD="$SOURCE/build-macos-server"
mkdir -p "$BUILD"
# Preserve both a live Actions log and local log files; pipefail propagates failures.
(
  cd "$SOURCE/dependencies/osx"
  ./install-dependencies-osx --arch=arm64
) 2>&1 | tee "$BUILD/dependencies.log"
export JAVA_HOME=/opt/homebrew/opt/openjdk@17
cmake -S "$SOURCE" -B "$BUILD" -G Ninja \
  -DRSTUDIO_TARGET=Server -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_OSX_ARCHITECTURES=arm64 -DCMAKE_OSX_DEPLOYMENT_TARGET=13.0 \
  -DCMAKE_INSTALL_PREFIX=/Applications -DRSTUDIO_TOOLS_ROOT="$RSTUDIO_TOOLS_ROOT" \
  -DRSTUDIO_UNIT_TESTS_DISABLED=ON -DGWT_BUILD=ON \
  2>&1 | tee "$BUILD/configure.log"
cmake --build "$BUILD" --parallel "$CMAKE_BUILD_PARALLEL_LEVEL" \
  2>&1 | tee "$BUILD/build.log"
bash "$SOURCE/package/osx-server/build-pkg.sh" "$BUILD" "$OUTPUT/$PACKAGE" \
  2>&1 | tee "$BUILD/package.log"
python3 "$PATCH_ROOT/tools/release.py" provenance --source "$SOURCE" \
  --tag "$UPSTREAM_TAG" --output "$OUTPUT"
