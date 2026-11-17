# Native RStudio Server on macOS

This patch series adds a native Server installation for macOS 13 or newer. It installs
as **RStudioServer.app**. Electron Desktop continues to install as **RStudio.app**;
the two applications can coexist. Server's browser IDE uses the matching
bundled rserver and rsession binaries.

The installable output is a **PKG containing RStudioServer.app**. The app includes
separate running/startup controls, Admin Info, and a system uninstaller.
For release branches, version metadata and future rebases, see
[Maintaining the macOS Server patches](MAINTAINING-SERVER.md).

## Build on Apple Silicon

Install the Xcode Command Line Tools and native arm64 Homebrew, then run these
commands from the patched RStudio source root. The patch repository README
describes fetching and applying the patches first. All dependency commands run as your normal
Mac account and request sudo only when necessary.

    cd dependencies/osx
    ./install-dependencies-osx --arch=arm64
    cd ../..
    export JAVA_HOME=/opt/homebrew/opt/openjdk@17
    cmake -S . -B build-macos-server -G Ninja \
      -DRSTUDIO_TARGET=Server \
      -DCMAKE_BUILD_TYPE=Release \
      -DCMAKE_OSX_ARCHITECTURES=arm64 \
      -DCMAKE_INSTALL_PREFIX=/Applications \
      -DGWT_BUILD=ON
    cmake --build build-macos-server
    sudo cmake --install build-macos-server

The dependency installer defaults to the host architecture, including on CI.
Intel Homebrew, osx-64 dependencies and Rosetta are not required. Universal
Desktop dependencies remain an explicit opt-in. The normal macOS Desktop
packaging scripts still build Electron; they do not package Server.

The optional sccache installer falls back to ~/opt/bin if /usr/local/bin is
not writable. This is intentional; the binary does not need moving to /opt/bin.
To use it, add the following to ~/.zprofile and open a new terminal:

    export PATH="$HOME/opt/bin:$PATH"

The Server can be built without sccache. To enable it explicitly, configure
with -DSCCACHE_ENABLED=ON after adding its directory to PATH.

The complete Server build includes the compiled GWT browser UI. Using
GWT_BUILD=OFF is useful for configure diagnostics but does not produce a complete
browser IDE on a clean checkout. The development rserver-dev launcher explicitly
passes auth-none=1 and is unsuitable for testing authenticated multi-user access.

## Build the installer

After the complete Server build, run:

    bash package/osx-server/build-pkg.sh build-macos-server

This produces build-macos-server/RStudioServer-arm64.pkg. It stages the complete
app, checks its arm64 executables, signs the app, and packages the installation
scripts. The default is an ad hoc signed development app in an unsigned PKG for
local testing. Distribution requires Developer ID signing and notarization.
RSTUDIO_MACOS_SIGN_IDENTITY and RSTUDIO_MACOS_INSTALLER_IDENTITY select signing
identities; notarization is a separate release step.

R is installed separately; the PKG does not install R or Homebrew.
Quit active Server R sessions and the RStudioServer control app before
installing/upgrading. Closing a browser tab alone does not quit an R session.
Install the PKG using macOS Installer or:

    sudo /usr/sbin/installer -pkg build-macos-server/RStudioServer-arm64.pkg -target /

The package installs only on the running macOS startup volume. Upgrades preserve
existing configuration and restore an enabled startup registration; macOS may
request approval again when a development signature changes.

## Install and approve startup

The Server application contains a native control window and a bundled system
LaunchDaemon. It uses Apple's SMAppService API, available since macOS 13.
The daemon runs before graphical login and rserver can launch sessions under
the authenticated accounts' UIDs. Quitting the control window does not stop it.

1. The PKG prepares the system automatically. For a manual cmake --install,
   install the complete app in /Applications, then run:

       sudo /Applications/RStudioServer.app/Contents/Resources/app/bin/rstudio-server install-service

   When /etc/rstudio/rserver.conf is absent, install-service creates it with:

       www-address=127.0.0.1
       auth-none=0
       auth-validate-users=1

   Existing configuration is preserved. Set rsession-which-r there to choose a
   particular Conda or other R installation.

   Installation creates a dedicated rstudio-server user and group with an unused
   system UID/GID below 500, a disabled password, /usr/bin/false shell, /var/empty
   home, and IsHidden=1. This is the daemon's service identity, separate from the
   accounts that sign in to RStudio. launchd starts rserver with root authority;
   rserver uses its service identity and restores privileges when launching
   sessions as authenticated users. Existing valid service accounts are preserved.
   The earlier development installation omitted this account and used upstream's
   root fallback; running install-service now provisions it for the next restart.

2. Sign the completed app bundle before registration. SMAppService requires a
   valid code signature. A distributed build needs signing with the appropriate
   Developer ID identity and notarization. For development in the VM, an ad hoc
   signature can be tried on the completed bundle:

       sudo codesign --force --deep --sign - /Applications/RStudioServer.app

   Ad hoc signing and registration were validated in the development VM.
   Distributed Developer ID signing and notarization remain separate release
   steps; compiling the control window alone does not validate registration.

3. Open /Applications/RStudioServer.app and choose **Enable Auto Startup**.
   After registration, if macOS reports approval is required, the app
   prompts to open **System Settings > Login Items**. Approve RStudio Server
   under background items; the precise pane name varies by macOS release.
   Approval is controlled by macOS and the administrator.

   A system LaunchDaemon appears under background items, not **Open at Login**
   (登录时打开). Open at Login is for apps opened after a graphical login;
   Server's background service is configured to start before graphical login.

4. Return to the app to see its running and startup states. Startup registration
   is separate from the health of the HTTP service. Open
   http://127.0.0.1:8787 and sign in using an eligible Mac account.

The LaunchDaemon stays in the app's Contents/Library/LaunchDaemons directory.
It is registered through SMAppService rather than copied into
/Library/LaunchDaemons. The daemon runs in the foreground under launchd,
requires authentication and system-user validation, and restarts after failure.
Its PATH includes the standard native Homebrew locations because launchd does
not read your shell profile. Set rsession-which-r explicitly to select a
particular Conda or other R installation.
The administrator can disable it in the app or in System Settings.

The installed admin script supports status, start, stop, restart, check-config,
and the existing session commands. Start, stop and restart require administrator
authorization. Install-service prepares system files without enabling startup;
uninstall-service reverses installer-owned system setup while retaining the app.

## Configuration and service controls

The control app displays **RStudio Server Status: Running / Dead** and
**RStudio Server Auto Startup: Enabled / Disabled**. Only the state words use
green for running/enabled and red for dead/disabled; the prefixes keep the
normal label color (black in light mode). Running means the app's rserver process
exists; it does not guarantee that HTTP requests or R sessions are healthy.
The status refreshes every two seconds. **Start Server / Stop Server** changes
the current service state. **Enable Auto Startup / Disable Auto Startup** changes
macOS background startup registration. Enabling startup also starts the service;
disabling startup unregisters and stops it. A manual start with startup disabled
runs until stopped or the Mac restarts.

Open **Admin Info → Open /etc/rstudio in Finder** to find rserver.conf and any
rsession.conf you create. Editing these root-owned files requires administrator
privileges. For example, use your preferred editor or Terminal:

    sudo /usr/bin/nano /etc/rstudio/rserver.conf

Set www-address and www-port in rserver.conf. 127.0.0.1 limits connections to
this Mac; 0.0.0.0 listens on all IPv4 interfaces. Stop and start the service after
saving to load the latest configuration. The command-line equivalent is:

    sudo /Applications/RStudioServer.app/Contents/Resources/app/bin/rstudio-server restart

The optional configure-network command validates a numeric listen address/port,
preserves other settings, and saves the previous rserver.conf before replacing it:

    sudo /Applications/RStudioServer.app/Contents/Resources/app/bin/rstudio-server configure-network 127.0.0.1 8787

## Access to macOS protected folders

macOS privacy controls can deny a session access to Documents, Desktop and
Downloads even when the authenticated UID owns those folders. A graphical login
is not required to initialize the user's home. In the tested VM, granting
**RStudioServer.app** access in **System Settings → Privacy & Security → Full
Disk Access**, then reconnecting the session, allowed access to protected folders.
This grants broad privacy access to the trusted Server app; ordinary Unix file
ownership and permissions still apply. Granting this access is an administrator's
choice. For projects that do not need protected folders, use a private directory
such as ~/Rprojects or a custom account home on your chosen storage.

## Authentication and account preferences

The shipped /etc/pam.d/rstudio profile uses macOS pam_opendirectory.so for both
password authentication and account-policy validation. no_check_shell allows
RStudio-only accounts with /usr/bin/false as their login shell; home-directory
and enabled-account checks remain in effect. Disabling an account or removing
its usable password also prevents this password-based web authentication.

Normal local accounts begin at UID 501. The automatic minimum UID is therefore
501 on macOS, while Linux keeps its existing detection and fallback. An
administrator can override auth-minimum-user-id and restrict access using
auth-required-user-group.

Account visibility is independent of Server support. Administrators may choose
visible users, hidden users, or dedicated RStudio-only users. IsHidden affects
login-window presentation; it is not an authentication or isolation boundary.
A non-login shell alone should not be treated as a complete policy forbidding
all graphical or remote access.

### Create a hidden RStudio user with an explicit home

Open **Admin Info** in the app, enter the account name and home directory,
choose whether it is hidden, then copy the **Create User** command into Terminal.
The helper uses macOS utilities and does not require Python or Homebrew. Example:

    sudo /bin/mkdir -m 755 /Users/RStudioHomes
    sudo /Applications/RStudioServer.app/Contents/Resources/app/bin/rstudio-server create-user rstudio_alice --home /Users/RStudioHomes/rstudio_alice --hidden

The storage parent must already exist; mkdir is needed only once. Account
creation securely prompts for a password in Terminal. Sign in to the Server with
rstudio_alice and that password. The account has its own UID, staff primary group,
/usr/bin/false login shell, and a private 0700 home. Use --visible instead of
--hidden, or omit both, for a visible account. No existing account or home is
adopted, overwritten or recursively chowned.

Storage paths must be root-owned and must not be group/world-writable, including
their resolved ancestors. For an external volume, mount it first and enable file
ownership. An administrator can prepare a dedicated APFS volume, for example:

    sudo /usr/sbin/diskutil enableOwnership /Volumes/RStudioData
    sudo /usr/sbin/chown root:wheel /Volumes/RStudioData
    sudo /bin/chmod 755 /Volumes/RStudioData
    sudo /bin/mkdir -m 755 /Volumes/RStudioData/RStudioHomes
    sudo /Applications/RStudioServer.app/Contents/Resources/app/bin/rstudio-server create-user rstudio_alice --home /Volumes/RStudioData/RStudioHomes/rstudio_alice --hidden

Use the actual mounted volume name. The volume must be mounted and unlocked
before the user starts an R session; a login-screen hidden account does not
automatically unlock external storage.

Choose **Change Visibility** or **Delete User** in the help window for their
individual commands. Only accounts created by this helper can be modified by it:

    sudo /Applications/RStudioServer.app/Contents/Resources/app/bin/rstudio-server set-user-visibility rstudio_alice visible
    sudo /Applications/RStudioServer.app/Contents/Resources/app/bin/rstudio-server set-user-visibility rstudio_alice hidden
    sudo /Applications/RStudioServer.app/Contents/Resources/app/bin/rstudio-server delete-user rstudio_alice

Quit all of that user's sessions before deletion. Deletion refuses active
processes and changed account identities. It preserves the home and changes its
top directory to root:wheel, mode 0700, so another account cannot inherit access
through UID reuse. The helper retains its UID allocation history under the
root-only /var/db/rstudio-server/accounts directory. Passwords are never supplied
in command arguments. Server group restrictions, if configured, still apply.

Each session uses its authenticated system account. Private home directories
must have restrictive ownership and permissions. Directory Service's
NFSHomeDirectory may point to an administrator-selected directory on another
volume, provided the volume enforces ownership, is mounted when needed, and is
accessible to the account. A shared HOME value without distinct UIDs would not
provide this separation.

The old Flask portal and its Conda management routes have not been migrated by
these source changes. Building the Server does not itself add a portal database
or a per-user Conda selection interface.

## Uninstall and retained data

To replace a development build with a release build, install the new PKG over
the existing app after quitting Server sessions and the control app. A full
uninstall is optional for this upgrade; it can remove unchanged default settings
and unregister startup, so startup may need to be enabled again after reinstall.

Choose **Uninstall Server** in Admin Info for the removal command, or run:

    sudo /Applications/RStudioServer.app/Contents/Resources/app/bin/uninstall-rstudio-server

First choose Session > Quit Session in every active Server session, then quit
the RStudioServer control app. Closing browser tabs alone does not quit sessions.
The uninstaller unregisters/stops the LaunchDaemon,
removes only the service user/group created by this installer (checking their
identities), removes unchanged installer-created PAM/default configuration,
removes empty installer-created directories, forgets the package receipt and
removes /Applications/RStudioServer.app. It preserves pre-existing or modified
configuration, end-user accounts and homes, logs, database, backups and account
management records. Retained standard Server data/log directories become
root-owned/private before the installer-owned service identity is removed.
On reinstall rserver assigns its database/runtime ownership to its service user.

Removing an end-user account is a separate explicit delete-user command. Use it
before uninstalling the app if desired. User data is never recursively deleted.
Dragging the app into Trash cannot execute uninstall scripts on macOS; use the
uninstaller first. Uninstalling does not require changing RStudio Desktop.
R, Homebrew and source-build dependencies are separate from the app installation
and remain installed.

## Optional developer validation

The following three scripts are optional developer tools. They are never invoked
by the dependency installer, CMake build, PKG installer, or application, and are
not installed in RStudioServer.app. Ordinary builds, upgrades, rebases, and
dependency-only changes do not require running them. Run them deliberately when
investigating changes to the behavior they cover; do not repeat them for every
configure/build/package step.

- test-server-integration.py checks layout and service integration in temporary
  directories, without changing the installed system service.
- test-server-administration.py checks administration safeguards using substituted
  system operations, without creating real accounts or changing /etc.
- probe-server-accounts.py exercises real PAM, accounts and optionally HTTP/R
  sessions. Account modes create disposable accounts and require an explicit
  administrator decision to run them; --check-http only checks anonymous HTTP.

Optional dependency-light checks:

    python3 dependencies/osx/test-server-integration.py
    python3 dependencies/osx/test-server-administration.py

The native control app can be compiled independently of the RStudio dependencies:

    cmake -S src/cpp/server/extras/macos -B build-server-control -G Ninja \
      -DCMAKE_OSX_ARCHITECTURES=arm64 -DCMAKE_OSX_DEPLOYMENT_TARGET=13.0
    cmake --build build-server-control

This standalone app lacks the Server binaries and service plist. It is a compile
check, not an installable service.

The account probe requires sudo and creates two disposable local accounts with
private homes and non-login shells. It checks real Open Directory PAM acceptance
and rejection, UID and HOME switching without a GUI session, private-file access
in both directions, and cross-user process signalling. It removes its accounts,
private PAM profile, and temporary files afterward.

    sudo /usr/bin/python3 dependencies/osx/probe-server-accounts.py

To optionally check the compiled Server's authentication helper, run:

    sudo /usr/bin/python3 dependencies/osx/probe-server-accounts.py \
      --pam-helper build-macos-server/src/cpp/server/pam/rserver-pam

For an optional live HTTP authentication and R session check after installing
and enabling startup, run:

    sudo /usr/bin/python3 dependencies/osx/probe-server-accounts.py \
      --pam-helper /Applications/RStudioServer.app/Contents/Resources/app/bin/rserver-pam \
      --server-url http://127.0.0.1:8787

This signs in with generated credentials using the browser's encrypted login
protocol, verifies rejection of an incorrect password, and starts two real R
sessions. It checks the authenticated UID and HOME, native arm64 R execution,
and cross-user private-file access from R. It stops only the disposable accounts'
sessions before removing those accounts and homes. The running Server may retain
its normal database and authentication records for the disposable usernames.
The test does not change the installed configuration or existing accounts.

The anonymous sign-in check alone does not require administrator privileges:

    /usr/bin/python3 dependencies/osx/probe-server-accounts.py --check-http

Add --hidden to set the temporary accounts' IsHidden attribute as well. The probe
does not use or log an existing account's password. It prints the paths and
account names so any interrupted run can be inspected.

On 2026-11-17 the account probe passed in the arm64 macOS VM, including valid
and invalid password tests through the newly built rserver-pam executable.
Account isolation and cleanup passed. The five dependency-light regression
tests passed.

The full Server build succeeded, including the GWT browser UI, rserver,
rsession, rserver-pam and the control application. The native C++ unit suite
was disabled for this build. Installation into a workspace staging directory
succeeded; the complete staged RStudioServer.app passed ad hoc codesign
verification. The staged server's --check-config accepted the bundled
configuration and detected Homebrew R 4.6.2.

System installation and SMAppService registration succeeded. The control app
reports startup enabled, and launchctl confirms a running system LaunchDaemon
managed by ServiceManagement. Anonymous HTTP requests redirect to the sign-in
page, the sign-in form includes a CSRF cookie, and an encrypted login for a
nonexistent account is rejected.

The full HTTP/session probe also passed for two disposable non-login accounts:
valid passwords were accepted and incorrect passwords rejected through both
the installed rserver-pam and the encrypted HTTP sign-in endpoint. Real
rsession processes initialized as the authenticated accounts. R console code
ran natively on arm64, with the correct UID and HOME, and could neither read
nor write the other account's private file. Both sessions coexisted without
graphical login. Account, session, PAM-profile and temporary-file cleanup
completed successfully.

The administrator also confirmed successful manual browser sign-in at
127.0.0.1:8787. The updated native settings/account-help controller compiles, and
14 administration safeguards plus the five integration checks pass. The tests
do not provision real persistent accounts or change /etc.

The administrator confirmed successful installation of the development PKG and
that the updated settings/account-help buttons appear and work. The uninstaller,
interactive account helper, reboot behavior and release signing/notarization
still require explicit runtime validation. The earlier successful HTTP/session
probe used the development installation's root fallback; repeating it with the
new dedicated service identity remains a separate check.
