#!/bin/bash
# Build a native macOS Server installer from a completed CMake Server build.
set -euo pipefail
PACKAGING_DIR=$(cd "$(/usr/bin/dirname "$0")" && /bin/pwd -P)
if [ "$#" -lt 1 ] || [ "$#" -gt 2 ]; then
 echo "Usage: bash package/osx-server/build-pkg.sh BUILD_DIRECTORY [OUTPUT.pkg]" >&2
 exit 2
fi
BUILD_DIR=$(cd "$1" && /bin/pwd -P)
OUTPUT=${2:-"$BUILD_DIR/RStudioServer-arm64.pkg"}
case "$OUTPUT" in /*) ;; *) OUTPUT="$PWD/$OUTPUT" ;; esac
if ! /usr/bin/grep -q '^CMAKE_INSTALL_PREFIX:PATH=/Applications$' "$BUILD_DIR/CMakeCache.txt" ||
   ! /usr/bin/grep -q '^RSTUDIO_TARGET:.*=Server$' "$BUILD_DIR/CMakeCache.txt"; then
 echo 'Use a Server build configured with CMAKE_INSTALL_PREFIX=/Applications.' >&2
 exit 1
fi
PAYLOAD=$(/usr/bin/mktemp -d "$BUILD_DIR/pkg-payload.XXXXXX")
COMPONENTS=$(/usr/bin/mktemp "$BUILD_DIR/pkg-components.XXXXXX")
trap '/bin/rm -rf "$PAYLOAD"; /bin/rm -f "$COMPONENTS"' EXIT
INSTALL_LOG="$BUILD_DIR/pkg-install.log"
if ! DESTDIR="$PAYLOAD" cmake --install "$BUILD_DIR" > "$INSTALL_LOG" 2>&1; then
 /usr/bin/tail -n 40 "$INSTALL_LOG" >&2
 exit 1
fi
APP="$PAYLOAD/Applications/RStudioServer.app"
for executable in rserver rsession rserver-pam; do
 if [ "$(/usr/bin/lipo -archs "$APP/Contents/Resources/app/bin/$executable")" != arm64 ]; then
    echo "Expected a native arm64 binary: $executable" >&2; exit 1
 fi
done
VERSION=$(/usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' "$APP/Contents/Info.plist")
SIGN_IDENTITY=${RSTUDIO_MACOS_SIGN_IDENTITY:--}
/usr/bin/codesign --force --deep --sign "$SIGN_IDENTITY" "$APP"
/usr/bin/codesign --verify --deep --strict "$APP"
/usr/bin/pkgbuild --analyze --root "$PAYLOAD" "$COMPONENTS"
# Always install the Server app at its configured location, including upgrades.
/usr/bin/plutil -replace '0.BundleIsRelocatable' -bool false "$COMPONENTS"
/usr/bin/plutil -replace '0.BundleIsVersionChecked' -bool false "$COMPONENTS"
PKG_ARGS=(--root "$PAYLOAD" --component-plist "$COMPONENTS" --scripts "$PACKAGING_DIR/scripts"
 --identifier org.rstudio.RStudioServer.pkg --version "$VERSION" --install-location / --ownership recommended)
if [ -n "${RSTUDIO_MACOS_INSTALLER_IDENTITY:-}" ]; then
 PKG_ARGS+=(--sign "$RSTUDIO_MACOS_INSTALLER_IDENTITY")
fi
/usr/bin/pkgbuild "${PKG_ARGS[@]}" "$OUTPUT"
echo "Created $OUTPUT"
if [ "$SIGN_IDENTITY" = - ]; then
 echo 'Development package: the app is ad hoc signed; Developer ID signing and notarization are required for distribution.'
fi
