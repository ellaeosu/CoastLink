"""Update path, transaction, feed-selection and release URL regressions."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import engine
import update_apply


class UpdateFlowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name) / "CoastLink"
        (self.repo / "coastlink").mkdir(parents=True)
        (self.repo / "coastlink" / "engine.py").write_text("original")
        (self.repo / "SOURCE.json").write_text(json.dumps({"version": "0.6.0"}))

    def package(self, files):
        manifest = {"product": "CoastLink", "version": "0.6.1", "upstream_commit": engine.UPSTREAM_COMMIT,
                    "files": {name: hashlib.sha256(data).hexdigest() for name, data in files.items()}}
        path = self.repo / "test-update.zip"
        with zipfile.ZipFile(path, "w") as archive:
            for name, data in files.items():
                archive.writestr(name, data)
            archive.writestr(update_apply.MANIFEST, json.dumps(manifest))
        return path

    def test_changing_repository_replaces_derived_feed(self):
        first = update_apply.save_config(self.repo, {"repo": "first/release"})
        self.assertIn("first/release", first["feed"])
        second = update_apply.save_config(self.repo, {"repo": "second/release"})
        self.assertIn("second/release", second["feed"])
        self.assertNotIn("first/release", second["feed"])
        stored = json.loads((self.repo / update_apply.CONFIG_NAME).read_text())
        self.assertEqual(stored["feed"], "")

    def test_explicit_feed_is_preserved_when_only_notification_setting_changes(self):
        feed = "https://updates.example/coastlink-release.json"
        update_apply.save_config(self.repo, {"feed": feed})
        self.assertEqual(update_apply.save_config(self.repo, {"check_on_launch": False})["feed"], feed)

    def test_fresh_install_uses_bundled_default_without_overwriting_custom_feed(self):
        path = self.repo / update_apply.BUNDLED_CONFIG
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"repo": "official/CoastLink"}))
        self.assertIn("official/CoastLink", update_apply.load_config(self.repo)["feed"])
        update_apply.save_config(self.repo, {"repo": "personal/CoastLink"})
        self.assertIn("personal/CoastLink", update_apply.load_config(self.repo)["feed"])
        update_apply.save_config(self.repo, {"feed": "https://custom.example/feed.json"})
        self.assertEqual(update_apply.load_config(self.repo)["feed"], "https://custom.example/feed.json")

    def test_old_empty_feed_config_uses_new_bundled_default(self):
        path = self.repo / update_apply.BUNDLED_CONFIG
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"repo": "official/CoastLink"}))
        config = self.repo / update_apply.CONFIG_NAME
        config.parent.mkdir(parents=True)
        config.write_text(json.dumps({"repo": "", "feed": "", "check_on_launch": False}))
        result = update_apply.load_config(self.repo)
        self.assertEqual(result["repo"], "official/CoastLink")
        self.assertFalse(result["check_on_launch"])

    def test_invalid_repository_or_credentialed_feed_is_rejected(self):
        for changes in ({"repo": "not a repository"}, {"repo": "owner/repo/extra"},
                        {"feed": "https://user:password@example/release.json"}, {"feed": "https:///missing-host"}):
            with self.assertRaises(update_apply.UpdateError):
                update_apply.save_config(self.repo, changes)

    def test_zip_aliases_and_windows_devices_are_rejected(self):
        for name in ("coastlink//engine.py", "scripts/./file.py", "coastlink/x/../engine.py", "CoastLink/",
                     "coastlink/CON.py", "scripts/NUL", "coastlink/LPT1.txt", "coastlink/COM².txt"):
            with self.assertRaises(update_apply.UpdateError, msg=name):
                update_apply.canonical(name)

    def test_valid_prefixed_update_name_has_one_canonical_destination(self):
        self.assertEqual(update_apply.canonical("CoastLink/coastlink/engine.py"), "coastlink/engine.py")

    def test_missing_original_exe_does_not_leave_pending_exe_after_rollback(self):
        result = update_apply.apply_update(self.repo, self.package({"CoastLink.exe": b"MZ new"}))
        self.assertTrue((self.repo / "CoastLink.exe.new").exists())
        update_apply.roll_back(self.repo, result["backup"])
        self.assertFalse((self.repo / "CoastLink.exe.new").exists())

    def test_invalid_later_target_does_not_partially_replace_earlier_file(self):
        original = update_apply._target
        def target(repo, name, **kwargs):
            if name == "coastlink/new.py":
                raise update_apply.UpdateError("unsafe test target")
            return original(repo, name, **kwargs)
        with patch("update_apply._target", side_effect=target):
            with self.assertRaisesRegex(update_apply.UpdateError, "unsafe test target"):
                update_apply.apply_update(self.repo, self.package({"coastlink/engine.py": b"new", "coastlink/new.py": b"x"}))
        self.assertEqual((self.repo / "coastlink" / "engine.py").read_text(), "original")
        self.assertFalse(update_apply.backups_root(self.repo).exists())

    def test_write_failure_restores_previous_files(self):
        original = update_apply._write
        def write(path, data):
            if path.name == "new.py":
                raise OSError("simulated locked file")
            return original(path, data)
        with patch("update_apply._write", side_effect=write):
            with self.assertRaisesRegex(update_apply.UpdateError, "everything was restored"):
                update_apply.apply_update(self.repo, self.package({"coastlink/engine.py": b"new", "coastlink/new.py": b"x"}))
        self.assertEqual((self.repo / "coastlink" / "engine.py").read_text(), "original")
        self.assertFalse((self.repo / "coastlink" / "new.py").exists())

    def test_link_target_refused_before_backup(self):
        outside = Path(self.temp.name) / "outside.py"
        outside.write_text("private")
        link = self.repo / "coastlink" / "linked.py"
        try:
            os.symlink(outside, link)
        except OSError:
            self.skipTest("this Windows account cannot create symlinks")
        with self.assertRaisesRegex(update_apply.UpdateError, "link or junction"):
            update_apply.apply_update(self.repo, self.package({"coastlink/linked.py": b"new"}))
        self.assertEqual(outside.read_text(), "private")
        self.assertFalse(update_apply.backups_root(self.repo).exists())

    def test_non_zip_or_bad_manifest_has_readable_error(self):
        path = self.repo / "bad.zip"
        path.write_bytes(b"not a zip")
        with self.assertRaisesRegex(update_apply.UpdateError, "complete CoastLink update ZIP"):
            update_apply.read_archive(path)
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr(update_apply.MANIFEST, "[]")
        with self.assertRaisesRegex(update_apply.UpdateError, "checksum list is invalid"):
            update_apply.read_archive(path)


class ReleaseUrlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = Path(__file__).resolve().parents[1] / "launcher" / "release.py"
        spec = importlib.util.spec_from_file_location("coastlink_release_test", path)
        cls.release = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.release)

    def test_real_github_repo_builds_versioned_download_base(self):
        self.assertEqual(self.release.release_base_url("", "owner/CoastLink", "0.6.1"),
                         "https://github.com/owner/CoastLink/releases/download/v0.6.1/")

    def test_missing_or_placeholder_repo_is_not_signed(self):
        for base, repo in (("", ""), ("https://github.com/OWNER/REPO/releases/download/v0.6.1/", ""), ("http://example/release", "")):
            with self.assertRaises(ValueError):
                self.release.release_base_url(base, repo, "0.6.1")

    def test_explicit_offline_release_has_signed_digest_but_no_fake_url(self):
        base = self.release.release_base_url("", "", "0.6.1", offline=True)
        feed = self.release.release_feed("0.6.1", ["Local test"], "CoastLink-0.6.1-update.zip", b"archive bytes", base)
        self.assertTrue(feed["offline"])
        self.assertEqual(feed["package"]["url"], "")
        self.assertEqual(feed["package"]["size"], len(b"archive bytes"))
        self.assertEqual(feed["package"]["sha256"], hashlib.sha256(b"archive bytes").hexdigest())
        self.assertNotIn("OWNER/REPO", json.dumps(feed))

    def test_offline_mode_cannot_accidentally_publish_a_remote_url(self):
        with self.assertRaisesRegex(ValueError, "not both"):
            self.release.release_base_url("https://example/release/", "", "0.6.1", offline=True)
        with self.assertRaisesRegex(ValueError, "not both"):
            self.release.release_base_url("", "owner/CoastLink", "0.6.1", offline=True)

    def test_packager_excludes_private_configuration_and_compressed_game_files(self):
        with tempfile.TemporaryDirectory() as folder:
            repo = Path(folder)
            target = repo / "launcher" / "src-tauri" / "target" / "release"
            target.mkdir(parents=True)
            (target / "coastlink.exe").write_bytes(b"test app")
            (target / "WebView2Loader.dll").write_bytes(b"test loader")
            for name in ("coastlink/allowed.py", "coastlink/private.key", "coastlink/game.nsz", "coastlink/.env",
                         "config/update.json", "launcher/update_source.json"):
                path = repo / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"test fixture")
            with patch.object(self.release, "REPO", repo), patch.object(self.release, "TARGET", target), \
                    patch.object(self.release, "tracked", return_value=["config/update.json"]):
                files = self.release.repo_files()
            self.assertIn("coastlink/allowed.py", files)
            self.assertIn("launcher/update_source.json", files)
            for refused in ("coastlink/private.key", "coastlink/game.nsz", "coastlink/.env", "config/update.json"):
                self.assertNotIn(refused, files)


if __name__ == "__main__":
    unittest.main()
