"""Policy tests for the macOS release-channel guards.

These tests extract and execute the *actual* bash logic from
.github/workflows/macos-build.yml and macos-release.yml (not a
reimplementation of the rules), so a change to the real guard logic that
breaks a policy is caught here rather than only discovered in CI or, worse,
by an actual bad release.

Usage: PYTHONPATH=. .venv/bin/python -m pytest packaging/macos/tests/test_release_guards.py -v
"""
import json
import os
import subprocess
import tempfile
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
BUILD_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "macos-build.yml"
RELEASE_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "macos-release.yml"
VALID_SHA = "9c38424f5e716c00e4444533a093ca1ba51258af"

APPLE_SECRET_NAMES = [
    "MACOS_CERTIFICATE_P12",
    "MACOS_CERTIFICATE_PASSWORD",
    "MACOS_SIGNING_IDENTITY",
    "APPLE_ID",
    "APPLE_TEAM_ID",
    "APPLE_APP_SPECIFIC_PASSWORD",
]


def get_step_run(workflow_path, job_name, step_name):
    with open(workflow_path) as f:
        data = yaml.safe_load(f)
    for step in data["jobs"][job_name]["steps"]:
        if step.get("name") == step_name:
            return step["run"]
    raise KeyError(f"step {step_name!r} not found in job {job_name!r} of {workflow_path}")


def run_bash(script, env, cwd=None):
    result = subprocess.run(
        ["bash", "-c", script],
        capture_output=True,
        text=True,
        env=env,
        cwd=cwd,
    )
    return result.returncode, result.stdout + result.stderr


@pytest.fixture(scope="module")
def enforce_script():
    return get_step_run(
        BUILD_WORKFLOW, "check-secrets", "Enforce channel/signing/notarization consistency"
    )


def run_enforce(script, channel, signing, notarization):
    env = dict(os.environ)
    env["RELEASE_CHANNEL"] = channel
    env["ENABLE_SIGNING"] = signing
    env["ENABLE_NOTARIZATION"] = notarization
    return run_bash(script, env)


def test_community_can_proceed_without_signing_or_notarization(enforce_script):
    rc, out = run_enforce(enforce_script, "community", "false", "false")
    assert rc == 0, out


def test_community_rejects_signing_enabled(enforce_script):
    rc, out = run_enforce(enforce_script, "community", "true", "false")
    assert rc != 0, out


def test_community_rejects_notarization_enabled(enforce_script):
    rc, out = run_enforce(enforce_script, "community", "false", "true")
    assert rc != 0, out


def test_signed_rejects_signing_disabled(enforce_script):
    rc, out = run_enforce(enforce_script, "signed", "false", "true")
    assert rc != 0, out


def test_signed_rejects_notarization_disabled(enforce_script):
    rc, out = run_enforce(enforce_script, "signed", "true", "false")
    assert rc != 0, out


def test_signed_with_both_enabled_proceeds(enforce_script):
    rc, out = run_enforce(enforce_script, "signed", "true", "true")
    assert rc == 0, out


def test_notarization_without_signing_is_rejected_community_path(enforce_script):
    rc, out = run_enforce(enforce_script, "community", "false", "true")
    assert rc != 0, out


def test_notarization_without_signing_is_rejected_signed_path(enforce_script):
    rc, out = run_enforce(enforce_script, "signed", "false", "true")
    assert rc != 0, out


@pytest.fixture(scope="module")
def failfast_script():
    return get_step_run(
        BUILD_WORKFLOW, "check-secrets", "Fail fast if signing/notarization requested without secrets"
    )


def run_failfast(script, signing, notarization, signing_secrets_present, notarization_secrets_present):
    # This step references ${{ steps.check.outputs.signing_secrets_present }}
    # and ${{ steps.check.outputs.notarization_secrets_present }} inline --
    # substitute those the same way the GitHub Actions expression engine
    # would, since this isn't running inside real Actions.
    substituted = script.replace(
        "${{ steps.check.outputs.signing_secrets_present }}", signing_secrets_present
    ).replace(
        "${{ steps.check.outputs.notarization_secrets_present }}", notarization_secrets_present
    )
    env = dict(os.environ)
    env["ENABLE_SIGNING"] = signing
    env["ENABLE_NOTARIZATION"] = notarization
    return run_bash(substituted, env)


def test_signing_requested_without_secrets_is_rejected(failfast_script):
    rc, out = run_failfast(failfast_script, "true", "false", "false", "false")
    assert rc != 0, out


def test_community_shaped_call_needs_no_secrets(failfast_script):
    rc, out = run_failfast(failfast_script, "false", "false", "false", "false")
    assert rc == 0, out


def test_signing_and_notarization_with_secrets_present_proceeds(failfast_script):
    rc, out = run_failfast(failfast_script, "true", "true", "true", "true")
    assert rc == 0, out


@pytest.fixture(scope="module")
def validate_script():
    return get_step_run(RELEASE_WORKFLOW, "guard", "Validate inputs and channel consistency")


def run_validate(script, source_ref, version, tag, channel, signing, notarization):
    env = dict(os.environ)
    env["SOURCE_REF"] = source_ref
    env["RELEASE_VERSION"] = version
    env["RELEASE_TAG"] = tag
    env["RELEASE_CHANNEL"] = channel
    env["ENABLE_SIGNING"] = signing
    env["ENABLE_NOTARIZATION"] = notarization
    env["ENABLE_RELEASE_UPLOAD"] = "true"
    # This step runs `git cat-file` against the checked-out repo, so it must
    # run with REPO_ROOT as the working directory.
    return run_bash(script, env, cwd=REPO_ROOT)


def test_community_tag_namespace_is_accepted(validate_script):
    rc, out = run_validate(
        validate_script, VALID_SHA, "1.12.0", "macos-community-v1.12.0", "community", "false", "false"
    )
    assert rc == 0, out


def test_community_channel_rejects_signed_tag_namespace(validate_script):
    rc, out = run_validate(
        validate_script, VALID_SHA, "1.12.0", "macos-v1.12.0", "community", "false", "false"
    )
    assert rc != 0, out


def test_signed_tag_namespace_is_accepted(validate_script):
    rc, out = run_validate(
        validate_script, VALID_SHA, "1.12.0", "macos-v1.12.0", "signed", "true", "true"
    )
    assert rc == 0, out


def test_signed_channel_rejects_community_tag_namespace(validate_script):
    rc, out = run_validate(
        validate_script, VALID_SHA, "1.12.0", "macos-community-v1.12.0", "signed", "true", "true"
    )
    assert rc != 0, out


def test_appimage_tag_is_rejected_for_community(validate_script):
    rc, out = run_validate(
        validate_script, VALID_SHA, "1.12.0", "appimage-v1.12.0", "community", "false", "false"
    )
    assert rc != 0, out


def test_appimage_tag_is_rejected_for_signed(validate_script):
    rc, out = run_validate(
        validate_script, VALID_SHA, "1.12.0", "appimage-v1.12.0", "signed", "true", "true"
    )
    assert rc != 0, out


# ---------------------------------------------------------------------
# Structural checks -- properties of the real workflow text itself, not
# something meaningful to execute.
# ---------------------------------------------------------------------

@pytest.fixture(scope="module")
def build_text():
    return BUILD_WORKFLOW.read_text()


@pytest.fixture(scope="module")
def release_text():
    return RELEASE_WORKFLOW.read_text()


def test_artifact_basename_appends_unsigned_suffix_for_community(build_text):
    assert "release_channel == 'community' && '-unsigned' || ''" in build_text


def test_community_release_notes_contain_unsigned_disclaimer(release_text):
    assert (
        "This Community Edition build is not signed with an Apple Developer ID "
        "and has not been notarized by Apple." in release_text
    )


def test_community_publish_job_never_references_apple_secrets():
    with open(RELEASE_WORKFLOW) as f:
        release_data = yaml.safe_load(f)
    community_job_text = yaml.dump(release_data["jobs"]["publish-community-release"])
    leaked = [name for name in APPLE_SECRET_NAMES if name in community_job_text]
    assert not leaked, f"leaked secret names: {leaked}"


def test_sign_script_still_invoked_for_signed_channel(build_text):
    assert "./packaging/macos/sign.sh \\" in build_text


def test_notarize_script_still_invoked_for_signed_channel(build_text):
    assert "./packaging/macos/notarize.sh" in build_text


def test_release_upload_defaults_to_false():
    with open(RELEASE_WORKFLOW) as f:
        release_data = yaml.safe_load(f)
    # PyYAML (1.1 spec) parses the bare `on:` key as the boolean True, not
    # the string 'on' -- index accordingly.
    on_key = True if True in release_data else "on"
    default = release_data[on_key]["workflow_dispatch"]["inputs"]["enable_release_upload"]["default"]
    assert default is False


def test_guard_refuses_existing_tag_and_never_clobbers(release_text):
    assert "already exists" in release_text
    assert "--clobber" not in release_text


def test_linux_appimage_workflow_untouched():
    result = subprocess.run(
        [
            "git", "diff", "--quiet", "feature/macos-production-release-process", "--",
            ".github/workflows/appimage.yml", "appimage/",
        ],
        cwd=REPO_ROOT,
    )
    assert result.returncode == 0


# ---------------------------------------------------------------------
# Provenance manifest signed/notarized fields -- run the actual embedded
# Python from the "Generate provenance manifest" step.
# ---------------------------------------------------------------------

@pytest.fixture(scope="module")
def community_manifest():
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
            return json.load(f)


def test_community_provenance_signed_is_false(community_manifest):
    assert community_manifest["signed"] is False


def test_community_provenance_notarized_is_false(community_manifest):
    assert community_manifest["notarized"] is False


def test_community_provenance_never_uses_null_for_booleans(community_manifest):
    for key in ("signed", "notarized", "stapled", "gatekeeper_assessed", "developer_id_signed"):
        assert community_manifest[key] is not None
