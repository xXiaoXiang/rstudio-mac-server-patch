import importlib.util
import json
from pathlib import Path
import sys
import tempfile
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
        existing = [{"tag_name": "v2026.11.0+203-macos.1", "draft": False}]
        self.assertEqual(release.plan([{"name": "v2026.11.0+203"}], existing, 1, (2026, 11)), [])

    def test_new_patch_revision_and_incomplete_draft_can_be_built(self):
        tags = [{"name": "v2026.11.0+203"}]
        existing = [{"tag_name": "v2026.11.0+203-macos.1", "draft": False}]
        self.assertEqual(len(release.plan(tags, existing, 2, (2026, 11))), 1)
        existing[0]["draft"] = True
        self.assertEqual(len(release.plan(tags, existing, 1, (2026, 11))), 1)

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


if __name__ == "__main__":
    unittest.main()
