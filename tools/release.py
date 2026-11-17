#!/usr/bin/env python3
"""Plan upstream tag builds, apply the patch series, and publish complete packages."""
import argparse
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
TAG_PATTERN = re.compile(r"v(20[0-9]{2})\.([0-9]{1,2})\.([0-9]+)\+([0-9]+)\Z")


@dataclass(frozen=True)
class Release:
    tag: str
    parts: tuple
    fields: tuple

    @classmethod
    def parse(cls, tag, minimum=(2026, 11)):
        match = TAG_PATTERN.fullmatch(tag)
        if not match:
            raise ValueError("Not a numeric upstream release tag: " + tag)
        fields = match.groups()
        parts = tuple(map(int, fields))
        if not 1 <= parts[1] <= 12 or parts[2] >= 999:
            raise ValueError("Invalid month or development version: " + tag)
        if parts[:2] < tuple(minimum):
            raise ValueError("Release predates the configured minimum: " + tag)
        return cls(tag, parts, fields)

    @property
    def version(self):
        return self.tag[1:]

    def item(self, revision):
        return {
            "tag": self.tag,
            "version": self.version,
            "release_tag": self.tag,
            "artifact": self.tag.replace("+", "-"),
            "package": "RStudioServer-" + self.version.replace("+", "-")
                       + "-arm64.pkg",
        }


def manifest():
    data = json.loads((ROOT / "patches/series.json").read_text())
    if type(data["revision"]) is not int or data["revision"] < 1:
        raise ValueError("Patch revision must be a positive integer")
    if data["upstream"] != "rstudio/rstudio":
        raise ValueError("Unexpected upstream repository")
    if not data["patches"]:
        raise ValueError("The patch series is empty")
    for item in data["patches"]:
        name = item["file"]
        if Path(name).name != name or not name.endswith(".patch"):
            raise ValueError("Invalid patch filename: " + name)
        if digest(ROOT / "patches" / name) != item["sha256"]:
            raise ValueError("Patch checksum mismatch: " + name)
    return data


def digest(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def command(args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)


def git(source, *args):
    return subprocess.check_output(["git", "-C", str(source), *args], text=True).strip()


def gh_pages(endpoint):
    output = subprocess.check_output(["gh", "api", "--paginate", "--slurp", endpoint], text=True)
    return [item for page in json.loads(output) for item in page]


def plan(tags, existing, revision, minimum, requested="", limit=4):
    candidates = []
    for entry in tags:
        try:
            candidates.append(Release.parse(entry["name"], minimum))
        except ValueError:
            pass
    if requested:
        selected = Release.parse(requested, minimum)
        if selected.tag not in {release.tag for release in candidates}:
            raise ValueError("Requested tag does not exist upstream: " + requested)
        candidates = [selected]
    else:
        candidates = sorted(set(candidates), key=lambda release: release.parts)
    marker = "<!-- macos-patch-revision: " + str(revision) + " -->"
    published = {item["tag_name"] for item in existing if not item.get("draft", False)
                 and marker in item.get("body", "")}
    all_versions = [release.parts for release in candidates]
    for item in existing:
        try:
            all_versions.append(Release.parse(item["tag_name"].split("-macos.")[0], minimum).parts)
        except ValueError:
            pass
    newest = max(all_versions, default=())
    results = []
    for release in candidates:
        item = release.item(revision)
        if requested or item["release_tag"] not in published:
            item["make_latest"] = release.parts == newest
            results.append(item)
    return results[:limit]


def plan_command(args):
    data = manifest()
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", args.repository):
        raise ValueError("Expected owner/repository")
    tags = (json.loads(args.tags_json.read_text()) if args.tags_json else
            gh_pages("repos/rstudio/rstudio/tags?per_page=100"))
    existing = (json.loads(args.releases_json.read_text()) if args.releases_json else
                gh_pages("repos/" + args.repository + "/releases?per_page=100"))
    selected = plan(tags, existing, data["revision"], data["minimum_release"], args.tag)
    matrix = json.dumps({"include": selected}, separators=(",", ":"))
    print(matrix)
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as stream:
            stream.write("matrix=" + matrix + "\ncount=" + str(len(selected)) + "\n")


def apply_command(args):
    data = manifest()
    Release.parse(args.tag, data["minimum_release"])
    source = args.source.resolve()
    if git(source, "status", "--porcelain"):
        raise ValueError("Source worktree must be clean before applying patches")
    if git(source, "rev-parse", "HEAD") != git(source, "rev-parse", args.tag + "^{commit}"):
        raise ValueError("Source HEAD does not match the requested upstream tag")
    environment = dict(os.environ, GIT_COMMITTER_NAME="macOS Server patch builder",
                       GIT_COMMITTER_EMAIL="noreply@github.com")
    patches = [str(ROOT / "patches" / item["file"]) for item in data["patches"]]
    try:
        command(["git", "-C", str(source), "am", "--no-gpg-sign", *patches], env=environment)
    except subprocess.CalledProcessError:
        command(["git", "-C", str(source), "am", "--abort"])
        raise RuntimeError("Patch application failed; no automatic conflict resolution or publication")


def provenance_command(args):
    data = manifest()
    release = Release.parse(args.tag, data["minimum_release"])
    item = release.item(data["revision"])
    output = args.output.resolve()
    package = output / item["package"]
    if not package.is_file():
        raise ValueError("Missing completed package: " + str(package))
    built_version = (args.source / "build-macos-server/VERSION").read_text().strip()
    if built_version != release.version:
        raise ValueError("Built version does not match the requested release: " + built_version)
    if git(args.source, "status", "--porcelain"):
        raise ValueError("Unexpected uncommitted source changes")
    source_name = "RStudioServer-" + release.version.replace("+", "-") + "-source.tar.gz"
    source_archive = output / source_name
    command(["git", "-C", str(args.source), "archive", "--format=tar.gz",
             "--prefix=rstudio-macos-server/", "--output=" + str(source_archive), "HEAD"])
    record = {
        "upstream": "https://github.com/rstudio/rstudio",
        "upstream_tag": release.tag,
        "upstream_commit": git(args.source, "rev-parse", release.tag + "^{commit}"),
        "patched_source_commit": git(args.source, "rev-parse", "HEAD"),
        "patch_repository_commit": git(ROOT, "rev-parse", "HEAD"),
        "patch_revision": data["revision"],
        "patches": data["patches"],
        "architecture": "arm64",
        "package_sha256": digest(package),
        "source_sha256": digest(source_archive),
        "app_signing": "ad hoc",
        "package_signing": "unsigned",
        "live_account_session_tests": "optional; not run by this workflow",
        "workflow_url": os.environ.get("GITHUB_SERVER_URL", "https://github.com") + "/"
                        + os.environ.get("GITHUB_REPOSITORY", "local") + "/actions/runs/"
                        + os.environ.get("GITHUB_RUN_ID", "local"),
    }
    (output / "PROVENANCE.json").write_text(json.dumps(record, indent=2) + "\n")
    notes = (
        "Native arm64 macOS Server build based on RStudio " + release.version + ".\n\n"
        "This is a community macOS port, not an official Posit macOS Server package. "
        "The app is ad hoc signed and the PKG is unsigned; Developer ID signing and "
        "Apple notarization are not configured in this workflow.\n\n"
        "Install R separately. Quit active Server sessions and the control app before "
        "installing/upgrading. Open RStudioServer.app afterward and approve background "
        "startup in System Settings when requested. Existing user homes are preserved.\n\n"
        "GitHub's automatic source ZIP/tar.gz contain the patch repository at the original release tag, not the full RStudio tree. "
        "For replacement packages use the exact patch-source commit linked below. "
        "Reconstruct the matching source using the upstream tag and tools/release.py apply. "
        "The full patched source and build records are also retained in the linked Actions run. "
        "Live account/PAM and service tests are optional developer tools and do not run in CI.\n"
    )
    notes += ("\n\nUpstream: " + release.tag + " (" + record["upstream_commit"] + ").\n"
              + "[Exact patch source](https://github.com/" + os.environ.get("GITHUB_REPOSITORY", "xXiaoXiang/rstudio-mac-server-patch")
              + "/tree/" + record["patch_repository_commit"] + "): " + record["patch_repository_commit"] + ".\n"
              + "Package SHA256: " + record["package_sha256"] + ".\n\n"
              + "[Build and source artifacts](" + record["workflow_url"] + ").\n\n"
              + "<!-- macos-patch-revision: " + str(data["revision"]) + " -->\n")
    (output / "RELEASE-NOTES.md").write_text(notes)
    assets = [package, source_archive, output / "PROVENANCE.json", output / "RELEASE-NOTES.md"]
    (output / "SHA256SUMS").write_text("".join(digest(path) + "  " + path.name + "\n" for path in assets))


def publish_command(args):
    data = manifest()
    release = Release.parse(args.tag, data["minimum_release"])
    item = release.item(data["revision"])
    output = args.output.resolve()
    assets = []
    for line in (output / "SHA256SUMS").read_text().splitlines():
        expected, name = line.split("  ", 1)
        if Path(name).name != name or not re.fullmatch(r"[0-9a-f]{64}", expected):
            raise ValueError("Invalid checksum entry")
        path = output / name
        if path.is_symlink() or digest(path) != expected:
            raise ValueError("Release asset checksum mismatch: " + name)
        assets.append(str(path))
    expected_names = {item["package"], "RStudioServer-" + release.version.replace("+", "-")
                      + "-source.tar.gz", "PROVENANCE.json", "RELEASE-NOTES.md"}
    if {Path(path).name for path in assets} != expected_names:
        raise ValueError("Incomplete release assets")
    # New drafts can have no Git tag yet and return 404 from releases/tags.
    # Resolve drafts by listing releases, then verify assets by numeric ID.
    records = gh_pages("repos/" + args.repository + "/releases?per_page=100")
    current = next((record for record in records if record["tag_name"] == item["release_tag"]), None)
    if current is None:
        command(["gh", "release", "create", item["release_tag"], "--repo", args.repository,
                 "--target", args.commit, "--title", "RStudio Server " + release.version
                 + " for macOS arm64",
                 "--notes-file", str(output / "RELEASE-NOTES.md"), "--draft"])
        current = next(record for record in gh_pages("repos/" + args.repository
            + "/releases?per_page=100") if record["tag_name"] == item["release_tag"])
    # Check all build artifacts above, but attach only the completed installer.
    expected_digest = "sha256:" + digest(output / item["package"])
    existing_asset = next((asset for asset in current.get("assets", [])
                           if asset["name"] == item["package"]), {})
    if existing_asset.get("digest") != expected_digest:
        command(["gh", "release", "upload", item["release_tag"], "--repo", args.repository,
                 "--clobber", str(output / item["package"])])
    uploaded = json.loads(subprocess.check_output(["gh", "api", "repos/" + args.repository
        + "/releases/" + str(current["id"])], text=True))
    package_asset = next(asset for asset in uploaded["assets"] if asset["name"] == item["package"])
    if package_asset.get("digest") != expected_digest:
        raise ValueError("Uploaded package digest does not match the completed build")
    # Create a missing release tag; never rewrite an existing source snapshot.
    reference = "repos/" + args.repository + "/git/ref/tags/" + quote(item["release_tag"], safe="")
    result = subprocess.run(["gh", "api", reference], capture_output=True, text=True)
    if result.returncode:
        if "HTTP 404" not in result.stderr:
            raise RuntimeError(result.stderr)
        command(["gh", "api", "--method", "POST", "repos/" + args.repository + "/git/refs",
                 "-f", "ref=refs/tags/" + item["release_tag"], "-f", "sha=" + args.commit])
    command(["gh", "release", "edit", item["release_tag"], "--repo", args.repository,
             "--title", "RStudio Server " + release.version + " for macOS arm64",
             "--notes-file", str(output / "RELEASE-NOTES.md"),
             "--draft=false", "--latest=" + str(args.latest).lower()])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    select = commands.add_parser("plan")
    select.add_argument("--repository", required=True)
    select.add_argument("--tag", default="")
    select.add_argument("--tags-json", type=Path)
    select.add_argument("--releases-json", type=Path)
    select.set_defaults(run=plan_command)
    apply = commands.add_parser("apply")
    apply.add_argument("--source", type=Path, required=True)
    apply.add_argument("--tag", required=True)
    apply.set_defaults(run=apply_command)
    provenance = commands.add_parser("provenance")
    provenance.add_argument("--source", type=Path, required=True)
    provenance.add_argument("--tag", required=True)
    provenance.add_argument("--output", type=Path, required=True)
    provenance.set_defaults(run=provenance_command)
    publish = commands.add_parser("publish")
    publish.add_argument("--tag", required=True)
    publish.add_argument("--repository", required=True)
    publish.add_argument("--commit", required=True)
    publish.add_argument("--output", type=Path, required=True)
    publish.add_argument("--latest", action="store_true")
    publish.set_defaults(run=publish_command)
    args = parser.parse_args()
    try:
        args.run(args)
    except (ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        parser.exit(1, str(error) + "\n")


if __name__ == "__main__":
    main()
