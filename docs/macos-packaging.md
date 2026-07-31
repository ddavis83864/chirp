# macOS packaging

This describes how `CHIRP.app` is built, signed, notarized, and released for
macOS from this fork, and how it relates to the existing `appimage-v1.12.0`
Linux release.

There are two independent release channels, selected explicitly via the
`release_channel` workflow input -- never inferred from whether Apple
credentials happen to exist:

| | **Community Edition** | **Signed Edition** |
|---|---|---|
| `release_channel` value | `community` | `signed` |
| Cost | Free | Requires a paid Apple Developer Program membership |
| Apple Developer ID signing | No | Yes |
| Apple notarization | No | Yes |
| Gatekeeper first-launch experience | Warning; user must explicitly authorize (Control-click -> Open, or System Settings -> Privacy & Security) | Opens normally, no warning |
| Tag namespace | `macos-community-v<version>` | `macos-v<version>` |
| Artifact names | `..._-unsigned.app.zip` / `..._-unsigned.dmg` | `....app.zip` / `....dmg` |
| GitHub Environment | `macos-community-release` (no Apple secrets) | `macos-production-release` (has Apple secrets) |
| Required secrets | none | `MACOS_CERTIFICATE_P12`, `MACOS_CERTIFICATE_PASSWORD`, `MACOS_SIGNING_IDENTITY`, `APPLE_ID`, `APPLE_TEAM_ID`, `APPLE_APP_SPECIFIC_PASSWORD` |
| Install guide | [docs/macos-community-installation.md](macos-community-installation.md) | (no warning to document -- opens normally) |

Unsigned status is a **user-experience limitation**, not a packaging
failure: a Community Edition artifact goes through exactly the same
architecture, bundle, resource, and dynamic-library validation as a Signed
Edition artifact (see Community Validation Gates below) -- the only thing
missing is Apple's verification of the publisher's identity, which costs
money and requires an Apple Developer Program membership neither this fork
nor its packaging infrastructure currently has. The Signed Edition path
can be enabled later, for the exact same source and packaging pipeline,
simply by adding the six secrets and selecting `release_channel=signed` --
no redesign needed.

## Source revision this packaging targets

There is no `v1.12.0` tag in this repository; the tagged Linux release is
`appimage-v1.12.0`, an annotated tag pointing at commit
`9c38424f5e716c00e4444533a093ca1ba51258af` ("Release 1.12.0"). That commit is
what the existing Linux AppImage (`CHIRP-appimage-v1.12.0-x86_64.AppImage`)
was built from, and it is the default `source_ref` in both macOS workflows.

Two revisions are involved and are intentionally kept separate:

- **Packaging infrastructure** (this directory, the workflow files, this
  doc): lives on feature branches built on top of `master`, and can be
  updated freely without touching application behavior.
- **Application source being packaged**: pinned to the exact commit above.
  The build workflow checks out `source_ref` (not `master`, not the branch
  tip), verifies that commit is an ancestor of the packaging branch, and
  overlays only the application source paths (`chirp/`, `setup.py`,
  `setup.cfg`, `requirements.txt`, `MANIFEST.in`, `COPYING`) from it. The
  release workflow additionally *requires* `source_ref` to be a full
  40-character commit SHA (not a tag or branch name) -- this is what
  guarantees a macOS release represents the exact same application code as
  the Linux AppImage, not whatever happens to be on `master` when the
  workflow runs.

`chirp/__init__.py` hardcodes `CHIRP_VERSION = "py3dev"`; this is unchanged
by either the AppImage or the macOS build -- the AppImage's `1.12.0` string
only appears in its filename and AppDir metadata (via `sed` substitution in
`appimage/build.sh`), never in the running application's internal version
string. The macOS build follows the same split: `1.12.0` appears in
`Info.plist` (`CFBundleShortVersionString`/`CFBundleVersion`) and artifact
filenames, while the in-app version string is whatever the packaged source
revision hardcodes.

## Supported macOS versions

`LSMinimumSystemVersion` is `11.0` (Big Sur), based on wxPython 4.2.0's
macOS wheel baseline. This has not been runtime-validated below macOS 15 on
real hardware -- see Known limitations.

## Supported architectures

| Artifact | Runner label | Status |
|---|---|---|
| `arm64` | `macos-15` | Native build. **Validated**: genuine arm64 Mach-O throughout (main executable + all bundled `.so`/`.dylib`), correct bundle/`Info.plist`, all 18 translations, all 20 stock configs, clean dynamic-library resolution, clean smoke test. |
| `x86_64` | `macos-15-large` | Native build. **Validated**: genuine x86_64 Mach-O throughout (264/264 native binaries individually inspected), same resource/dynamic-library/smoke-test results as arm64, byte-for-byte identical non-binary resource tree. |
| `universal2` | `macos-15` | **Not eligible, confirmed by a real build attempt.** PyInstaller's `target_arch=universal2` failed at the `COLLECT` stage: `IncompatibleBinaryArchError: numpy/_core/_multiarray_tests.cpython-310-darwin.so is not a fat binary!`. `numpy` is a transitive dependency (not pinned directly by this packaging) whose official PyPI macOS wheels are architecture-specific, not universal2 -- unlike Python 3.10 and wxPython 4.2.0, which both are genuinely universal2 on the runners used here. PyInstaller's own strict architecture-conversion check correctly refused to produce a mislabeled or partially-thin artifact. **Separate native `arm64` and `x86_64` artifacts are the supported and only release strategy.** Do not attempt to `lipo`-merge the two native builds together after the fact -- that produces a Frankenstein binary with mismatched embedded resources/signatures, not a real universal2 build.

wxPython 4.2.0 only publishes macOS wheels for CPython 3.10 (no 3.11/3.12
macOS wheels exist for this version), which is why the build pins Python 3.10.

## Workflows

Two separate GitHub Actions workflows exist, deliberately kept apart so
release publication has exactly one path with strong guarantees, while
ordinary build validation stays cheap and unrestricted:

### `.github/workflows/macos-build.yml`

Builds, optionally signs, and optionally notarizes CHIRP.app. Runs on
`workflow_dispatch` and `workflow_call` only -- never on branch pushes, so it
can never silently mutate anything. **Never publishes a release** -- it has
no release-upload capability at all. Callable directly for build validation,
or called by `macos-release.yml` as the build step of a release.

Inputs:

- `source_ref` -- commit to package (default: the `appimage-v1.12.0` commit)
- `release_version` -- version string for metadata/filenames (default `1.12.0`)
- `architectures` -- comma-separated list: `arm64`, `x86_64`, `universal2`,
  or `all` (expands to all three); e.g. `arm64,x86_64`
- `release_channel` -- `community` (default) or `signed`. `check-secrets`
  rejects any inconsistent combination before any macOS runner is used:
  `community` requires `enable_signing=false` and `enable_notarization=false`;
  `signed` requires both `true`.
- `build_dmg` -- also build the DMG (default `true`)
- `enable_signing` / `enable_notarization` -- both default `false`; the
  workflow fails fast in `check-secrets` if either is requested without its
  required secrets configured

For `release_channel=community`, artifact filenames get a `-unsigned`
suffix (e.g. `CHIRP-1.12.0-macOS-arm64-unsigned.app.zip`) so an unsigned
artifact can never be confused with a signed one, and an additional step
(`Verify Community Edition bundle is not Developer-ID signed`) inspects
`codesign -dv` output and fails the build if a real `Authority=` line is
unexpectedly present -- a Community Edition artifact must be ad-hoc-signed
at most (PyInstaller applies its own ad-hoc signature so Apple Silicon
binaries can execute at all; this is not a Developer ID signature).

### `.github/workflows/macos-release.yml`

The **only** workflow authorized to publish a macOS GitHub release. Runs on
`workflow_dispatch` only. Calls `macos-build.yml` internally, then adds
**two separate** publish jobs -- `publish-community-release` and
`publish-signed-release` -- each gated on its own channel, its own
environment, and its own independent re-verification, so a Community
Edition run can structurally never touch the signed release's environment
or secrets:

- `publish-community-release` runs only if `release_channel=community`
  **and** `enable_release_upload=true` **and** `enable_signing=false`
  **and** `enable_notarization=false`, targets the `macos-community-release`
  environment (no Apple secrets), and re-verifies each architecture's
  provenance manifest reports `release_channel: "community"`,
  `signed: false`, `notarized: false` before publishing.
- `publish-signed-release` runs only if `release_channel=signed` **and**
  `enable_release_upload=true` **and** `enable_signing=true` **and**
  `enable_notarization=true`, targets the `macos-production-release`
  environment, and re-verifies each architecture's provenance manifest
  reports `release_channel: "signed"`, `signed: true`, `notarized: true`
  before publishing.

Both publish jobs share the same `guard` job's pre-flight checks (valid
inputs, tag/channel namespace consistency, `release_tag` doesn't already
exist as a tag or release, working tree clean) and both independently
recompute SHA-256 for every downloaded artifact and compare against the
recorded checksums rather than trusting the upstream job's claimed success.

Inputs: `source_ref` (must be a full 40-character SHA for a release, unlike
the build workflow which accepts a tag name with a warning), `release_version`,
`architectures` (default `arm64,x86_64` -- `universal2` is refused at
publish time), `release_channel` (`community` or `signed`), `enable_signing`,
`enable_notarization`, `enable_release_upload`, `release_tag` (default
`macos-community-v1.12.0`), `release_name`, `prerelease` (default `true`).

Safe defaults: `release_channel=community`, `enable_signing=false`,
`enable_notarization=false`, `enable_release_upload=false`, `prerelease=true`.

## Modes

| Mode | channel | signing | notarization | release upload | Result |
|---|---|---|---|---|---|
| A | community | false | false | false | Unsigned validation build. `.zip`/`.dmg` as workflow artifacts only. No Apple credentials needed. |
| B | community | false | false | true | Unsigned arm64+x86_64 Community Edition GitHub release, prominently labeled unsigned. No Apple credentials needed. |
| C | signed | true | true | false | Signed, notarized, stapled release-candidate artifacts as workflow artifacts. No release. |
| D | signed | true | true | true | Everything Mode C does, plus a real signed macOS GitHub release, gated by the protected `macos-production-release` environment. |

Any other combination is rejected by `check-secrets` (in `macos-build.yml`)
and/or `guard` (in `macos-release.yml`) before a macOS runner is used --
e.g. `community` with signing enabled, `signed` with notarization disabled,
or `enable_notarization=true` with `enable_signing=false`.

Mode D is structurally impossible unless Mode C's signing and notarization
both genuinely succeeded in the *same* triggered run -- `publish-signed-release`
depends on `build-sign-notarize` and independently re-verifies its output
rather than trusting a flag. Mode B is available immediately, with no
Apple credentials of any kind, because the Community Edition channel never
requires them.

## Protected environments

Two GitHub Environments gate release publication, one per channel, so
Community Edition runs never have access to signed-release secrets even if
those secrets exist in the repository:

### `macos-community-release`

Targeted by `publish-community-release`. Should have **no** Apple secrets
configured on it -- the Community Edition channel doesn't need any. The
repo owner should still configure, under **Settings -> Environments ->
macos-community-release**:

- **Required reviewers**, so an unsigned public release still needs a
  human sign-off even though no Apple credentials are involved.
- **Deployment branch/ref policy**, restricting which branches may deploy.

### `macos-production-release`

Targeted by `publish-signed-release`. Holds (or should hold) the six Apple
secrets, scoped to this environment specifically rather than repository-wide.
The repo owner should configure, under **Settings -> Environments ->
macos-production-release**:

- **Required reviewers**: at least one person who must approve before
  `publish-signed-release` runs, even if all automated gates pass.
- **Deployment branch/ref policy**: restrict which branches/refs may
  deploy to this environment (e.g. only `feature/macos-production-release-process`
  or, once merged, `master`).
- **Prevent self-review**, if your plan tier supports it, so the person who
  triggered the run cannot also be the approver.
- **Wait timer**, if you want a mandatory cooling-off period before
  publication proceeds even after approval.
- **Environment secrets**: `MACOS_CERTIFICATE_P12`, `MACOS_CERTIFICATE_PASSWORD`,
  `MACOS_SIGNING_IDENTITY`, `APPLE_ID`, `APPLE_TEAM_ID`, and
  `APPLE_APP_SPECIFIC_PASSWORD`, scoped to this environment so they're only
  readable when a run is actually deploying to it.

Both environments exist as bare shells only (created via the API) -- **no
protection rules are configured on either yet**. Do not treat Mode B or
Mode D as safe to run in production until the relevant environment's
protection rules are set up by someone with repo admin access.

## Local build prerequisites

- macOS (Intel or Apple Silicon)
- Python 3.10 on `PATH` as `python3`
- Xcode Command Line Tools (`codesign`, `hdiutil`, `ditto`, `lipo`, `otool`,
  `plutil`, `xcrun` come from these)
- `gettext` (for `msgfmt`): `brew install gettext`

## Local build commands

```bash
# Unsigned .app for the native architecture of your machine:
./packaging/macos/build_app.sh

# Explicit architecture:
./packaging/macos/build_app.sh arm64
./packaging/macos/build_app.sh x86_64

# Validate the result:
./packaging/macos/validate_bundle.sh packaging/macos/dist/CHIRP.app \
    --version 1.12.0 --bundle-id com.ddavis83864.chirp --arch arm64

# Package it:
ditto -c -k --sequesterRsrc --keepParent \
    packaging/macos/dist/CHIRP.app CHIRP-1.12.0-macOS-arm64.app.zip
./packaging/macos/build_dmg.sh packaging/macos/dist/CHIRP.app \
    CHIRP-1.12.0-macOS-arm64.dmg "CHIRP 1.12.0"
```

To sign and notarize locally (requires a real Developer ID Application
certificate and Apple credentials on your own keychain/environment):

```bash
export MACOS_CERTIFICATE_P12=... MACOS_CERTIFICATE_PASSWORD=... MACOS_SIGNING_IDENTITY=...
./packaging/macos/sign.sh packaging/macos/dist/CHIRP.app signing-info.json

export APPLE_ID=... APPLE_TEAM_ID=... APPLE_APP_SPECIFIC_PASSWORD=...
ditto -c -k --keepParent packaging/macos/dist/CHIRP.app /tmp/submit.zip
./packaging/macos/notarize.sh /tmp/submit.zip packaging/macos/dist/CHIRP.app app .

ditto -c -k --sequesterRsrc --keepParent packaging/macos/dist/CHIRP.app CHIRP-1.12.0-macOS-arm64.app.zip
./packaging/macos/build_dmg.sh packaging/macos/dist/CHIRP.app CHIRP-1.12.0-macOS-arm64.dmg "CHIRP 1.12.0"
./packaging/macos/sign_dmg.sh CHIRP-1.12.0-macOS-arm64.dmg
./packaging/macos/notarize.sh CHIRP-1.12.0-macOS-arm64.dmg CHIRP-1.12.0-macOS-arm64.dmg dmg .
```

`CHIRP_APP_VERSION`, `CHIRP_BUNDLE_ID`, and `CHIRP_MIN_MACOS` environment
variables override the corresponding defaults in `build_app.sh`/`chirpwx.spec`.

## Artifact naming

Signed Edition:

```text
CHIRP-1.12.0-macOS-arm64.app.zip
CHIRP-1.12.0-macOS-arm64.dmg
CHIRP-1.12.0-macOS-x86_64.app.zip
CHIRP-1.12.0-macOS-x86_64.dmg
CHIRP-1.12.0-macOS-SHA256SUMS.txt
```

Community Edition -- every binary artifact filename carries an `unsigned`
marker so it can never be confused with a signed one:

```text
CHIRP-1.12.0-macOS-arm64-unsigned.app.zip
CHIRP-1.12.0-macOS-arm64-unsigned.dmg
CHIRP-1.12.0-macOS-x86_64-unsigned.app.zip
CHIRP-1.12.0-macOS-x86_64-unsigned.dmg
CHIRP-1.12.0-macOS-Community-SHA256SUMS.txt
CHIRP-1.12.0-macOS-Community-PROVENANCE.json
```

`publish-community-release` asserts every artifact filename matches
`*-unsigned.app.zip`/`*-unsigned.dmg` before publishing and fails the run
otherwise. Neither channel's checksum manifest ever contains the other
channel's or Linux's entries.

## Signing sequence (inside-out)

`packaging/macos/sign.sh`:

1. Creates an ephemeral keychain with a random password (`openssl rand`),
   used only for this job, and imports the `.p12` **only into that
   keychain** -- never the runner's persistent login keychain.
2. Deletes the decoded certificate file immediately after import.
3. Verifies the requested `MACOS_SIGNING_IDENTITY` matches **exactly one**
   identity in the imported certificate before signing anything -- refuses
   to proceed on zero or multiple matches.
4. Signs, in order: nested `.framework` bundles, then loose `.dylib`/`.so`
   files (excluding anything inside an already-signed framework, to avoid
   double-signing), then every executable in `Contents/MacOS` (helper
   executables and the main `chirp` executable), then the outer `.app`
   bundle itself -- **without** `--deep` at that final step, since
   everything nested is already explicitly signed by that point. `--deep`
   is used only for the subsequent *verification* pass
   (`codesign --verify --deep --strict`), which checks the result rather
   than producing it.
5. Every signing invocation uses `--options runtime` (hardened runtime) and
   `--entitlements packaging/macos/entitlements.plist`.
6. Records signing details (authority, team ID, bundle ID, hardened-runtime
   status, timestamp presence) to a JSON file for the provenance manifest.
7. Deletes the ephemeral keychain in a `trap ... EXIT`, which fires even if
   an earlier step in the script failed.

`packaging/macos/sign_dmg.sh` signs the built DMG itself with the same
identity, after `sign.sh` has already unlocked it in the current keychain
search list within the same job.

## Entitlements

`packaging/macos/entitlements.plist` carries exactly one entitlement:
`com.apple.security.cs.allow-unsigned-executable-memory`, justified by
`serial.tools.list_ports_osx` (pyserial, used for serial port enumeration)
calling directly into CoreFoundation/IOKit via `ctypes`, which needs
writable+executable memory pages for libffi's callback trampolines under
the hardened runtime.

Two entitlements present in earlier drafts were removed for lacking
evidence: `com.apple.security.cs.disable-library-validation` (unnecessary
since every nested binary is re-signed under the same Developer ID
identity, so library validation should hold) and
`com.apple.security.cs.allow-dyld-environment-variables` (nothing in this
codebase reads `DYLD_*` at runtime). If a real Mode C (signed) run ever
fails with a library-validation or dyld-related error, add the specific
entitlement back with that exact failure documented above it in the file --
not preemptively. No Mode C run has been possible yet; Apple Developer ID
credentials are not configured in this repository.

## Provenance manifest

Each architecture build produces `<basename>-manifest.json` with:
`release_channel`, `signed`, `notarized`, `stapled`, `gatekeeper_assessed`,
`developer_id_signed`, `source_sha`, `packaging_sha`, `workflow_run_id`,
`workflow_run_attempt`, `architecture`, `application_version`,
`bundle_identifier`, `minimum_macos_version`, `build_timestamp`,
`signing_authority`, `apple_team_id`, `hardened_runtime`, and an
`artifacts` list of `{filename, size, sha256}` objects (one per shipped
`.app.zip`/`.dmg` -- adapted from a flat `artifact_filename`/`artifact_size`/
`sha256` to a list since one manifest covers both files for that
architecture). For Community Edition builds, `signed`, `notarized`,
`stapled`, `gatekeeper_assessed`, and `developer_id_signed` are always
`false` -- never `null`, never omitted. `publish-community-release` builds
a combined `CHIRP-<version>-macOS-Community-PROVENANCE.json` (the per-
architecture manifests as a JSON array) and attaches it to the release.

## Community validation gates

Before a Community Edition artifact can be published, every one of these
must pass (implemented across `validate_bundle.sh`, the workflow's
Community-specific verification steps, and `publish-community-release`'s
independent re-check) -- none of them require Developer ID, notarization,
stapling, or a successful `spctl` trust assessment, and a `spctl` rejection
on an unsigned artifact is expected, not a defect:

correct source SHA and version; correct bundle identifier; correct minimum
macOS version (`LSMinimumSystemVersion`); native `arm64`/`x86_64`
executable matching the build's own architecture with no cross-architecture
contamination; all `.so`/`.dylib` files inspected; bundled Python runtime
and wxPython native modules present; `wx._xml` present and correct
architecture; expected translation and stock-configuration counts; no
leaked build-machine paths in `otool -L` output; ZIP extracts cleanly with
executable permissions intact; DMG mounts and contains `CHIRP.app` plus an
`/Applications` symlink; the app launches on the build runner and survives
the smoke-test interval with no traceback, missing-library error, or
wxPython initialization failure; checksums match after upload/download;
the provenance manifest is complete and self-consistent; release notes
identify the artifacts as unsigned; the tag is in the `macos-community-v*`
namespace.

## Notarization and stapling strategy

Both the `.app` (for the shipped `.zip`) and the `.dmg` are independently
submitted, notarized, and stapled:

1. The signed `.app` is zipped into a submission-only archive (not the
   final shipped zip), submitted via `xcrun notarytool submit --wait`, and
   on acceptance the ticket is stapled **directly to the `.app` bundle**.
   This means the `.app` inside the final shipped `.zip` carries its own
   offline-capable notarization ticket.
2. The final shipped `.zip` and `.dmg` are then built from that
   already-stapled `.app` (packaging, not code mutation -- the app is never
   modified after being signed and stapled).
3. The `.dmg` is separately signed, then independently submitted,
   notarized, and stapled as its own artifact, so it also carries a
   directly verifiable ticket without needing to be opened first.

`notarize.sh` captures the notarization submission ID and status from
`notarytool`'s JSON output; on any non-`Accepted` status it fetches
`xcrun notarytool log <submission-id>` and saves it as a workflow artifact
before failing the job (never printed to a public log without being saved
as evidence first, and never containing credential values). After stapling,
it runs `xcrun stapler validate`, the architecture-appropriate `spctl
--assess` (`--type execute` for the `.app`, `--type open --context
context:primary-signature` for the `.dmg`), and a final `codesign --verify`
-- all hard gates; none of them are downgraded to warnings.

## Required secrets

| Secret | Purpose | Format |
|---|---|---|
| `MACOS_CERTIFICATE_P12` | Developer ID Application certificate | base64-encoded `.p12` (`base64 -i cert.p12 \| pbcopy`) |
| `MACOS_CERTIFICATE_PASSWORD` | password protecting the `.p12` | plain text |
| `MACOS_SIGNING_IDENTITY` | exact identity string | e.g. `Developer ID Application: NAME (TEAMID)`, from `security find-identity -v -p codesigning` |
| `APPLE_ID` | Apple ID for notarization | email address |
| `APPLE_TEAM_ID` | Developer Team ID | e.g. `TEAMID1234`, from the Apple Developer portal |
| `APPLE_APP_SPECIFIC_PASSWORD` | app-specific password for notarization, **not** your Apple ID password | generate at appleid.apple.com -> Sign-In and Security -> App-Specific Passwords |

Configure via **Settings -> Secrets and variables -> Actions** (repository
secrets) or, preferably, scoped to the `macos-production-release`
environment. Never commit any of these values to the repository, a
workflow file, a log, or a PR. `macos-build.yml`'s `check-secrets` job
checks only presence (`secrets.X != ''`), never the value, and fails the
run early and clearly if signing/notarization is requested without its
prerequisites.

## Unsigned installation behavior (Community Edition / Mode A/B artifacts)

Gatekeeper will refuse to open an unsigned build with a plain double-click
("CHIRP.app is damaged and can't be opened" or "cannot be opened because
the developer cannot be verified"). This is expected, standard behavior
for unsigned Developer-ID-less software, not a packaging bug. See
[docs/macos-community-installation.md](macos-community-installation.md)
for the full, user-facing walkthrough (Control-click -> Open, or System
Settings -> Privacy & Security -> Open Anyway) -- do not instruct users to
disable Gatekeeper system-wide (`sudo spctl --master-disable`) or disable
System Integrity Protection.

## Signed and notarized installation behavior (Signed Edition / Mode C/D artifacts)

A properly signed, notarized, and stapled build should open normally via
double-click with no Gatekeeper warning, including fully offline (the
ticket is stapled locally, no network round-trip to Apple needed at launch
time). `spctl --assess --type execute CHIRP.app` should report `accepted`
with `source=Notarized Developer ID`.

## How to verify checksums

```bash
shasum -a 256 -c CHIRP-1.12.0-macOS-arm64.sha256.txt
# or, for a release:
shasum -a 256 -c CHIRP-1.12.0-macOS-SHA256SUMS.txt
```

## Troubleshooting

- **"CHIRP.app is damaged"**: expected for unsigned (Mode A) builds; see
  above.
- **`wx` import errors during `build_app.sh`**: confirm `python3 --version`
  reports 3.10 exactly -- wxPython 4.2.0 has no macOS wheel for 3.11/3.12.
- **Attempting a `universal2` build fails with `IncompatibleBinaryArchError`**:
  expected and confirmed -- see Supported architectures above. Do not try
  to work around it by excluding the offending package or by manually
  `lipo`-combining two native builds.
- **Notarization rejected**: the saved `notarization-log-*.json` workflow
  artifact contains Apple's exact rejection reason; also retrievable
  manually via `xcrun notarytool log <submission-id> --apple-id ...
  --team-id ... --password ...`.
- **`publish-release` fails at the independent re-verification step**: this
  means the downloaded artifact's checksum, or its provenance manifest's
  `signed`/`notarized`/version/source-SHA fields, didn't match what was
  expected -- treat this as a real signal something is wrong, not a flake to
  retry past.
- **`macos-release.yml` refuses to run past `guard`**: check the exact
  error -- most commonly `release_tag` already exists (choose a new one,
  e.g. `macos-v1.12.0.1`, rather than trying to force an overwrite) or
  `source_ref` isn't a full 40-character SHA.

## Emergency release-disable procedure

If a published macOS release needs to be pulled (e.g. a defect discovered
after publication):

1. `gh release delete <tag> --repo ddavis83864/chirp` removes the release
   and its assets (does not delete the underlying git tag by default; pass
   `--cleanup-tag` if the tag should go too).
2. This never touches `appimage-v1.12.0`, any Linux artifact, or the other
   macOS channel's release -- all three release processes are fully
   independent by tag namespace, environment, and workflow job.
3. To prevent further releases while investigating, remove the relevant
   environment's (`macos-community-release` or `macos-production-release`)
   required-reviewer list down to nobody -- this makes the corresponding
   publish job fail closed. For the signed channel, temporarily deleting
   the environment-scoped Apple secrets has the same effect.
4. Do not force-push, rewrite the tag, or re-publish under the same tag
   name; use a new `release_tag` for the corrected release.

## Certificate rotation procedure

1. Generate/export a new Developer ID Application certificate from the
   Apple Developer portal (or Keychain Access if generated locally) as a
   `.p12` with a strong password.
2. `base64 -i newcert.p12 | pbcopy`, update the `MACOS_CERTIFICATE_P12`
   secret with the new value, and `MACOS_CERTIFICATE_PASSWORD` with its
   password.
3. Update `MACOS_SIGNING_IDENTITY` if the certificate's common name or team
   ID changed (check with `security find-identity -v -p codesigning` after
   importing the new cert into a local keychain).
4. Run a Mode C (signed + notarized, no release) validation build first to
   confirm the new identity works before ever running Mode D.
5. The old certificate's secret values can be deleted once the rotation is
   confirmed working; there is nothing else in this repository that
   references a certificate by value (only by secret name).

## App-specific password rotation procedure

1. Revoke the old app-specific password at appleid.apple.com -> Sign-In and
   Security -> App-Specific Passwords.
2. Generate a new one, update `APPLE_APP_SPECIFIC_PASSWORD`.
3. Run a Mode C validation build to confirm notarization still succeeds.

## Release-operator checklists

### Community Edition

1. Confirm `source_ref` is the correct full 40-character commit SHA.
2. Confirm `release_version` matches what you intend to ship.
3. Select `release_channel=community`.
4. Confirm `enable_signing=false`.
5. Confirm `enable_notarization=false`.
6. Initially run with `enable_release_upload=false` (Mode A) to validate.
7. Confirm both `arm64` and `x86_64` build jobs pass.
8. Inspect the workflow's validation output for both architectures.
9. Download the artifacts and verify checksums yourself.
10. Review each architecture's provenance manifest.
11. Review the auto-generated release notes template for accuracy.
12. Re-run with `enable_release_upload=true` (Mode B) once satisfied --
    this requires `macos-community-release` environment approval.
13. Verify the release assets after publication (download and re-check
    checksums against the published `SHA256SUMS.txt`).

### Signed Edition

1. Confirm `source_ref`, `release_version`.
2. Select `release_channel=signed`.
3. Confirm `enable_signing=true`, `enable_notarization=true`.
4. Confirm the six Apple secrets are configured (only presence is checked
   automatically; correctness is only proven by the run itself succeeding).
5. Run with `enable_release_upload=false` (Mode C) first and review the
   signing/notarization/stapling/Gatekeeper evidence in the job logs and
   provenance manifest.
6. Only then re-run with `enable_release_upload=true` (Mode D) -- requires
   `macos-production-release` environment approval.
7. Verify the release assets after publication.

## Physical testing limitations

No physical Mac hardware, remote Mac, or GUI-interactive session was used
to author or validate this packaging -- everything above was built and
checked from a Linux development environment plus GitHub-hosted macOS CI
runners (headless, no interactive GUI login session). Concretely, this
means:

- No visible GUI rendering, dock icon appearance, window redraw behavior,
  dark/light mode, or high-DPI rendering has been confirmed.
- No physical radio (serial/USB) communication has been tested; only
  serial-port enumeration with no radio attached is exercised by CI.
- Gatekeeper's actual first-launch user experience on a real, physically
  operated Mac has not been observed, for either unsigned or signed builds.
- No Mode C/D (signed/notarized) run has ever been executed -- Apple
  Developer ID credentials are not present in this repository. Everything
  describing signing/notarization behavior above is the intended design,
  verified through static review of the scripts and workflow logic, not
  through a live signed run.

## Known limitations

- The `universal2` limitation is now a confirmed, evidence-based
  conclusion (a real failed build, not speculation) -- see Supported
  architectures.
- CI's launch smoke test (pre- and post-signing) only checks that the
  process survives 5+ seconds with no Python traceback in its log; this is
  not proof the main window rendered.
- DMG creation via `hdiutil` is not byte-for-byte deterministic (HFS+/APFS
  timestamps), though build inputs and process are reproducible.
- Signing and notarization logic is implemented and statically validated
  but has never been exercised against real Apple credentials in this
  repository.
