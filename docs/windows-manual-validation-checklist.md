# Windows manual hardware validation checklist

GitHub Actions can build, package, launch-smoke-test, silently
install/uninstall, and run a driver-*registry* check for the Windows
CHIRP Community Edition build -- but it cannot plug in a real USB
programming cable or talk to a real radio. **None of the items below
have been performed as part of this implementation.** They require a
human with a real (or virtualized) Windows 11 x86-64 machine and actual
radio hardware, and should be completed before treating a Windows
release as fully validated end-to-end, not just CI-validated.

Copy this checklist into the release PR or issue when performing a
manual validation pass, and check off what was actually done -- do not
mark an item done unless it was physically performed.

## Environment

- [ ] Fresh Windows 11 x86-64 system or VM (not the machine used to
      build the release).
- [ ] Confirm Windows version and build number before starting
      (Settings > System > About).

## Portable ZIP

- [ ] Download `CHIRP-windows-v<version>-x86_64-portable.zip` from the
      release page (not a local build).
- [ ] Verify its SHA-256 against `SHA256SUMS`.
- [ ] Extract the ZIP using Windows Explorer's built-in "Extract All".
- [ ] Launch `CHIRP.exe` from the extracted folder.
- [ ] Confirm the CHIRP icon appears correctly (taskbar and window).
- [ ] Confirm no console window appears.

## Installer

- [ ] Download `CHIRP-windows-v<version>-x86_64-setup.exe` from the
      release page.
- [ ] Verify its SHA-256 against `SHA256SUMS`.
- [ ] Run the installer as a normal (non-administrator) user; confirm no
      UAC elevation prompt appears for the default per-user install.
- [ ] Confirm the install lands under
      `%LOCALAPPDATA%\Programs\CHIRP`.
- [ ] Confirm a Start Menu shortcut ("CHIRP") was created.
- [ ] Leave the optional desktop shortcut checkbox unchecked; confirm no
      desktop icon appears.
- [ ] Re-run the installer, this time checking the desktop shortcut
      option; confirm the desktop icon appears and launches CHIRP.
- [ ] Launch CHIRP from the Start Menu shortcut.
- [ ] Launch CHIRP from the installed `CHIRP.exe` directly via a
      PowerShell prompt (`& "$env:LOCALAPPDATA\Programs\CHIRP\CHIRP.exe"`).

## Upgrade behavior

- [ ] With a prior version installed and some user preferences/settings
      changed from defaults, install a newer version over it using the
      same installer flow.
- [ ] Confirm the upgrade completes without requiring a manual uninstall
      first.
- [ ] Confirm application binaries were replaced (Help > About shows the
      new version).
- [ ] Confirm user preferences/settings from before the upgrade are
      still present.
- [ ] Confirm any radio image files (.img) saved before the upgrade are
      still present and still open correctly.

## Uninstall behavior

- [ ] Save a radio image file and a CSV export somewhere in your normal
      Documents folder (not the install directory) before uninstalling.
- [ ] Change a CHIRP preference from its default (e.g. a color-coding
      setting) before uninstalling.
- [ ] Uninstall via Windows Settings > Apps.
- [ ] Confirm `%LOCALAPPDATA%\Programs\CHIRP` no longer contains
      `CHIRP.exe` (or was removed entirely).
- [ ] Confirm the saved radio image and CSV export from Documents are
      untouched.
- [ ] Reinstall and confirm the previously changed preference is still
      set (i.e. uninstall did not wipe user configuration).

## Real hardware

- [ ] Plug in a supported USB programming cable; confirm Windows assigns
      it a COM port (Device Manager) without needing a manually
      installed driver, OR follow the manufacturer's driver install and
      confirm it then works.
- [ ] In CHIRP, select that COM port and **read** from a real,
      supported radio.
- [ ] **Write** a small, safe test change to the same radio and confirm
      it applies correctly on the radio itself.
- [ ] Confirm no other running program interferes with the COM port
      (e.g. another terminal program left open on the same port
      produces a clear error, not a silent hang).

## Core workflows

- [ ] Open an existing `.img` file (from a real radio read, or a
      provided sample).
- [ ] Save changes to that image.
- [ ] Import a CSV memory list.
- [ ] Export the current memory list to CSV.
- [ ] Enable Programming Assistant (Help > Enable Programming Assistant
      (Experimental)), restart CHIRP, and confirm the feature is
      reachable via Radio > Programming Assistant... (functional
      end-to-end testing of this feature is out of scope for this
      checklist beyond "is it reachable and does it open").
- [ ] Open View > Radio Profile (if applicable to the radio in use) and
      confirm it opens without error.
- [ ] Enable memory color coding (on by default) and confirm colors
      render correctly for a few different memory types.

## Windows-specific behavior

- [ ] Confirm Windows Defender does not flag `CHIRP.exe` or the
      installer during normal use (beyond the expected first-launch
      SmartScreen warning, which is separate from a Defender
      detection).
- [ ] Confirm the SmartScreen "unknown publisher" warning appears as
      described in `docs/windows-community-installation.md`, and that
      "More info" > "Run anyway" works as documented.
- [ ] Confirm CHIRP's debug log (Help > Open debug log) is reachable and
      contains recent log output.
- [ ] Deliberately trigger an error (e.g. try to open a corrupt/invalid
      file) and confirm CHIRP shows a normal error dialog rather than
      crashing silently.

## Sign-off

Record, for whoever performed this checklist:

- Date.
- Windows version/build tested.
- CHIRP version and source commit tested (from `build-provenance.json`
  or Help > About).
- Radio model(s) and USB cable(s) used for the hardware section.
- Any items above that were skipped, and why.
- Any defects found, with enough detail to file an issue.
