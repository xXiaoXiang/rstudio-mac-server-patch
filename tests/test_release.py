import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import subprocess
import unittest
from unittest.mock import patch

MODULE = Path(__file__).resolve().parents[1] / "tools/release.py"
spec = importlib.util.spec_from_file_location("release", MODULE)
release = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = release
spec.loader.exec_module(release)


class ReleasePlanningTests(unittest.TestCase):
    def test_tag_filter_excludes_old_development_and_preview_versions(self):
        tags = [{"name": name} for name in (
            "v2026.10.1+239", "v2026.11.0+203", "v2026.11.999+999",
            "v2026.12.0+1-preview", "v2027.01.0+8")]
        planned = release.plan(tags, [], 1, (2026, 11))
        self.assertEqual([item["tag"] for item in planned], ["v2026.11.0+203", "v2027.01.0+8"])

    def test_published_version_is_not_built_again(self):
        existing = [{"tag_name": "v2026.11.0+203", "draft": False, "body": "<!-- macos-patch-revision: 1 -->"}]
        self.assertEqual(release.plan([{"name": "v2026.11.0+203"}], existing, 1, (2026, 11)), [])

    def test_new_patch_revision_and_incomplete_draft_can_be_built(self):
        tags = [{"name": "v2026.11.0+203"}]
        existing = [{"tag_name": "v2026.11.0+203", "draft": False, "body": "<!-- macos-patch-revision: 1 -->"}]
        self.assertEqual(len(release.plan(tags, existing, 2, (2026, 11))), 1)
        existing[0]["draft"] = True
        self.assertEqual(len(release.plan(tags, existing, 1, (2026, 11))), 1)

    def test_stable_names_and_explicit_rebuild(self):
        item = release.Release.parse("v2026.11.0+203").item(7)
        self.assertEqual(item["package"], "RStudioServer-2026.11.0-203-arm64.pkg")
        self.assertEqual(item["release_tag"], "v2026.11.0+203")
        tags = [{"name": item["tag"]}]
        existing = [{"tag_name": item["tag"], "draft": False,
                     "body": "<!-- macos-patch-revision: 7 -->"}]
        self.assertEqual(release.plan(tags, existing, 7, (2026, 11)), [])
        self.assertEqual(len(release.plan(tags, existing, 7, (2026, 11), item["tag"])), 1)

    def test_invalid_or_unknown_manual_tag_fails(self):
        for tag in ("main", "v2026.11.0+1\nignored", "v2026.13.0+1", "v2026.10.0+233"):
            with self.subTest(tag=tag), self.assertRaises(ValueError):
                release.Release.parse(tag)
        with self.assertRaises(ValueError):
            release.plan([], [], 1, (2026, 11), "v2026.11.0+203")

    def test_old_manual_build_does_not_replace_newest_release(self):
        tags = [{"name": "v2026.11.0+203"}]
        existing = [{"tag_name": "v2027.01.0+8-macos.1", "draft": False}]
        planned = release.plan(tags, existing, 1, (2026, 11), "v2026.11.0+203")
        self.assertFalse(planned[0]["make_latest"])

    def test_backlog_is_bounded_and_sorted_numerically(self):
        tags = [{"name": "v2026.11.0+" + str(number)} for number in (10, 2, 3, 1, 11)]
        planned = release.plan(tags, [], 1, (2026, 11))
        self.assertEqual([item["tag"] for item in planned],
                         ["v2026.11.0+1", "v2026.11.0+2", "v2026.11.0+3", "v2026.11.0+10"])

    def test_patches_do_not_embed_markdown_guides(self):
        data = release.manifest()
        for item in data["patches"]:
            patch_path = release.ROOT / "patches" / item["file"]
            for line in patch_path.read_text().splitlines():
                if line.startswith("diff --git "):
                    self.assertFalse(line.rsplit(" b/", 1)[-1].lower().endswith(".md"), line)
        self.assertTrue((release.ROOT / "docs/SERVER.md").is_file())
        self.assertTrue((release.ROOT / "docs/MAINTAINING-SERVER.md").is_file())

    def test_patch_manifest_is_complete_and_checked(self):
        self.assertTrue(release.manifest()["patches"])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "patches").mkdir()
            (root / "patches/a.patch").write_text("changed patch")
            data = {"upstream": "rstudio/rstudio", "revision": 1,
                    "patches": [{"file": "a.patch", "sha256": "0" * 64}]}
            (root / "patches/series.json").write_text(json.dumps(data))
            with patch.object(release, "ROOT", root), self.assertRaisesRegex(ValueError, "checksum"):
                release.manifest()


class PublishingTests(unittest.TestCase):
    def run_publish(self, remote_digest):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            package = output / "RStudioServer-2026.11.0-203-arm64.pkg"
            package.write_bytes(b"completed installer")
            names = [package.name, "RStudioServer-2026.11.0-203-source.tar.gz",
                     "PROVENANCE.json", "RELEASE-NOTES.md"]
            for name in names[1:]:
                (output / name).write_text("build record")
            (output / "SHA256SUMS").write_text("".join(
                release.digest(output / name) + "  " + name + "\n" for name in names))
            uploaded = {"assets": [{"name": package.name,
                        "digest": remote_digest or "sha256:" + release.digest(package)}]}
            response = subprocess.CompletedProcess([], 0, '{"draft":false}', "")
            args = SimpleNamespace(tag="v2026.11.0+203", output=output,
                repository="example/patches", commit="abc123", latest=True)
            with patch.object(release, "command") as command, \
                 patch.object(release.subprocess, "run", return_value=response), \
                 patch.object(release.subprocess, "check_output", return_value=json.dumps(uploaded)):
                if remote_digest:
                    with self.assertRaisesRegex(ValueError, "digest"):
                        release.publish_command(args)
                else:
                    release.publish_command(args)
                return [call.args[0] for call in command.call_args_list]

    def test_publish_uploads_only_pkg_and_preserves_existing_tag(self):
        calls = self.run_publish(None)
        upload = calls[0]
        self.assertEqual(upload[:3], ["gh", "release", "upload"])
        self.assertEqual(upload[-2], "--clobber")
        self.assertTrue(upload[-1].endswith("RStudioServer-2026.11.0-203-arm64.pkg"))
        self.assertEqual(len(upload), 8)
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[1][:3], ["gh", "release", "edit"])

    def test_bad_uploaded_digest_prevents_tag_update_and_publication(self):
        calls = self.run_publish("sha256:" + "0" * 64)
        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
