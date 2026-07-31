# macOS packaging

This describes how `CHIRP.app` is built for macOS from this fork, and how it
relates to the existing `appimage-v1.12.0` Linux release.

## Source revision this packaging targets

There is no `v1.12.0` tag in this repository; the tagged Linux release is
`appimage-v1.12.0`, an annotated tag pointing at commit
`9c38424f5e716c00e4444533a093ca1ba51258af` ("Release 1.12.0"). That commit
is what the existing Linux AppImage (`CHIRP-appimage-v1.12.0-x86_64.AppImage`)
was built from, and it is the default `source_ref` in
`.github/workflows/macos-build.yml`.

Two revisions are involved and are intentionally kept separate:

- **Packaging infrastructure** (this directory, the workflow file, this
  doc): lives on `feature/macos-v1.12.0-packaging`, branched from `master`,
  and can be updated freely without touching application behavior.
- **Application source being packaged**: pinned to the exact commit above.
  The workflow checks out `source_ref` (not `master`, not the branch tip)
  and asserts the checked-out `HEAD` matches it exactly whenever `source_ref`
  is a full 40-character SHA, refusing to build otherwise. This is what
  guarantees the macOS build represents the same application code as the
  Linux AppImage, not whatever happens to be on `master` when the workflow
  runs.

`chirp/__init__.py` hardcodes `CHIRP_VERSION = "py3dev"`; this is unchanged
by either the AppImage or the macOS build -- the AppImage's `1.12.0` string
only appears in its filename and AppDir metadata (via `sed` substitution in
`appimage/build.sh`), never in the running application's internal version
string. The macOS build follows the same split: `1.12.0` appears in
`Info.plist` (`CFBundleShortVersionString`/`CFBundleVersion`) and artifact
filenames, while the in-app version string is whatever the packaged source
revision hardcodes.

## Supported macOS versions

`LSMinimumSystemVersion` is set to `11.0` (Big Sur). This matches
wxPython 4.2.0's macOS wheel baseline (`macosx_10_10`/`macosx_11_0` platform
tags) and has not been runtime-validated below that on real hardware -- see
Limitations.

## Supported architectures

| Artifact | Runner | Status |
|---|---|---|
| `x86_64` | `macos-13` (Intel) | Native arch-specific build |
| `arm64` | `macos-14` (Apple Silicon) | Native arch-specific build |
| `universal2` | `macos-14` | Built with PyInstaller `target_arch=universal2`; only shipped if `validate_bundle.sh`'s `lipo -info` check confirms both `x86_64` and `arm64` slices in the final executable. The workflow fails that job rather than shipping a mislabeled artifact. |

wxPython 4.2.0 only publishes macOS wheels for CPython 3.10, and only as
`universal2` wheels (no separate arm64/x86_64 wheels exist for it). That is
why the build pins Python 3.10 and why a genuine `universal2` build is
possible at all -- but it has only been verified by static inspection of the
toolchain (PyPI wheel tags, python.org's universal2 3.10 installer), not by
running the workflow on a real macOS runner. Treat the `universal2` artifact
as unverified until a CI run's `lipo -info` output has been checked.

## Local build prerequisites

- macOS (Intel or Apple Silicon)
- Python 3.10 on `PATH` as `python3`
- Xcode Command Line Tools (`codesign`, `hdiutil`, `ditto`, `lipo`, `otool`,
  `plutil` come from these)
- `gettext` (for `msgfmt`, used to compile `.po` translations): `brew install gettext`

## Local build commands

```bash
# Unsigned .app for the native architecture of your machine:
./packaging/macos/build_app.sh

# Explicit architecture (must run on matching or universal2-capable hardware):
./packaging/macos/build_app.sh arm64
./packaging/macos/build_app.sh x86_64
./packaging/macos/build_app.sh universal2

# Validate the result:
./packaging/macos/validate_bundle.sh packaging/macos/dist/CHIRP.app \
    --version 1.12.0 --bundle-id com.ddavis83864.chirp --arch arm64

# Package it:
ditto -c -k --sequesterRsrc --keepParent \
    packaging/macos/dist/CHIRP.app CHIRP-1.12.0-macOS-arm64.app.zip
./packaging/macos/build_dmg.sh packaging/macos/dist/CHIRP.app \
    CHIRP-1.12.0-macOS-arm64.dmg "CHIRP 1.12.0"
```

`CHIRP_APP_VERSION`, `CHIRP_BUNDLE_ID`, and `CHIRP_MIN_MACOS` environment
variables override the corresponding defaults in `build_app.sh` /
`chirpwx.spec`.

## GitHub Actions usage

`.github/workflows/macos-build.yml` runs only on `workflow_dispatch` --
never on branch pushes, so it can never silently overwrite or mutate the
existing `appimage-v1.12.0` release. Inputs:

- `source_ref` -- commit to package (default: the `appimage-v1.12.0` commit)
- `release_version` -- version string for metadata/filenames (default `1.12.0`)
- `architectures` -- `all`, `x86_64`, `arm64`, or `universal2`
- `build_dmg` -- also build the DMG (default `true`)
- `enable_signing` / `enable_notarization` -- both default `false`
- `enable_release_upload` -- default `false`; when `true`, uploads to
  `release_tag` (default `v1.12.0-macos.1`), never to `appimage-v1.12.0`
  (the workflow refuses any `release_tag` starting with `appimage-v`)

## Artifact naming

```text
CHIRP-1.12.0-macOS-arm64.app.zip
CHIRP-1.12.0-macOS-arm64.dmg
CHIRP-1.12.0-macOS-x86_64.app.zip
CHIRP-1.12.0-macOS-x86_64.dmg
CHIRP-1.12.0-macOS-universal2.app.zip   (only if lipo verification passes)
CHIRP-1.12.0-macOS-universal2.dmg
```

## Unsigned installation behavior

With `enable_signing=false` (the default), Gatekeeper will refuse to open
the app with a plain double-click ("CHIRP.app is damaged and can't be
opened" or "cannot be opened because the developer cannot be verified",
depending on macOS version and how the zip/dmg was downloaded). To run an
unsigned build: right-click (or Control-click) `CHIRP.app` -> Open -> Open,
or clear the quarantine attribute manually:

```bash
xattr -dr com.apple.quarantine /Applications/CHIRP.app
```

This is expected, standard behavior for unsigned Developer-ID-less
software and is not a packaging bug.

## Signing configuration

Set `enable_signing=true` and provide these repository secrets:

- `MACOS_CERTIFICATE_P12` -- base64-encoded Developer ID Application `.p12`
- `MACOS_CERTIFICATE_PASSWORD` -- password for that `.p12`
- `MACOS_SIGNING_IDENTITY` -- e.g. `Developer ID Application: NAME (TEAMID)`

`packaging/macos/sign.sh` imports the certificate into a temporary keychain
(deleted via a trap on exit), signs nested `.so`/`.dylib`/executable files,
then the app bundle itself, with the hardened runtime and
`packaging/macos/entitlements.plist`. Never commit real secret values to
this repository, workflow files, or logs.

## Notarization configuration

Set `enable_notarization=true` (requires `enable_signing=true`) and provide:

- `APPLE_ID`
- `APPLE_TEAM_ID`
- `APPLE_APP_SPECIFIC_PASSWORD`

`packaging/macos/notarize.sh` submits via `xcrun notarytool submit --wait`,
then staples the ticket with `xcrun stapler staple`.

## Troubleshooting

- **"CHIRP.app is damaged"**: expected for unsigned builds; see Unsigned
  installation behavior above.
- **`wx` import errors during `build_app.sh`**: confirm `python3 --version`
  reports 3.10 exactly -- wxPython 4.2.0 has no macOS wheel for 3.11/3.12.
- **`validate_bundle.sh` fails the `universal2` architecture check**: the
  build toolchain did not actually produce a fat binary (e.g. Python or
  PyInstaller resolved to a thin interpreter). Do not ship that artifact
  under the `universal2` name; fall back to the arch-specific builds.
- **Notarization rejected**: run `xcrun notarytool log <submission-id>
  --apple-id ... --team-id ... --password ...` for Apple's rejection detail.

## How to verify checksums

```bash
shasum -a 256 -c CHIRP-1.12.0-macOS-arm64.sha256.txt
```

(or compare the printed hash against the `.sha256.txt` file's contents
directly.)

## Known limitations

- No macOS hardware was used to build, run, sign, or notarize this
  packaging -- it was authored and statically reviewed from a Linux
  development environment. The workflow must be run on a real GitHub
  Actions macOS runner (via `workflow_dispatch`) before any artifact from
  it can be considered validated.
- The `universal2` artifact's architecture claim is unverified until a real
  run's `lipo -info` output has been inspected; see the Architectures table.
- CI runs with no interactive GUI login session may not fully exercise the
  wx event loop; the workflow's launch smoke test only checks that the
  process does not immediately exit, not that the main window renders.
  Full interactive testing (opening dialogs, importing/exporting CSVs and
  images, driver loading) needs to be done manually on real hardware.
- Physical radio programming (serial/USB device communication) has not
  been tested and cannot be tested in CI; only serial-port enumeration with
  no radio attached is expected to be exercised.
- DMG creation via `hdiutil` is not byte-for-byte deterministic (HFS+
  timestamps), though the build inputs and process are reproducible.
- Signing and notarization are implemented but unexercised without real
  Apple Developer credentials in the repository's secrets.
