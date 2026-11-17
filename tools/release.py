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
            "release_tag": self.tag + "-macos." + str(revision),
            "artifact": self.tag.replace("+", "-") + "-macos." + str(revision),
            "package": "RStudioServer-" + self.version.replace("+", "-")
                       + "-arm64-macos." + str(revision) + ".pkg",
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
    published = {item["tag_name"] for item in existing if not item.get("draft", False)}
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
        if item["release_tag"] not in published:
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
        "The matching patched source, checksums and build provenance are attached. "
        "Live account/PAM and service tests are optional developer tools and do not run in CI.\n"
    )
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
    result = subprocess.run(["gh", "api", "repos/" + args.repository + "/releases/tags/"
                             + quote(item["release_tag"], safe="")], text=True, capture_output=True)
    if result.returncode:
        if "HTTP 404" not in result.stderr:
            raise RuntimeError(result.stderr)
        command(["gh", "release", "create", item["release_tag"], "--repo", args.repository,
                 "--target", args.commit, "--title", "RStudio Server " + release.version
                 + " for macOS arm64 (patch " + str(data["revision"]) + ")",
                 "--notes-file", str(output / "RELEASE-NOTES.md"), "--draft"])
    elif not json.loads(result.stdout)["draft"]:
        raise ValueError("A published release already exists; increment the patch revision instead of replacing it")
    command(["gh", "release", "upload", item["release_tag"], "--repo", args.repository,
             "--clobber", *assets, str(output / "SHA256SUMS")])
    command(["gh", "release", "edit", item["release_tag"], "--repo", args.repository,
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
