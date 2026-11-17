#!/bin/bash
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd -P)
REPOSITORY="$ROOT/rstudio"
[ ! -e "$REPOSITORY/.git" ] || { echo "Refusing to overwrite $REPOSITORY/.git" >&2; exit 1; }
python3 "$ROOT/workspace-state/restore-rstudio-git.py" "$ROOT"
git -C "$REPOSITORY" reset --mixed HEAD
git -C "$REPOSITORY" status --short --branch
