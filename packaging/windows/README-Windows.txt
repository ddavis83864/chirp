CHIRP for Windows (x86-64) -- Community Edition
=================================================

This is the Windows x86-64 community build of CHIRP, version 1.12.0.

It corresponds to the same verified application source used by this
fork's Linux AppImage release (appimage-v1.12.0) and macOS Community
Edition release (macos-community-v1.12.0) -- see build-provenance.json
in this distribution for the exact source commit and how that was
verified.

This build is distributed from the ddavis83864/chirp fork on GitHub:
    https://github.com/ddavis83864/chirp

It is NOT necessarily an official upstream CHIRP release. Upstream CHIRP
is at https://chirpmyradio.com -- check there too if you want the
canonical project.

--------------------------------------------------------------------
UNSIGNED COMMUNITY PRERELEASE
--------------------------------------------------------------------

CHIRP.exe and the installer are NOT signed with a code-signing
certificate. Windows SmartScreen will very likely show an "Unknown
publisher" or "Windows protected your PC" warning the first time you run
either one. This is expected for any unsigned Windows application -- it
is not a sign that something is wrong with this specific download.

To proceed after verifying your download (see below):
  1. If SmartScreen blocks the app, click "More info".
  2. Click "Run anyway".

Do NOT disable Windows Defender or SmartScreen system-wide to work
around this. That removes protection for your whole PC, not just this
one app, and is never necessary just to run an unsigned program you've
verified yourself.

A future release may add proper Authenticode code signing -- see this
distribution's build-provenance.json "code_signing" field for the
current status.

--------------------------------------------------------------------
USING THE PORTABLE ZIP
--------------------------------------------------------------------

  1. Download CHIRP-windows-v1.12.0-x86_64-portable.zip
  2. Extract it anywhere (your Desktop, a USB drive, etc.) -- no
     installation, no admin rights needed.
  3. Open the extracted folder and double-click CHIRP.exe.

Nothing is written outside your normal user profile; CHIRP stores its
settings the same way whether you use the portable ZIP or the installer
(see "Where CHIRP stores your configuration" below).

--------------------------------------------------------------------
USING THE INSTALLER
--------------------------------------------------------------------

  1. Download CHIRP-windows-v1.12.0-x86_64-setup.exe
  2. Run it. It installs per-user by default -- no administrator prompt,
     no elevation required -- to:
         %LOCALAPPDATA%\Programs\CHIRP
  3. It adds a Start Menu shortcut, and offers an optional Desktop
     shortcut (unchecked by default).
  4. To uninstall later, use Windows Settings > Apps, or the Start Menu
     shortcut in the CHIRP group. Uninstalling removes only the
     installed application files -- your saved radio images, CSV
     exports, and CHIRP settings are never touched by uninstall.

Silent install/uninstall (for scripted deployment) are supported via the
standard Inno Setup switches, e.g.:
    CHIRP-windows-v1.12.0-x86_64-setup.exe /VERYSILENT /SUPPRESSMSGBOXES

--------------------------------------------------------------------
PYTHON IS BUNDLED -- NOTHING ELSE TO INSTALL
--------------------------------------------------------------------

Both the portable ZIP and the installer contain a complete, bundled
Python runtime and all of CHIRP's Python dependencies (wxPython,
pyserial, etc.). You do not need Python installed separately, and this
build does not touch any Python installation you may already have.

--------------------------------------------------------------------
USB SERIAL CABLE DRIVERS -- NOT INCLUDED
--------------------------------------------------------------------

This build does NOT include or install USB-to-serial chip drivers
(FTDI, Prolific, WCH/CH340, Silicon Labs CP210x, or any other). Most
radio programming cables use one of these chips.

  - Windows Update installs many of these automatically once you plug
    the cable in.
  - If your cable isn't recognized, get the driver from the cable/radio
    manufacturer's site, or the chipset manufacturer directly (search
    for the chip name printed on or near the cable's USB connector).
  - Avoid third-party driver download sites.

Once installed, the cable appears as a COM port in Device Manager;
select that port in CHIRP's Radio > Download from radio / Upload to
radio dialog.

--------------------------------------------------------------------
VERIFYING YOUR DOWNLOAD (SHA-256)
--------------------------------------------------------------------

This distribution's SHA256SUMS file lists the SHA-256 hash of every
release asset. To verify what you downloaded, in PowerShell:

    Get-FileHash CHIRP-windows-v1.12.0-x86_64-portable.zip -Algorithm SHA256

Compare the printed hash against the matching line in SHA256SUMS. They
must match exactly. A matching hash confirms the file is byte-for-byte
identical to what this project's build produced -- it confirms file
integrity, not that the software is inherently safe to run; only
download CHIRP from the official GitHub releases page for this
repository, never a third-party mirror.

--------------------------------------------------------------------
BUILD PROVENANCE
--------------------------------------------------------------------

build-provenance.json (included in this distribution) records the exact
source commit, build tool versions, Windows runner image, and workflow
run that produced these artifacts, along with the Linux and macOS
v1.12.0 release source commits it was cross-checked against. See that
file if you need to confirm exactly what was built.

--------------------------------------------------------------------
WHERE CHIRP STORES YOUR CONFIGURATION
--------------------------------------------------------------------

CHIRP stores its settings and configuration in your normal Windows user
profile (the same location whether you run the portable ZIP or the
installed version), so upgrading, moving the portable folder, or
reinstalling does not lose your settings. This is CHIRP's standard,
unmodified default location -- this Windows build does not redirect it
anywhere unusual.

--------------------------------------------------------------------
REPORTING AN ISSUE
--------------------------------------------------------------------

File issues at: https://github.com/ddavis83864/chirp/issues

Please include:
  - Whether you used the portable ZIP or the installer.
  - Your Windows version (Settings > System > About).
  - The exact CHIRP version (Help > About inside CHIRP), which also
    shows the bundled Python and wxPython versions.
  - The source commit SHA from build-provenance.json.
  - What you expected to happen vs. what actually happened.
  - If CHIRP crashed or wouldn't start, attach the debug log (Help >
    Open debug log inside CHIRP, if it got far enough to open; otherwise
    note that it wouldn't start at all).
