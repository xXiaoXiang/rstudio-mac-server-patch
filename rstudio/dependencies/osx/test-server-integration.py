#!/usr/bin/env python3
"""Optional developer integration checks; no system mutations.

Run explicitly when investigating macOS Server integration changes. These checks
are not part of dependency installation, the build, packaging, or the application.
"""
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
CMAKE = os.environ.get("CMAKE", shutil.which("cmake") or str(ROOT / ".venv/bin/cmake"))


class ServerIntegrationTests(unittest.TestCase):
    def test_install_layout(self):
        for target, expected_bin, install_prefix in (
            ("Server", "RStudioServer.app/Contents/Resources/app/bin", None),
            ("Electron", "RStudio.app/Contents/Resources/app/bin", None),
            ("Server", "RStudioServer.app/Contents/Resources/app/bin", "/tmp/custom-prefix"),
        ):
            with self.subTest(target=target, prefix=install_prefix), tempfile.TemporaryDirectory() as tmp:
                source = Path(tmp) / "CMakeLists.txt"
                source.write_text('''cmake_minimum_required(VERSION 3.25)
project(LayoutCheck LANGUAGES NONE)
include("${REPO}/cmake/init.cmake")
include("${REPO}/cmake/globals.cmake")
if(NOT RSTUDIO_INSTALL_BIN STREQUAL EXPECTED_BIN)
  message(FATAL_ERROR "Unexpected binary layout: ${RSTUDIO_INSTALL_BIN}")
endif()
if(NOT CMAKE_INSTALL_PREFIX STREQUAL EXPECTED_PREFIX)
  message(FATAL_ERROR "Unexpected prefix: ${CMAKE_INSTALL_PREFIX}")
endif()
''')
                command = [CMAKE, "-S", tmp, "-B", tmp + "/build",
                    "-DREPO=" + str(ROOT), "-DRSTUDIO_TARGET=" + target,
                    "-DEXPECTED_BIN=" + expected_bin,
                    "-DEXPECTED_PREFIX=" + (install_prefix or "/Applications")]
                if install_prefix:
                    command.append("-DCMAKE_INSTALL_PREFIX=" + install_prefix)
                result = subprocess.run(command,
                    capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_launchd_policy(self):
        path = ROOT / "src/cpp/server/extras/launchd/com.rstudio.launchd.rserver.plist.in"
        plist = plistlib.loads(path.read_bytes())
        self.assertIn("--server-daemonize=0", plist["ProgramArguments"])
        self.assertIn("--auth-none=0", plist["ProgramArguments"])
        self.assertIn("--auth-validate-users=1", plist["ProgramArguments"])
        self.assertTrue(plist["RunAtLoad"])
        self.assertEqual(plist["KeepAlive"], {"SuccessfulExit": False})
        # launchd starts with root authority, allowing rserver to switch UIDs.
        self.assertNotIn("UserName", plist)
        self.assertEqual(plist["BundleProgram"], "Contents/Resources/app/bin/rserver")
        self.assertEqual(plist["ProgramArguments"][0], "rserver")
        # A boot-time daemon does not inherit a user's Homebrew shell setup.
        self.assertIn("/opt/homebrew/bin", plist["EnvironmentVariables"]["PATH"].split(":"))

    def run_admin(self, operation, loaded=True, config_status=0, config_extra=""):
        template = (ROOT / "src/cpp/server/extras/admin/rstudio-server.mac.in").read_text()
        functions = template.split('case "$1" in', 1)[0]
        with tempfile.TemporaryDirectory(prefix="rstudio service ") as tmp:
            prefix = Path(tmp)
            (prefix / "bin").mkdir()
            executable = prefix / "bin/rserver"
            executable.write_text("#!/bin/bash\n" + config_extra + "\nexit " + str(config_status) + "\n")
            executable.chmod(0o755)
            functions = functions.replace("${CMAKE_INSTALL_PREFIX}/${RSTUDIO_INSTALL_SUPPORTING}", tmp)
            harness = functions + '''
requireRoot() { return 0; }
SERVER_CONTROL="$SERVER_PREFIX/control"
launchctl() {
 printf '%s\n' "$*" >> "$MOCK_LOG"
 if [ "$1" = print ]; then return "$MOCK_PRINT_STATUS"; fi
}
''' + operation + "\n"
            control = prefix / "control"
            control.write_text('#!/bin/bash\nprintf "control %s\\n" "$*" >> "$MOCK_LOG"\n')
            control.chmod(0o755)
            log = prefix / "calls"
            env = dict(os.environ, MOCK_LOG=str(log), MOCK_PRINT_STATUS="0" if loaded else "1")
            result = subprocess.run(["/bin/bash"], input=harness, text=True, env=env, capture_output=True)
            calls = log.read_text().splitlines() if log.exists() else []
            return result, calls

    def test_service_lifecycle(self):
        target = "system/com.rstudio.launchd.rserver"
        result, calls = self.run_admin("startServer", loaded=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls, ["control --enable-service"])
        result, calls = self.run_admin("stopServer")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls, ["control --disable-service"])
        result, calls = self.run_admin("restartServer")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls, ["print " + target, "kickstart -k " + target])
        result, calls = self.run_admin("restartServer", loaded=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls, ["print " + target, "control --enable-service"])

    def test_config_failure_prevents_start(self):
        result, calls = self.run_admin("startServer", loaded=False, config_status=42)
        self.assertEqual(result.returncode, 42)
        self.assertEqual(calls, [])

    def test_verification_preserves_arguments(self):
        result, _ = self.run_admin('verifyInstallation "argument with spaces" tail',
            config_extra="printf '<%s>\n' \"$@\"")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["<--verify-installation=1>",
            "<--server-daemonize=0>", "<argument with spaces>", "<tail>"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
