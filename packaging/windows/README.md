# Windows packaging

This describes how `CHIRP.exe` is built, tested, and packaged for Windows
from this fork, and how it relates to the existing `appimage-v1.12.0`
Linux release and `macos-community-v1.12.0` macOS release.

## Verified v1.12.0 baseline

`appimage-v1.12.0` and `macos-community-v1.12.0` were independently
confirmed (via `git rev-parse <tag>^{commit}`, not by matching version
strings) to point at the **same commit**:

```text
9c38424f5e716c00e4444533a093ca1ba51258af  ("Release 1.12.0")
```

This is also stated explicitly in the published macOS release notes
("Source: appimage-v1.12.0 (commit 9c38424f...)") and confirmed
independently via the AppImage workflow's own run history
(`gh run list --workflow=appimage.yml`), which shows the run that
produced `appimage-v1.12.0` ran with `headSha =
9c38424f5e716c00e4444533a093ca1ba51258af`.

This commit is the **canonical v1.12.0 application source baseline**.
`chirp/__init__.py`'s `CHIRP_VERSION` constant is intentionally not the
version-of-record here (it's hardcoded to `"py3dev"` and is not updated
by any of this project's packaging pipelines) -- the release version is
established by the git tag / explicit `release_version` workflow input,
cross-checked against the pinned `source_commit`, exactly as the macOS
pipeline already does (see `docs/macos-packaging.md`).

### Why the packaging branch isn't based on that old commit

`master` has moved on since v1.12.0 -- notably the experimental
Programming Assistant feature (`chirp/assistant/`,
`chirp/wxui/programming_assistant.py`) and a large locale-file refresh
were added afterward, neither of which shipped in the v1.12.0 release
family. Branching Windows packaging infrastructure from the old commit
would either lose all of this fork's subsequent packaging/doc
improvements, or require constantly rebasing/cherry-picking them back in.

Instead, this follows the **same split this repository's macOS packaging
already established and shipped**: packaging infrastructure (this
directory, the workflow file, this doc) lives on a feature branch built
on top of the current `master` tip and can evolve freely; the
**application source being packaged** is pinned to the exact verified
commit above via a source overlay step in the workflow (see
`.github/workflows/windows-release.yml`'s "Pin application source to
source_ref" step, which mirrors `.github/workflows/macos-build.yml`
line-for-line in intent):

```bash
git checkout "$RESOLVED" -- chirp setup.py setup.cfg requirements.txt MANIFEST.in COPYING
```

So `CHIRP.exe` for v1.12.0 always contains exactly the same `chirp/`
source as the Linux AppImage and macOS Community Edition builds, even
though the packaging scripts around it keep evolving on `master`.

## Local build prerequisites

- Windows 10/11 x86-64.
- [Python 3.11](https://www.python.org/downloads/) available via the `py`
  launcher (`py -3.11`). wxPython 4.2.0 has win_amd64 wheels for this
  version.
- [Inno Setup 6](https://jrsoftware.org/isinfo.php) (`ISCC.exe` on
  `PATH`, or installed to the default
  `C:\Program Files (x86)\Inno Setup 6\` location) -- only needed for
  `-Mode Package` unless you pass `-SkipInnoSetup`.
- GNU gettext tools (`msgfmt` on `PATH`) -- needed to compile
  `chirp/locale/*.po` to `*.mo` before freezing. `choco install gettext -y`
  is what CI uses.
- Git (to resolve the current commit for `build-provenance.json`).

Everything else (PyInstaller, wxPython, CHIRP's own runtime
dependencies) is installed into an isolated virtual environment at
`packaging/windows/.build-venv` by the build script itself -- nothing is
installed into your global Python.

## Local build commands

```powershell
# From the repo root, on Windows, with the application source you want
# to package already checked out (for a real v1.12.0 build, that means
# `git checkout 9c38424f5e716c00e4444533a093ca1ba51258af -- chirp setup.py setup.cfg requirements.txt MANIFEST.in COPYING`
# first, exactly like CI's overlay step):

.\packaging\windows\build-windows.ps1 -Mode Build
.\packaging\windows\build-windows.ps1 -Mode Test
.\packaging\windows\build-windows.ps1 -Mode Package -Version 1.12.0

# Or all three in sequence:
.\packaging\windows\build-windows.ps1 -Mode All -Version 1.12.0
```

Output:

- `dist\CHIRP\` -- the validated PyInstaller one-directory bundle
  (`CHIRP.exe`, `CHIRP-driver-check.exe`, and everything they need).
- `dist\CHIRP-windows-v1.12.0-x86_64-portable.zip`
- `dist\CHIRP-windows-v1.12.0-x86_64-setup.exe`
- `build-provenance.json`, `SHA256SUMS`, `THIRD_PARTY_LICENSES.txt` in
  the repo root.

## Triggering a CI build (workflow_dispatch)

`.github/workflows/windows-release.yml` supports a manual
`workflow_dispatch` validation build from the Actions tab (or
`gh workflow run windows-release.yml --repo ddavis83864/chirp`). A
manual run never creates a tag, never creates a GitHub release, and
always labels its artifacts as an unsigned validation build. It uploads
the ZIP, installer, `SHA256SUMS`, `build-provenance.json`, and
`THIRD_PARTY_LICENSES.txt` as workflow artifacts for inspection.

## Release tag convention

Following the existing `appimage-v<version>` (Linux) and
`macos-community-v<version>` (macOS, free/unsigned channel) / `macos-v<version>`
(macOS, signed channel) namespaces, the Windows community release tag is:

```text
windows-community-v<version>
```

Pushing that tag (or manually dispatching the release job with matching
inputs) runs the same build/package/validate pipeline as the manual
`workflow_dispatch` path, but additionally validates the tag format,
version, and source commit before any release-publishing logic is
reached. **Publishing is intentionally not exercised by this initial
implementation** -- see `docs/windows-packaging.md` / the PR description
for what's been validated vs. what still requires a maintainer to
actually push a release tag.

## Version validation

The workflow refuses to proceed if:

- `release_version` isn't `X.Y.Z`.
- `source_ref` isn't a full 40-character commit SHA.
- `source_ref` isn't an ancestor of the packaging branch (refuses to
  build from a divergent/newer application source than what was
  requested).
- Requested `source_equivalence_verified=true` but the Windows source
  commit doesn't actually match the recorded Linux/macOS source commits
  (`generate-provenance.py` enforces this itself -- it will not write a
  provenance file that claims equivalence it can't back up).

## Smoke testing

`packaging/windows/smoke-test.ps1` is used identically for the portable
ZIP's extracted `CHIRP.exe` and for an Inno Setup-installed `CHIRP.exe`:
it launches with an isolated `--config-dir`, confirms the process
survives long enough to finish wx initialization, checks captured stderr
for known failure signatures (import errors, DLL load failures), and
closes the app cleanly. It also runs the bundled
`CHIRP-driver-check.exe` helper (see `driver_check.py`) to confirm radio
drivers actually registered *inside the frozen bundle* -- PyInstaller's
static import analysis can silently miss a dynamically-loaded driver,
and that class of bug would otherwise only surface when a user tries a
specific radio.

This is a **startup** smoke test only. It does not exercise interactive
GUI functionality (opening a file, talking to a radio, etc.) -- see the
manual hardware validation checklist below for what still requires a
human with real hardware.

## Windows Defender scanning

The workflow scans the built bundle directory, the portable ZIP, and the
installer with Windows Defender (available by default on the
`windows-2022` GitHub-hosted runner) and fails the build on a confirmed
detection. If Defender is unavailable on a given runner, the workflow
reports that explicitly rather than silently skipping the check.

## Code-signing integration point

Nothing is signed by this implementation. `build-provenance.json` always
reports `"code_signing": {"signed": false, "status":
"unsigned-community-prerelease"}`, and every generated artifact name,
the installer UI, and `README-Windows.txt` say so explicitly.

The workflow is structured so a signing stage can be inserted later,
after `Invoke-Package` produces the validated ZIP/installer and before
any future release-publishing step -- the same position the macOS
workflow's signing/notarization step occupies relative to its own
build/package step. Plausible future options, in roughly increasing
setup cost:

- A traditional Authenticode code-signing certificate (OV or EV) from a
  CA, signed locally or in CI via `signtool.exe`.
- A hardware-backed signing token (e.g. a YubiKey-backed EV certificate),
  required by some CAs for EV certificates specifically.
- [Azure Trusted Signing](https://learn.microsoft.com/azure/trusted-signing/) --
  a managed cloud signing service; avoids handling a raw private key or
  hardware token in CI at all.
- Another managed/cloud code-signing provider with a CI-friendly API.

None of these require secrets to exist in this repository today -- they
would be added only when a maintainer actually sets up signing.

## Known limitations

- Driver-registry validation (`CHIRP-driver-check.exe`) runs inside the
  frozen bundle, which is the strongest signal PyInstaller's static
  analysis didn't silently drop a driver -- but it only checks that
  drivers *register*, not that any specific radio actually programs
  correctly.
- The startup smoke test confirms the app launches and stays alive; it
  is not a substitute for interactive GUI testing or real hardware
  testing (see the manual validation checklist).
- Only Windows x86-64 is built. No ARM64, no 32-bit, no MSIX/Microsoft
  Store package, no one-file executable.
- `SHA256SUMS`/`build-provenance.json` describe a **reproducible build
  process** (pinned tool versions, pinned application source, documented
  inputs) -- this has not been verified to produce bit-for-bit identical
  binaries across repeated builds, and no such claim is made.

## Manual hardware validation

GitHub Actions cannot validate real radio hardware. See
`docs/windows-manual-validation-checklist.md` for the checklist a human
with a real Windows 11 machine and supported hardware should work
through before this build is treated as fully validated end-to-end.
