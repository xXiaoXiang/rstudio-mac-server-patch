# RStudio Server for macOS: patch series and packages

This repository stores the native macOS Server patches and release automation.
It does not duplicate RStudio's source tree or require a GitHub fork. Every build
checks out a versioned tag from [rstudio/rstudio](https://github.com/rstudio/rstudio),
applies the checksummed patches, and builds a matching arm64 Server and browser UI.
Download completed packages from [Releases](https://github.com/xXiaoXiang/rstudio-mac-server-patch/releases).

The initial supported baseline is **v2026.11.0+203**. macOS Server is a community
port; these packages are not official Posit macOS Server releases. Electron
Desktop keeps its original `RStudio.app` name; Server installs as
`RStudioServer.app` with PAM authentication, per-account UIDs, startup approval,
listen-address settings, service controls and account-management help.

## Automatic packages

The **Build and publish macOS Server** workflow checks upstream tags daily at
04:23 UTC. It accepts numeric release tags from **2026.11 onward**, excludes
development/preview suffixes, and builds up to four pending versions per run.
RStudio currently uses versioned Git tags rather than GitHub Release entries;
the workflow therefore watches tags. A tag's appearance is the automation's
release signal; this does not independently check the Posit download website.

It uses GitHub's standard `macos-15` **arm64** runner, installs the dependencies
pinned by the selected source release, builds the full Server/UI, and publishes:

- `RStudioServer-<version>-arm64-macos.<patch-revision>.pkg`
- The matching patched RStudio source archive
- `PROVENANCE.json` with upstream/patch commits and package/source hashes
- `SHA256SUMS` and installation notes

Releases are named `v2026.11.0+203-macos.1`, for example. Existing published assets
are not overwritten. Increment `revision` in `patches/series.json` when updating
the patch series. Patch conflicts or build/package failures prevent publication.
Only the separate publishing job has permission to write releases.

The initial workflow produces an **ad hoc signed app in an unsigned PKG**.
Developer ID signing and Apple notarization are not configured. R is installed
separately on the target Mac. The build disables the native C++ unit suite; the
three optional PAM/account/service developer scripts are not run by CI.

To start a specific build, open **Actions → Build and publish macOS Server → Run
workflow**, enter `v2026.11.0+203`, and choose whether to publish. Leaving the tag
blank processes pending versions. Unpublished test builds remain available as
Actions artifacts for 14 days. GitHub can disable schedules on inactive public
repositories; check the Actions page if scheduled runs stop.

## Install, upgrade and remove

Quit every active Server R session using **Session → Quit Session**, then quit
the RStudioServer control app before installing a new PKG. Installing over the
development app is supported; a full uninstall is unnecessary for an upgrade.
After installation, open `/Applications/RStudioServer.app`, enable startup and
approve its background item in System Settings when prompted. Startup is a
LaunchDaemon, not an Open at Login application.

To remove the installation instead, quit all sessions and the control app, then
run in your own Terminal:

```sh
sudo /Applications/RStudioServer.app/Contents/Resources/app/bin/uninstall-rstudio-server
```

This removes the app, service registration, installer-owned service identity and
package receipt. User accounts/homes, modified or pre-existing settings, logs,
database and account-management records are preserved. R, Homebrew and source
build dependencies are separate. Do not remove the app in Finder first: macOS
cannot run its uninstaller when it is dragged to Trash.

## Local build

On a native arm64 Mac with Xcode Command Line Tools and Homebrew:

```sh
git clone --depth=1 --branch 'v2026.11.0+203' https://github.com/rstudio/rstudio.git upstream
python3 tools/release.py apply --source upstream --tag 'v2026.11.0+203'
bash tools/build-macos.sh "$PWD/upstream" 'v2026.11.0+203' "$PWD/dist"
```

The dependency installer runs as your normal account and uses sudo for system
setup when necessary. GitHub-hosted macOS runners provide passwordless sudo.
The local source-archive/provenance step expects this patch repository to have a
Git commit. Local builds do not install or restart the app.

## Maintain the patches

Keep development source branches in your separate RStudio checkout. Export only
the commits after their explicit upstream base marker:

```sh
python3 tools/export-patches.py --source ../rstudio \
  --base macos-server/base-main-2da6d1b --branch feature/macos-server --revision 2
```

Commit the regenerated patch files and manifest here. A rebase of the source
branch requires updating the `--base` boundary. Do not commit generated source,
downloaded dependencies, PKGs, signing certificates or account data.

The small `tests/` suite validates release selection and patch integrity.
The validation workflow also checks patch application to the baseline release.
The optional upstream `probe-server-accounts.py` and two `test-server-*.py`
scripts are retained in the patch series for deliberate developer use; they are
not build, installation, or release requirements.

## License

The patches and build tooling are provided under AGPL-3.0, as described in
[COPYING](COPYING). Upstream notices remain in the patched source and packages.
