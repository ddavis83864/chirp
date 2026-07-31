# macOS packaging

This describes how `CHIRP.app` is built, signed, notarized, and released for
macOS from this fork, and how it relates to the existing `appimage-v1.12.0`
Linux release.

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
- `build_dmg` -- also build the DMG (default `true`)
- `enable_signing` / `enable_notarization` -- both default `false`; the
  workflow fails fast in a dedicated `check-secrets` job if either is
  requested without its required secrets configured, before spending any
  macOS runner time

### `.github/workflows/macos-release.yml`

The **only** workflow authorized to publish a macOS GitHub release. Runs on
`workflow_dispatch` only. Calls `macos-build.yml` internally, then adds a
`publish-release` job gated on all of:

1. `enable_signing=true` **and** `enable_notarization=true` **and**
   `enable_release_upload=true` (all three, not just the upload flag);
2. the protected `macos-production-release` GitHub Environment approving
   the run (see below);
3. the `guard` job's pre-flight checks passing (valid inputs, `release_tag`
   doesn't already exist as a tag or release, `release_tag` is in the
   `macos-v*` namespace and can never collide with `appimage-*`, working
   tree clean);
4. every architecture's build+sign+notarize job succeeding;
5. an **independent** re-verification in `publish-release` itself: downloads
   every architecture's artifacts fresh, recomputes SHA-256 and compares
   against the recorded checksums, and parses each architecture's
   provenance manifest to confirm `signed: true` and `notarized: true` --
   not just trusting that the upstream job claimed success.

Inputs: `source_ref` (must be a full 40-character SHA for a release, unlike
the build workflow which accepts a tag name with a warning), `release_version`,
`architectures` (default `arm64,x86_64` -- `universal2` is refused at
publish time), `enable_signing`, `enable_notarization`, `enable_release_upload`,
`release_tag` (default `macos-v1.12.0`), `release_name`, `prerelease`
(default `true`).

Safe defaults: `enable_signing=false`, `enable_notarization=false`,
`enable_release_upload=false`, `prerelease=true`.

## Modes

| Mode | signing | notarization | release upload | Result |
|---|---|---|---|---|
| A | false | false | false | Unsigned validation build. `.zip`/`.dmg` as workflow artifacts only. |
| B | true | true | false | Signed, notarized, stapled release-candidate artifacts as workflow artifacts. No release. |
| C | true | true | true | Everything Mode B does, plus a real macOS-only GitHub release, gated by the protected environment. |

Mode C is structurally impossible unless Mode B's signing and notarization
both genuinely succeeded in the *same* triggered run -- `publish-release`
depends on `build-sign-notarize` and independently re-verifies its output
rather than trusting a flag.

## Protected environment: `macos-production-release`

`macos-release.yml`'s `publish-release` job targets a GitHub Environment
named `macos-production-release`. This repository's automation can create
the empty environment shell via the API, but **cannot** configure
protection rules (that requires a human with repo admin access in the
GitHub UI). The repo owner should configure, under
**Settings -> Environments -> macos-production-release**:

- **Required reviewers**: at least one person who must approve before
  `publish-release` runs, even if all automated gates pass.
- **Deployment branch/ref policy**: restrict which branches/refs may
  deploy to this environment (e.g. only `feature/macos-production-release-process`
  or, once merged, `master`).
- **Prevent self-review**, if your plan tier supports it, so the person who
  triggered the run cannot also be the approver.
- **Wait timer**, if you want a mandatory cooling-off period before
  publication proceeds even after approval.
- **Environment secrets**: consider moving `MACOS_CERTIFICATE_P12`,
  `MACOS_CERTIFICATE_PASSWORD`, `MACOS_SIGNING_IDENTITY`, `APPLE_ID`,
  `APPLE_TEAM_ID`, and `APPLE_APP_SPECIFIC_PASSWORD` into
  environment-scoped secrets on `macos-production-release` instead of (or
  in addition to) repository-level secrets, so they're only readable when a
  run is actually deploying to that environment.

None of these protection settings exist yet -- only the bare environment
was created. Do not treat Mode C as safe to run until they're configured.

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

```text
CHIRP-1.12.0-macOS-arm64.app.zip
CHIRP-1.12.0-macOS-arm64.dmg
CHIRP-1.12.0-macOS-x86_64.app.zip
CHIRP-1.12.0-macOS-x86_64.dmg
CHIRP-1.12.0-macOS-SHA256SUMS.txt   (release only -- combined checksums for all published macOS artifacts, generated by macos-release.yml; never contains Linux checksums, and the Linux AppImage's own checksum process never contains macOS entries)
```

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
codebase reads `DYLD_*` at runtime). If a real Mode B (signed) run ever
fails with a library-validation or dyld-related error, add the specific
entitlement back with that exact failure documented above it in the file --
not preemptively. No Mode B run has been possible yet; Apple Developer ID
credentials are not configured in this repository.

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

## Unsigned installation behavior (Mode A artifacts)

Gatekeeper will refuse to open an unsigned build with a plain double-click
("CHIRP.app is damaged and can't be opened" or "cannot be opened because
the developer cannot be verified"). To run it anyway: right-click ->
Open -> Open, or:

```bash
xattr -dr com.apple.quarantine /Applications/CHIRP.app
```

This is expected, standard behavior for unsigned Developer-ID-less
software, not a packaging bug.

## Signed and notarized installation behavior (Mode B/C artifacts)

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
2. This never touches `appimage-v1.12.0` or any Linux artifact -- the two
   release processes are fully independent by tag namespace and workflow.
3. To prevent further releases while investigating, remove or rotate the
   `macos-production-release` environment's required-reviewer list down to
   nobody, or temporarily delete the environment-scoped secrets -- either
   makes `publish-release` fail closed.
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
4. Run a Mode B (signed + notarized, no release) validation build first to
   confirm the new identity works before ever running Mode C.
5. The old certificate's secret values can be deleted once the rotation is
   confirmed working; there is nothing else in this repository that
   references a certificate by value (only by secret name).

## App-specific password rotation procedure

1. Revoke the old app-specific password at appleid.apple.com -> Sign-In and
   Security -> App-Specific Passwords.
2. Generate a new one, update `APPLE_APP_SPECIFIC_PASSWORD`.
3. Run a Mode B validation build to confirm notarization still succeeds.

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
- No Mode B (signed/notarized) run has ever been executed -- Apple
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
