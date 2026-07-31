#!/usr/bin/env python3
"""Generates build-provenance.json for a Windows CHIRP release build.

Mirrors the per-architecture manifest generated for the macOS build
(see .github/workflows/macos-build.yml) and the combined
CHIRP-<version>-macOS-Community-PROVENANCE.json produced at release time,
adapted to this task's single build-provenance.json schema and to
Windows having exactly one supported architecture (x86_64).

Every value is passed in explicitly by the caller (the build-windows.ps1
script or the windows-release.yml workflow) rather than guessed here --
this script's only job is to assemble and validate the JSON, not to
determine what the "true" values are.
"""
import argparse
import json
import logging
import sys

logging.basicConfig(level=logging.INFO, format='%(message)s')
LOG = logging.getLogger(__name__)

SCHEMA_VERSION = 1


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', required=True,
                    help='Path to write build-provenance.json to')
    p.add_argument('--repository', default='ddavis83864/chirp')
    p.add_argument('--release-family', default='v1.12.0')
    p.add_argument('--application-version', required=True,
                    help='e.g. v1.12.0')
    p.add_argument('--architecture', default='x86_64')
    p.add_argument('--source-commit', required=True,
                    help='Full 40-character commit SHA of the pinned '
                         'application source actually packaged')
    p.add_argument('--source-ref', required=True,
                    help='Branch or tag the packaging infrastructure was '
                         'built from')
    p.add_argument('--linux-release', default='appimage-v1.12.0')
    p.add_argument('--linux-source-commit', required=True)
    p.add_argument('--macos-release', default='macos-community-v1.12.0')
    p.add_argument('--macos-source-commit', required=True)
    p.add_argument('--source-equivalence-verified', required=True,
                    choices=['true', 'false'],
                    help='"true" only if windows/linux/macos source '
                         'commits were independently confirmed identical')
    p.add_argument('--build-timestamp-utc', required=True,
                    help='ISO-8601 UTC timestamp, e.g. from '
                         '`date -u +%%Y-%%m-%%dT%%H:%%M:%%SZ`')
    p.add_argument('--runner-image', required=True)
    p.add_argument('--python-version', required=True)
    p.add_argument('--pyinstaller-version', required=True)
    p.add_argument('--installer-tool-version', required=True)
    p.add_argument('--workflow-name', required=True)
    p.add_argument('--workflow-run-id', required=True)
    p.add_argument('--workflow-run-attempt', required=True)
    p.add_argument(
        '--artifact', action='append', default=[], dest='artifacts',
        metavar='FILENAME=SHA256',
        help='Repeatable. One artifact filename/hash pair, e.g. '
             '--artifact CHIRP-windows-v1.12.0-x86_64-portable.zip=<hash>')
    return p.parse_args(argv)


def build_provenance(args):
    artifacts = []
    for item in args.artifacts:
        if '=' not in item:
            raise ValueError(
                f"--artifact value {item!r} must be FILENAME=SHA256")
        filename, sha256 = item.split('=', 1)
        sha256 = sha256.strip().lower()
        if len(sha256) != 64 or any(c not in '0123456789abcdef'
                                     for c in sha256):
            raise ValueError(
                f"--artifact {filename!r} has a malformed sha256 value "
                f"({sha256!r}); expected 64 hex characters")
        artifacts.append({'filename': filename, 'sha256': sha256})

    source_equivalence_verified = args.source_equivalence_verified == 'true'
    if source_equivalence_verified:
        if not (args.source_commit == args.linux_source_commit
                == args.macos_source_commit):
            raise ValueError(
                'source_equivalence_verified=true was requested, but '
                'source-commit/linux-source-commit/macos-source-commit '
                'are not all identical -- refusing to write a provenance '
                'file that falsely claims source equivalence. Pass '
                '--source-equivalence-verified false if the commits '
                'genuinely differ, and explain why in the release notes.')

    return {
        'schema_version': SCHEMA_VERSION,
        'repository': args.repository,
        'release_family': args.release_family,
        'application_version': args.application_version,
        'platform': 'windows',
        'architecture': args.architecture,
        'source_commit': args.source_commit,
        'source_ref': args.source_ref,
        'linux_release': args.linux_release,
        'linux_source_commit': args.linux_source_commit,
        'macos_release': args.macos_release,
        'macos_source_commit': args.macos_source_commit,
        'windows_source_commit': args.source_commit,
        'source_equivalence_verified': source_equivalence_verified,
        'build_timestamp_utc': args.build_timestamp_utc,
        'runner_os': 'Windows',
        'runner_image': args.runner_image,
        'python_version': args.python_version,
        'pyinstaller_version': args.pyinstaller_version,
        'installer_tool': 'Inno Setup',
        'installer_tool_version': args.installer_tool_version,
        'workflow_name': args.workflow_name,
        'workflow_run_id': args.workflow_run_id,
        'workflow_run_attempt': args.workflow_run_attempt,
        'artifacts': artifacts,
        'code_signing': {
            'signed': False,
            'status': 'unsigned-community-prerelease',
        },
    }


def main(argv=None):
    args = parse_args(argv)
    try:
        provenance = build_provenance(args)
    except ValueError as exc:
        LOG.error("error: %s", exc)
        return 1

    text = json.dumps(provenance, indent=2, sort_keys=False)
    # Validate round-trip before writing anything to disk.
    json.loads(text)

    with open(args.output, 'w', encoding='utf-8', newline='\n') as f:
        f.write(text)
        f.write('\n')

    LOG.info("Wrote %s", args.output)
    LOG.info("%s", text)
    return 0


if __name__ == '__main__':
    sys.exit(main())
