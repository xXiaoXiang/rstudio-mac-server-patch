#!/bin/bash
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd -P)
PATCH_REPO="$ROOT/rstudio-mac-server-patch"
SNAPSHOT=542f7cecd006150c490dc41981d05667b79814d8
[ ! -e "$PATCH_REPO/.git" ] || { echo "Refusing to overwrite $PATCH_REPO/.git" >&2; exit 1; }
git -C "$ROOT" cat-file -e "$SNAPSHOT^{commit}"
git init -q "$PATCH_REPO"
git -C "$PATCH_REPO" fetch --no-tags "$ROOT" "$SNAPSHOT"
git -C "$PATCH_REPO" symbolic-ref HEAD refs/heads/main
git -C "$PATCH_REPO" reset --mixed FETCH_HEAD
git -C "$PATCH_REPO" remote add origin https://github.com/xXiaoXiang/rstudio-mac-server-patch.git
git -C "$PATCH_REPO" update-ref refs/remotes/origin/main "$SNAPSHOT"
git -C "$PATCH_REPO" branch --set-upstream-to=origin/main main
git -C "$PATCH_REPO" status --short --branch
