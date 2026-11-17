# Restoring This Workspace

This branch snapshots source, Git history, settings, and instructions, not
generated builds, downloaded dependencies, credentials, or PKG files. The
sibling directory rstudio-2026.11.0-203 was deliberately excluded. Its tracked
source state is represented by the included RStudio checkout, refs, and shallow
Git-history archive.

## Contents

- R_in_conda/ contains the Linux management application and wrappers. Its Flask
  signing key was removed. Configure CONDA_R_FLASK_SECRET_KEY with a fresh,
  random value before running the portal.
- rstudio-mac-server-patch/ contains build and publish automation and docs.
  The separate GitHub main branch remains patch-only.
- rstudio/ contains committed RStudio source at the recorded development branch
  head, plus the VM's VS Code launch/settings/task files.
- workspace-state/git-history/ contains the sanitized shallow Git database,
  split into GitHub-safe parts, the original local refs, and checksums.
- workspace-state/build-config/rstudio/build-settings.json records portable
  build choices and the verified PKG checksum, without machine-specific paths.
- workspace-state/tool-versions.json records the original tool versions.

The original Linux source was archived after replacing its hard-coded Flask
signing key with an environment variable. A fresh signing key is intentionally
not part of this backup.

## Reconstruct the RStudio Git Checkout

Clone the backup branch first (do not use a shallow clone or download the ZIP
if you also want to recover the nested patch repository history):

    git clone --single-branch --branch patched-dev-root \
      https://github.com/xXiaoXiang/rstudio-mac-server-patch.git RstudioServerMacOS
    cd RstudioServerMacOS

From this repository root, run:

    ./workspace-state/restore-rstudio-git.sh
    ./workspace-state/restore-patch-repo.sh

The script verifies every part before joining the history archive, extracts the
Git database under rstudio/.git, verifies HEAD against the snapshot, and restores
the recorded local branches and tags. The second script restores the nested
patch repository's main branch at the saved commit using the outer clone's Git
history; it does not need network access. It refuses to overwrite an existing
rstudio/.git.

The RStudio checkout was shallow. Its ancestry beyond the recorded shallow
boundaries is not included. All Git objects and refs present in the VM are
included. Rebuild products, build-tools, downloaded Node/GWT dependencies,
package outputs, runtime caches, IDE extension downloads, and Actions build
artifacts are omitted; recreate them by following the build guide and workflow.

## Recreate the Excluded Release Worktree

The visible rstudio/ source snapshot is the original development branch.
The latest app fixes are on the preserved macos-server/2026.11.0-203-v2 branch.
After restoring Git metadata, reconstruct that release checkout with:

    git -C rstudio worktree add ../rstudio-2026.11.0-203 macos-server/2026.11.0-203-v2

The original release directory and its build outputs were not copied. Only its
local branch history is retained in the Git archive. Newly reconstructed source
can be rebuilt using the patch repository's build script.

## Rebuild on Apple Silicon

Install Xcode Command Line Tools, native arm64 Homebrew, and current RStudio
build dependencies. The downloaded build-tools tree and generated build files
are omitted and must be recreated. See
rstudio-mac-server-patch/docs/SERVER.md for macOS Server build, signing, package,
and installation instructions. For an automated release build, use the
patch-only repository's Actions workflow. The macOS system account records, login passwords, keychain, installed
applications, /etc/rstudio, and user home data were outside this workspace and
are not included. This snapshot does not preserve the VM itself.

For a release build after restoring both nested Git repositories and creating
the release worktree:

    bash rstudio-mac-server-patch/tools/build-macos.sh \
      "$PWD/rstudio-2026.11.0-203" 'v2026.11.0+203' "$PWD/dist"

This downloads dependencies and builds a fresh PKG; it does not install or
restart the system service.

Generate a fresh secret before starting the legacy Linux portal, for example:

    export CONDA_R_FLASK_SECRET_KEY="$(python3 -c 'import secrets; print(secrets.token_hex(32))')"

Keep this value stable across the portal's workers. Do not commit the value.
Existing browser logins from the old portal will no longer be valid.
