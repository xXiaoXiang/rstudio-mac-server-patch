#!/usr/bin/env python3
"""Optional developer checks for macOS Server administration safeguards.

These checks do not change macOS accounts or /etc. Run explicitly when changing
administration behavior; they are not a build, packaging, or installation step.
"""
import hashlib
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
ADMIN = ROOT / "src/cpp/server/extras/admin"
CONTROL = Path(os.environ.get("RSTUDIO_SERVER_CONTROL", str(
    ROOT / "build-macos-server/src/cpp/server/extras/macos/RStudioServer.app/Contents/MacOS/RStudioServer")))


class AdministrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="rstudio admin ")
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.bin = self.directory / "bin"
        self.bin.mkdir()
        for name in ("rstudio-server-users", "rstudio-server-install"):
            shutil.copyfile(ADMIN / (name + ".mac"), self.bin / name)

    def shell(self, body, helper="rstudio-server-users"):
        # The installed scripts have source guards, so tests exercise their
        # actual functions while substituting only privileged OS operations.
        return subprocess.run(["/bin/bash"], text=True, capture_output=True,
                              input="source " + shlex.quote(str(self.bin / helper)) +
                                    "\nset +e\n" + body + "\n")

    def test_account_names_cannot_escape_directory_records(self):
        for name in ("../admin", "a/b", "-root", "AUser", "a\nadmin", "a" * 32, ""):
            with self.subTest(name=name):
                result = self.shell("validateUserName " + shlex.quote(name))
                self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.shell("validateUserName rstudio_alice").returncode, 0)

    def test_existing_home_and_symlink_are_never_adopted(self):
        home = self.directory / "existing home"
        home.mkdir()
        sentinel = home / "keep"
        sentinel.write_text("private data")
        symlink = self.directory / "linked home"
        symlink.symlink_to(home)
        for path in (home, symlink):
            result = self.shell("validateHome " + shlex.quote(str(path)))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("already exists", result.stderr)
        self.assertEqual(sentinel.read_text(), "private data")

    def test_relative_and_ambiguous_homes_are_rejected(self):
        for path in ("relative/home", "/Users/", "/Users/.", "/Users/..", "/Users/a\nb"):
            result = self.shell("validateHome " + shlex.quote(path))
            self.assertNotEqual(result.returncode, 0)

    def test_other_users_cannot_control_storage_ancestry(self):
        result = self.shell("secureDirectory " + shlex.quote(str(self.directory)))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("root-owned", result.stderr)

    def test_retired_uid_is_not_reused(self):
        state = self.directory / "state"
        state.mkdir()
        (state / "last-uid").write_text("9000\n")
        result = self.shell("USER_STATE=" + shlex.quote(str(state)) + '''
directoryService() { printf 'root 0\nalice 501\n'; }
allocateUid || exit $?
printf '%s\n' "$ACCOUNT_UID"
allocateUid || exit $?
printf '%s\n' "$ACCOUNT_UID"
''')
        self.assertEqual(result.returncode, 0, result.stderr)
        first, second = map(int, result.stdout.splitlines())
        self.assertGreater(first, 9000)
        self.assertGreater(second, first)

    def test_identity_change_prevents_managed_user_mutation(self):
        state = self.directory / "state"
        state.mkdir()
        (state / "alice").write_text("502\noriginal-uuid\n/Users/RStudioHomes/alice\n")
        result = self.shell("USER_STATE=" + shlex.quote(str(state)) + '''
prepareState() { :; }
userAttribute() { if [ "$2" = UniqueID ]; then echo 502; else echo replaced-uuid; fi; }
loadManagedUser alice
''')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("identity changed", result.stderr)

    def test_running_process_prevents_user_deletion(self):
        result = self.shell('''
loadManagedUser() { ACCOUNT_UID=502; }
userHasProcesses() { return 0; }
directoryService() { echo UNEXPECTED_MUTATION; }
deleteUser alice
''')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("running processes", result.stderr)
        self.assertNotIn("UNEXPECTED_MUTATION", result.stdout)

    def test_uninstall_preserves_modified_and_unmanaged_configuration(self):
        state = self.directory / "state"
        state.mkdir()
        config = self.directory / "rserver.conf"
        original = "www-address=127.0.0.1\n"
        config.write_text(original)
        marker = state / "config-sha256"
        marker.write_text(hashlib.sha256(original.encode()).hexdigest() + "\n")
        config.write_text(original + "www-port=8788\n")
        result = self.shell("STATE=" + shlex.quote(str(state)) + "\nremoveInstalledFile " +
                            shlex.quote(str(config)) + " config-sha256", "rstudio-server-install")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(config.exists())
        self.assertIn("Preserving", result.stdout)
        # No marker: a pre-existing file is preserved even if contents match defaults.
        result = self.shell("STATE=" + shlex.quote(str(state)) + "\nremoveInstalledFile " +
                            shlex.quote(str(config)) + " config-sha256", "rstudio-server-install")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(config.exists())

    def test_uninstall_removes_only_unchanged_installer_file(self):
        state = self.directory / "state"
        state.mkdir()
        config = self.directory / "rserver.conf"
        config.write_text("www-address=127.0.0.1\n")
        (state / "config-sha256").write_text(hashlib.sha256(config.read_bytes()).hexdigest() + "\n")
        result = self.shell("STATE=" + shlex.quote(str(state)) + "\nremoveInstalledFile " +
                            shlex.quote(str(config)) + " config-sha256", "rstudio-server-install")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(config.exists())

    def test_uninstall_refuses_replaced_service_identity(self):
        state = self.directory / "state"
        state.mkdir()
        (state / "service-account").write_text("499\n499\ngroup-uuid\nold-user-uuid\n")
        result = self.shell("STATE=" + shlex.quote(str(state)) + '''
directoryService() { if [ "$1" = -delete ]; then echo UNEXPECTED_MUTATION; fi; }
attribute() { if [ "$2" = UniqueID ]; then echo 499; else echo new-user-uuid; fi; }
removeServiceAccount
''', "rstudio-server-install")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("identity changed", result.stderr)
        self.assertNotIn("UNEXPECTED_MUTATION", result.stdout)

    def test_existing_service_account_is_preserved_and_not_claimed(self):
        state = self.directory / "state"
        state.mkdir()
        result = self.shell("STATE=" + shlex.quote(str(state)) + '''
directoryService() { if [ "$1" = -create ]; then echo UNEXPECTED_MUTATION; fi; }
attribute() { echo 499; }
createServiceAccount
''', "rstudio-server-install")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Preserving existing service account", result.stdout)
        self.assertNotIn("UNEXPECTED_MUTATION", result.stdout)
        self.assertFalse((state / "service-account").exists())

    def test_normal_user_cannot_be_adopted_as_service_account(self):
        for uid in (0, 501):
            with self.subTest(uid=uid):
                result = self.shell('''
directoryService() { if [ "$1" = -create ]; then echo UNEXPECTED_MUTATION; fi; }
attribute() { echo ''' + str(uid) + '''; }
createServiceAccount
''', "rstudio-server-install")
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("not a system account", result.stderr)
                self.assertNotIn("UNEXPECTED_MUTATION", result.stdout)

    def test_network_edit_preserves_other_settings_and_comments(self):
        template = (ADMIN / "rstudio-server.mac.in").read_text().split('case "$1" in', 1)[0]
        config = self.directory / "rserver.conf"
        config.write_text("# www-address=example\nauth-none=0\nrsession-which-r=/opt/R/bin/R\n"
                          " www-address = 127.0.0.1\nwww-port=8787\nwww-port=9999\n")
        result = subprocess.run(["/bin/bash"], input=template + "\nrenderNetworkConfig " +
                                shlex.quote(str(config)) + " 0.0.0.0 8788\n", text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("auth-none=0\nrsession-which-r=/opt/R/bin/R\n", result.stdout)
        self.assertIn("# www-address=example", result.stdout)
        self.assertEqual(result.stdout.count("www-port="), 1)
        self.assertTrue(result.stdout.endswith("www-address=0.0.0.0\nwww-port=8788\n"))

    @unittest.skipUnless(CONTROL.exists(), "build the native controller first")
    def test_native_network_validation(self):
        for address, port, accepted in (("127.0.0.1", "8787", True), ("0.0.0.0", "1", True),
                ("::1", "65535", True), (":::1", "8787", False), ("999.0.0.1", "8787", False),
                ("", "8787", False), ("127.0.0.1", "1١", False),
                ("127.0.0.1\nauth-none=1", "8787", False), ("127.0.0.1", "65536", False),
                ("127.0.0.1", "0", False), ("127.0.0.1", "8787;touch /tmp/invalid", False)):
            with self.subTest(address=address, port=port):
                result = subprocess.run([str(CONTROL), "--validate-network", address, port], capture_output=True)
                self.assertEqual(result.returncode == 0, accepted, result.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
