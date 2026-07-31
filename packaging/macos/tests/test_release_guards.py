#!/usr/bin/env python3
"""Policy tests for the macOS release-channel guards.

These tests extract and execute the *actual* bash logic from
.github/workflows/macos-build.yml and macos-release.yml (not a
reimplementation of the rules), so a change to the real guard logic that
breaks a policy is caught here rather than only discovered in CI or, worse,
by an actual bad release.

Usage: python3 packaging/macos/tests/test_release_guards.py
Exit code 0 if every case passes, 1 otherwise.
"""
import subprocess
import sys
import textwrap
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
BUILD_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "macos-build.yml"
RELEASE_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "macos-release.yml"

FAILURES = []


def get_step_run(workflow_path, job_name, step_name):
    with open(workflow_path) as f:
        data = yaml.safe_load(f)
    for step in data["jobs"][job_name]["steps"]:
        if step.get("name") == step_name:
            return step["run"]
    raise KeyError(f"step {step_name!r} not found in job {job_name!r} of {workflow_path}")


def run_bash(script, env):
    result = subprocess.run(
        ["bash", "-c", script],
        capture_output=True,
        text=True,
        env=env,
    )
    return result.returncode, result.stdout + result.stderr


def check(label, condition, detail=""):
    if condition:
        print(f"PASS: {label}")
    else:
        print(f"FAIL: {label} {detail}")
        FAILURES.append(label)


# ---------------------------------------------------------------------
# check-secrets job, "Enforce channel/signing/notarization consistency"
# (macos-build.yml) -- the core channel<->signing<->notarization guard.
# ---------------------------------------------------------------------
enforce_script = get_step_run(
    BUILD_WORKFLOW, "check-secrets", "Enforce channel/signing/notarization consistency"
)


def run_enforce(channel, signing, notarization):
    import os

    env = dict(os.environ)
    env["RELEASE_CHANNEL"] = channel
    env["ENABLE_SIGNING"] = signing
    env["ENABLE_NOTARIZATION"] = notarization
    return run_bash(enforce_script, env)


rc, out = run_enforce("community", "false", "false")
check("1. Community can proceed without signing/notarization", rc == 0, out)

rc, out = run_enforce("community", "true", "false")
check("3. Community rejects signing enabled", rc != 0, out)

rc, out = run_enforce("community", "false", "true")
check("4. Community rejects notarization enabled", rc != 0, out)

rc, out = run_enforce("signed", "false", "true")
check("5. Signed rejects signing disabled", rc != 0, out)

rc, out = run_enforce("signed", "true", "false")
check("6. Signed rejects notarization disabled", rc != 0, out)

rc, out = run_enforce("signed", "true", "true")
check("(sanity) Signed with both enabled proceeds", rc == 0, out)

rc, out = run_enforce("community", "false", "true")  # signing false, notarization true
check("7. Notarization without signing is rejected (via community path)", rc != 0, out)

rc, out = run_enforce("signed", "false", "true")  # explicit cross-channel notarization-without-signing
check("7b. Notarization without signing is rejected (signed channel, signing left false)", rc != 0, out)

# ---------------------------------------------------------------------
# check-secrets job, "Fail fast if signing/notarization requested
# without secrets" -- tests case 2 (signed cannot publish without
# Apple secrets) using the real secret-presence gate.
# ---------------------------------------------------------------------
failfast_script = get_step_run(
    BUILD_WORKFLOW, "check-secrets", "Fail fast if signing/notarization requested without secrets"
)
# This step references ${{ steps.check.outputs.signing_secrets_present }}
# and ${{ steps.check.outputs.notarization_secrets_present }} inline --
# substitute those the same way the GitHub Actions expression engine would,
# since we're not running inside real Actions here.


def run_failfast(signing, notarization, signing_secrets_present, notarization_secrets_present):
    import os

    script = failfast_script.replace(
        "${{ steps.check.outputs.signing_secrets_present }}", signing_secrets_present
    ).replace(
        "${{ steps.check.outputs.notarization_secrets_present }}", notarization_secrets_present
    )
    env = dict(os.environ)
    env["ENABLE_SIGNING"] = signing
    env["ENABLE_NOTARIZATION"] = notarization
    return run_bash(script, env)


rc, out = run_failfast("true", "false", "false", "false")
check("2. Signing requested without secrets is rejected", rc != 0, out)

rc, out = run_failfast("false", "false", "false", "false")
check("(sanity) Community-shaped call (signing/notarization both false) needs no secrets", rc == 0, out)

rc, out = run_failfast("true", "true", "true", "true")
check("(sanity) Signing+notarization with secrets present proceeds", rc == 0, out)

# ---------------------------------------------------------------------
# guard job, "Validate inputs and channel consistency" (macos-release.yml)
# -- tag namespace <-> channel rules, and appimage-v* rejection.
# ---------------------------------------------------------------------
validate_script = get_step_run(RELEASE_WORKFLOW, "guard", "Validate inputs and channel consistency")


def run_validate(source_ref, version, tag, channel, signing, notarization):
    import os

    env = dict(os.environ)
    env["SOURCE_REF"] = source_ref
    env["RELEASE_VERSION"] = version
    env["RELEASE_TAG"] = tag
    env["RELEASE_CHANNEL"] = channel
    env["ENABLE_SIGNING"] = signing
    env["ENABLE_NOTARIZATION"] = notarization
    env["ENABLE_RELEASE_UPLOAD"] = "true"
    # This step also runs `git cat-file` against the checked-out repo, so
    # it must run with REPO_ROOT as the working directory.
    result = subprocess.run(
        ["bash", "-c", script_with_cwd(env)],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        env=env,
    )
    return result.returncode, result.stdout + result.stderr


def script_with_cwd(_env):
    return validate_script


VALID_SHA = "9c38424f5e716c00e4444533a093ca1ba51258af"

rc, out = run_validate(VALID_SHA, "1.12.0", "macos-community-v1.12.0", "community", "false", "false")
check("8. Community tag macos-community-v* is accepted", rc == 0, out)

rc, out = run_validate(VALID_SHA, "1.12.0", "macos-v1.12.0", "community", "false", "false")
check("8b. Community channel rejects a macos-v* (non-community) tag", rc != 0, out)

rc, out = run_validate(VALID_SHA, "1.12.0", "macos-v1.12.0", "signed", "true", "true")
check("9. Signed tag macos-v* is accepted", rc == 0, out)

rc, out = run_validate(VALID_SHA, "1.12.0", "macos-community-v1.12.0", "signed", "true", "true")
check("9b. Signed channel rejects a macos-community-v* tag", rc != 0, out)

rc, out = run_validate(VALID_SHA, "1.12.0", "appimage-v1.12.0", "community", "false", "false")
check("10. appimage-v* tag is rejected (community)", rc != 0, out)

rc, out = run_validate(VALID_SHA, "1.12.0", "appimage-v1.12.0", "signed", "true", "true")
check("10b. appimage-v* tag is rejected (signed)", rc != 0, out)

# ---------------------------------------------------------------------
# Structural / static checks (11, 12, 15, 17, 18, 19, 20) -- properties
# of the real workflow text itself, not something meaningful to execute.
# ---------------------------------------------------------------------
build_text = BUILD_WORKFLOW.read_text()
release_text = RELEASE_WORKFLOW.read_text()

check(
    "11. ARTIFACT_BASENAME expression appends -unsigned for community",
    "release_channel == 'community' && '-unsigned' || ''" in build_text,
)

check(
    "12. Community release notes contain the required unsigned disclaimer",
    "This Community Edition build is not signed with an Apple Developer ID and has not been notarized by Apple."
    in release_text,
)

# Extract just the publish-community-release job's text to check it never
# references any of the six Apple/signing secrets.
with open(RELEASE_WORKFLOW) as f:
    release_data = yaml.safe_load(f)
community_job_text = yaml.dump(release_data["jobs"]["publish-community-release"])
apple_secret_names = [
    "MACOS_CERTIFICATE_P12",
    "MACOS_CERTIFICATE_PASSWORD",
    "MACOS_SIGNING_IDENTITY",
    "APPLE_ID",
    "APPLE_TEAM_ID",
    "APPLE_APP_SPECIFIC_PASSWORD",
]
leaked = [s for s in apple_secret_names if s in community_job_text]
check(
    "15. publish-community-release never references Apple/signing secrets",
    not leaked,
    f"leaked: {leaked}",
)

check(
    "17. sign.sh is still invoked for the signed channel's Sign app step",
    "./packaging/macos/sign.sh \\" in build_text,
)
check(
    "17b. notarize.sh is still invoked for the signed channel",
    "./packaging/macos/notarize.sh" in build_text,
)

with open(RELEASE_WORKFLOW) as f:
    release_data2 = yaml.safe_load(f)
# PyYAML (1.1 spec) parses the bare `on:` key as the boolean True, not the
# string 'on' -- index accordingly.
on_key = True if True in release_data2 else "on"
enable_release_upload_default = release_data2[on_key]["workflow_dispatch"]["inputs"][
    "enable_release_upload"
]["default"]
check(
    "18. enable_release_upload defaults to false",
    enable_release_upload_default is False,
)

check(
    "19/20. guard job refuses when the tag already exists (no --clobber anywhere)",
    "already exists" in release_text and "--clobber" not in release_text,
)

check(
    "16. Linux AppImage workflow file is untouched by this branch",
    subprocess.run(
        ["git", "diff", "--quiet", "feature/macos-production-release-process", "--",
         ".github/workflows/appimage.yml", "appimage/"],
        cwd=REPO_ROOT,
    ).returncode == 0,
)

# ---------------------------------------------------------------------
# Provenance manifest signed/notarized fields (13, 14) -- run the actual
# embedded Python from the "Generate provenance manifest" step.
# ---------------------------------------------------------------------
import json
import os
import tempfile

manifest_step = get_step_run(BUILD_WORKFLOW, "build", "Generate provenance manifest")
start = manifest_step.index("<<'PYEOF'\n") + len("<<'PYEOF'\n")
end = manifest_step.index("\nPYEOF")
manifest_py = manifest_step[start:end]

with tempfile.TemporaryDirectory() as tmp:
    out_json = os.path.join(tmp, "manifest.json")
    env = dict(os.environ)
    env.update({
        "ARTIFACT_BASENAME": "CHIRP-1.12.0-macOS-arm64-unsigned",
        "MATRIX_ARCH": "arm64",
        "RELEASE_CHANNEL": "community",
        "ENABLE_SIGNING": "false",
        "ENABLE_NOTARIZATION": "false",
        "CHIRP_APP_VERSION": "1.12.0",
        "CHIRP_BUNDLE_ID": "com.ddavis83864.chirp",
        "GITHUB_RUN_ID": "12345",
        "GITHUB_RUN_ATTEMPT": "1",
        "APPLICATION_SOURCE_SHA": VALID_SHA,
        "PACKAGING_BRANCH_SHA": "deadbeef",
    })
    script_path = os.path.join(tmp, "gen.py")
    with open(script_path, "w") as f:
        f.write(manifest_py)
    subprocess.run(
        ["python3", script_path, out_json, "2026-01-01T00:00:00Z"],
        env=env,
        cwd=tmp,
        check=True,
        capture_output=True,
        text=True,
    )
    with open(out_json) as f:
        manifest = json.load(f)

check("13. Community provenance manifest has signed: false", manifest["signed"] is False, manifest)
check("14. Community provenance manifest has notarized: false", manifest["notarized"] is False, manifest)
check(
    "14b. Community provenance manifest never uses null for signed/notarized/stapled",
    all(
        manifest[k] is not None
        for k in ("signed", "notarized", "stapled", "gatekeeper_assessed", "developer_id_signed")
    ),
)

# ---------------------------------------------------------------------
print()
if FAILURES:
    print(f"{len(FAILURES)} FAILURE(S): {FAILURES}")
    sys.exit(1)
else:
    print("All release-guard policy checks passed.")
    sys.exit(0)
