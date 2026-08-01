# Installing CHIRP for Windows (Community Edition)

Download the current release from the
[Windows Community Edition v1.13.1 release page](https://github.com/ddavis83864/chirp/releases/tag/windows-community-v1.13.1).
See [packaging/windows/README.md](../packaging/windows/README.md) for how
the Windows packaging pipeline that produces it works, or the
[Windows section of the main README](../README.md#windows) for a shorter
summary.

The CHIRP Windows Community Edition is **not signed with an Authenticode
certificate**. It is built automatically, from source, on a
GitHub-hosted Windows runner, from the exact CHIRP source commit
identified on the release page -- the same application source used for
the Linux and macOS v1.13.1 releases. Unsigned status means no
code-signing certificate has verified the publisher identity behind this
build; it does not mean the package failed any validation. Every build
goes through PyInstaller-bundle validation, a driver-registry check
running inside the frozen bundle, and a launch smoke test before being
packaged -- see the attached `build-provenance.json` on the release page
for details.

## 1. Choose portable or installed

Both contain the exact same validated application bundle -- pick
whichever suits you:

- **Portable ZIP** (`CHIRP-windows-v<version>-x86_64-portable.zip`) --
  extract anywhere and run `CHIRP.exe` directly. No installation, no
  administrator rights, nothing written outside your normal user
  profile.
- **Installer** (`CHIRP-windows-v<version>-x86_64-setup.exe`) -- installs
  per-user (no administrator rights required) to
  `%LOCALAPPDATA%\Programs\CHIRP`, adds a Start Menu shortcut, and offers
  an optional Desktop shortcut.

## 2. Install from the ZIP

1. Download the portable ZIP from the official GitHub release page.
2. (Recommended) Verify the checksum -- see section 5 below.
3. Right-click the downloaded `.zip` -> **Extract All...** (or use your
   preferred archive tool).
4. Open the extracted folder and double-click `CHIRP.exe`.

## 2b. Install from the setup.exe

1. Download the installer from the official GitHub release page.
2. (Recommended) Verify the checksum -- see section 5 below.
3. Run it. It installs per-user by default -- you should **not** see a
   User Account Control (admin) prompt for the default install.
4. Follow the wizard; the optional desktop shortcut checkbox is
   unchecked by default.
5. Launch CHIRP from the Start Menu, or let the installer's "Launch
   CHIRP" checkbox do it for you at the end.

## 3. First launch (SmartScreen)

Because this build is unsigned, Windows SmartScreen may block it the
first time you try to run either `CHIRP.exe` or the installer. This is
expected, standard Windows behavior for any unsigned application -- it
is not specific to CHIRP and not a sign that something is wrong.

1. If you see "Windows protected your PC", click **More info**.
2. Click **Run anyway**.

**Do not** disable Windows Defender or SmartScreen system-wide to work
around this. Neither is necessary, and both remove protection for your
whole PC, not just this one app.

## 4. Uninstalling (installer only)

Use Windows Settings > Apps > installed apps > CHIRP > Uninstall, or the
uninstaller shortcut in the CHIRP Start Menu group. Uninstalling removes
only the files the installer put under
`%LOCALAPPDATA%\Programs\CHIRP` -- it does not touch your saved radio
images, CSV exports, or CHIRP settings, which live in your normal user
profile.

The portable ZIP has no installer to run in the first place -- just
delete the extracted folder whenever you're done with it.

## 5. Verify your download (recommended)

The release page includes a `SHA256SUMS` file with SHA-256 checksums for
every artifact. To verify what you downloaded, in PowerShell:

```powershell
Get-FileHash CHIRP-windows-v<version>-x86_64-portable.zip -Algorithm SHA256
```

(substitute the installer filename to check that one instead). Compare
the printed hash against the matching line in `SHA256SUMS`. They must
match exactly.

A matching checksum confirms the file you downloaded is byte-for-byte
identical to what this project's build produced -- it confirms **file
integrity**, not that the software is inherently safe. It's the same
guarantee a checksum gives for any download; it doesn't replace judgment
about whether to trust the source. Only download CHIRP from the official
GitHub releases page for this repository -- never from a third-party
mirror.

## USB serial cable drivers

This build does not include or install USB-to-serial chip drivers
(FTDI, Prolific, WCH/CH340, Silicon Labs CP210x, etc.). Windows Update
installs many of these automatically; if your programming cable isn't
recognized, get the driver from the cable/radio manufacturer or the
chipset manufacturer directly. Cable drivers are never CHIRP's or this
installer's responsibility.

## Getting help

If CHIRP doesn't launch after following the steps above, please report
the issue with:

- whether you used the portable ZIP or the installer;
- your Windows version (Settings > System > About);
- the source commit SHA from `build-provenance.json`;
- the exact error message or behavior you saw.
