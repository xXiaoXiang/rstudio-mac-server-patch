# Maintaining the macOS Server patches

## Branches and upstream versions

The current source-only branch is macos-server/2026.11.0-203-v2, based on the
official v2026.11.0+203 tag. It contains three commits: native dependencies,
Open Directory PAM, and the native Server app/package lifecycle. The older
feature/macos-server and macos-server/2026.11.0-203 branches are retained locally
for reference; do not export their intermediate documentation changes.

The small patch repository keeps the guides in docs/ and exports only source
and build revisions. It does not need a full upstream fork. On another Mac,
follow the repository README to fetch an official tag and apply the manifest.

To review the current source branch from its RStudio checkout:

    git log --reverse --oneline v2026.11.0+203..macos-server/2026.11.0-203-v2
    git diff --stat v2026.11.0+203 macos-server/2026.11.0-203-v2

The version shown in the app must come from the selected official tag's version
metadata. Changing a development build's display version does not make it a
release build. The 2026.11.0+203 build uses the exact official source tag plus
the macOS patches, then sets RSTUDIO_VERSION_MAJOR/MINOR/PATCH/SUFFIX explicitly.

## Build the prepared release branch

From the development checkout:

    cd ../rstudio-2026.11.0-203
    git status --short --branch
    git describe --tags --match 'v2026.*' --always

Check out the release source plus our patches, then set its build metadata.
Changing metadata on the development source alone does not make it release
source. Without metadata, CMake uses the current year/month and
999-dev+999, even when the source came from a release tag.

Use one Terminal session for configure, build and packaging, keeping these
variables exported so an automatic CMake reconfigure retains the correct version:

    export RSTUDIO_VERSION_MAJOR=2026
    export RSTUDIO_VERSION_MINOR=11
    export RSTUDIO_VERSION_PATCH=0
    export RSTUDIO_VERSION_SUFFIX='+203'
    export JAVA_HOME=/opt/homebrew/opt/openjdk@17
    export PATH="/opt/homebrew/bin:$PATH"

Install dependencies from the release checkout, rather than assuming the
development dependencies match. This release pins Node 24.22.1, GWT
2.13.1-montauk-daisy-4, Quarto 1.10.19 and the montauk-daisy Panmirror branch;
the development snapshot uses newer versions. A configure step can succeed with
shared development tools even though the later UI build or package is wrong.

Use a separate tools root so installing the release's Quarto and other mutable
dependencies does not replace the development tools. The installer may request
administrator authentication for system paths. Run it as your normal user;
its individual steps use sudo where needed. This does not install the Server app.

    export RSTUDIO_TOOLS_ROOT=/opt/rstudio-tools/releases/2026.11.0-203/arm64
    (cd dependencies/osx && ./install-dependencies-osx --arch=arm64)

The release installer also prepares Node/Yarn, GWT and Panmirror inside this
worktree, preventing their fallback to the development checkout. For only the
Node/Yarn installation, use (cd dependencies/common && ./install-npm-dependencies).
Do not substitute that narrower step for all the release dependencies.

    cmake -S . -B build-macos-server -G Ninja \
      -DRSTUDIO_TARGET=Server \
      -DCMAKE_BUILD_TYPE=Release \
      -DCMAKE_OSX_ARCHITECTURES=arm64 \
      -DCMAKE_INSTALL_PREFIX=/Applications \
      -DRSTUDIO_TOOLS_ROOT="$RSTUDIO_TOOLS_ROOT" \
      -DRSTUDIO_UNIT_TESTS_DISABLED=ON \
      -DGWT_BUILD=ON
    cmake --build build-macos-server --parallel 4
    bash package/osx-server/build-pkg.sh build-macos-server \
      build-macos-server/RStudioServer-2026.11.0-203-arm64.pkg

Configure should print Building RStudio 2026.11.0+203. This makes a custom macOS
Server build based on the official source release. The native C++ unit suite was
disabled in the original VM build; omit RSTUDIO_UNIT_TESTS_DISABLED to enable it.
The checks below do not substitute for that suite or live multi-user testing.

Use a separate shell for a different version, or unset the four RSTUDIO_VERSION_*
variables before reconfiguring a development build. Never reuse a CMake build
directory from a different checkout or upstream version.

## Rebase the patches onto another release

First finish/commit current edits and verify git status is clean. From the
original development checkout, fetch the actual upstream tag and create a copy
of the patch branch. Replace NEW_TAG, NEW_BRANCH and NEW_WORKTREE with the desired
tag and unused local names:

    git fetch --no-tags --depth=1 origin tag NEW_TAG
    git branch NEW_BRANCH macos-server/2026.11.0-203-v2
    git worktree add NEW_WORKTREE NEW_BRANCH
    cd NEW_WORKTREE
    git rebase --onto NEW_TAG v2026.11.0+203

The old upstream tag is the essential rebase boundary: it excludes unrelated
upstream development history. These commands leave the current source branch
unchanged and put the rebased commits on NEW_BRANCH.

For conflicts, retain upstream changes and reapply only the macOS-specific
behavior. Inspect git diff --name-only --diff-filter=U, edit the conflicted files,
git add the resolved paths, then git rebase --continue. git rebase --abort restores
the copied branch to its starting state. Do not copy whole files from a newer
upstream development checkout to resolve a release conflict.

Keep new macOS changes in focused commits on the canonical feature branch;
cherry-pick those commits onto release branches as needed. Do not merge unrelated
upstream development history into release branches. Build products, downloaded
dependencies, generated UI files and PKGs remain ignored and outside the commits.

After a successful port, export from the new tag to the new branch using
explicit --base and --branch arguments. Increment the patch manifest revision
before publishing another package for an already published upstream release.
Keep all guide changes here in docs/, outside the source patches.

## Optional developer checks after a port

These scripts are opt-in diagnostics, not required build or installation steps.
They are not called automatically. Ordinary rebases, documentation edits, version
changes, dependency installations and repeat builds do not require rerunning them.
Use them when investigating changes to the integration/administration behavior
they cover. The live account/PAM probe in SERVER.md is also optional and should
only be run when an administrator deliberately chooses that validation.

    python3 dependencies/osx/test-server-integration.py
    python3 dependencies/osx/test-server-administration.py
    git diff --check

The native control app can also be built without the full Server dependencies:

    cmake -S src/cpp/server/extras/macos -B build-server-control -G Ninja \
      -DCMAKE_OSX_ARCHITECTURES=arm64 -DCMAKE_OSX_DEPLOYMENT_TARGET=13.0
    cmake --build build-server-control
    RSTUDIO_SERVER_CONTROL="$PWD/build-server-control/RStudioServer.app/Contents/MacOS/RStudioServer" \
      python3 dependencies/osx/test-server-administration.py

That environment variable lets the native address/port validation tests use the
standalone controller; otherwise they use the full Server build, or skip that
one test when no compiled controller exists. The standalone app is not a complete
Server installation. Building the full Server/UI and installing the package are
separate from these diagnostics. If live authentication/session validation is
desired, SERVER.md documents the optional PAM/HTTP probe. Reboot and uninstall
behavior need their own runtime checks; these scripts do not establish them.
