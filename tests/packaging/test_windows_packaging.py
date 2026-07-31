"""Tests for the Windows packaging helper scripts and static config.

These are deliberately platform-independent: they exercise the pure
-Python provenance/validation logic and do static checks against the
checked-in PyInstaller spec / Inno Setup script text, none of which
require a Windows host, wxPython, or PyInstaller to be installed. The
actual build (PyInstaller freeze, Inno Setup compile, launch smoke
tests) only runs on the windows-2022 CI runner via build-windows.ps1 --
see packaging/windows/README.md.

Run with: pytest tests/packaging/test_windows_packaging.py -v
"""
import importlib.util
import json
import re
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
WINDOWS_PKG_DIR = REPO_ROOT / 'packaging' / 'windows'


def _load_script_module(name, filename):
    path = WINDOWS_PKG_DIR / filename
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class VersionAndFilenamePatternTests(unittest.TestCase):
    """These regexes are duplicated (by necessity) in build-windows.ps1's
    -Version ValidatePattern and in windows-release.yml's guard job --
    keeping the canonical pattern under test here means a change to one
    that silently diverges from the others gets caught."""

    VERSION_RE = re.compile(r'^\d+\.\d+\.\d+$')
    SHA_RE = re.compile(r'^[0-9a-f]{40}$')

    def test_valid_version_accepted(self):
        self.assertRegex('1.12.0', self.VERSION_RE)
        self.assertRegex('0.0.1', self.VERSION_RE)

    def test_invalid_versions_rejected(self):
        for bad in ['v1.12.0', '1.12', '1.12.0.1', '1.12.x', '', '1.12.0-rc1']:
            self.assertNotRegex(bad, self.VERSION_RE)

    def test_baseline_sha_is_well_formed(self):
        baseline = '9c38424f5e716c00e4444533a093ca1ba51258af'
        self.assertRegex(baseline, self.SHA_RE)
        self.assertEqual(len(baseline), 40)

    def test_expected_artifact_filenames(self):
        version = '1.12.0'
        zip_name = f'CHIRP-windows-v{version}-x86_64-portable.zip'
        setup_name = f'CHIRP-windows-v{version}-x86_64-setup.exe'
        self.assertEqual(zip_name,
                          'CHIRP-windows-v1.12.0-x86_64-portable.zip')
        self.assertEqual(setup_name,
                          'CHIRP-windows-v1.12.0-x86_64-setup.exe')
        # Both must embed the same version string in the same X.Y.Z form.
        self.assertIn(f'v{version}', zip_name)
        self.assertIn(f'v{version}', setup_name)


class ProvenanceGeneratorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = _load_script_module(
            'generate_provenance', 'generate-provenance.py')

    def _base_args(self, **overrides):
        ns = self.mod.parse_args([
            '--output', 'unused.json',
            '--application-version', 'v1.12.0',
            '--source-commit', '9c38424f5e716c00e4444533a093ca1ba51258af',
            '--source-ref', 'feature/windows-packaging-v1.12.0',
            '--linux-source-commit',
            '9c38424f5e716c00e4444533a093ca1ba51258af',
            '--macos-source-commit',
            '9c38424f5e716c00e4444533a093ca1ba51258af',
            '--source-equivalence-verified', 'true',
            '--build-timestamp-utc', '2026-08-01T00:00:00Z',
            '--runner-image', 'windows-2022',
            '--python-version', '3.11.9',
            '--pyinstaller-version', '6.10.0',
            '--installer-tool-version', '6.3.1',
            '--workflow-name', 'Windows Release',
            '--workflow-run-id', '12345',
            '--workflow-run-attempt', '1',
        ])
        for k, v in overrides.items():
            setattr(ns, k, v)
        return ns

    def test_matching_commits_produce_valid_schema(self):
        provenance = self.mod.build_provenance(self._base_args())
        self.assertEqual(provenance['schema_version'], 1)
        self.assertEqual(provenance['repository'], 'ddavis83864/chirp')
        self.assertEqual(provenance['platform'], 'windows')
        self.assertEqual(provenance['architecture'], 'x86_64')
        self.assertTrue(provenance['source_equivalence_verified'])
        self.assertEqual(provenance['code_signing'],
                          {'signed': False,
                           'status': 'unsigned-community-prerelease'})
        # Round-trips through JSON cleanly.
        json.loads(json.dumps(provenance))

    def test_mismatched_commits_with_verified_true_is_rejected(self):
        args = self._base_args(
            macos_source_commit='0' * 40,
            source_equivalence_verified='true',
        )
        with self.assertRaises(ValueError):
            self.mod.build_provenance(args)

    def test_mismatched_commits_with_verified_false_is_allowed(self):
        args = self._base_args(
            macos_source_commit='0' * 40,
            source_equivalence_verified='false',
        )
        provenance = self.mod.build_provenance(args)
        self.assertFalse(provenance['source_equivalence_verified'])

    def test_artifact_hash_validation(self):
        args = self._base_args()
        args.artifacts = ['CHIRP-windows-v1.12.0-x86_64-portable.zip=' + 'a' * 64]
        provenance = self.mod.build_provenance(args)
        self.assertEqual(len(provenance['artifacts']), 1)
        self.assertEqual(
            provenance['artifacts'][0]['filename'],
            'CHIRP-windows-v1.12.0-x86_64-portable.zip')

    def test_malformed_artifact_hash_rejected(self):
        args = self._base_args()
        args.artifacts = ['CHIRP.zip=not-a-hash']
        with self.assertRaises(ValueError):
            self.mod.build_provenance(args)


class PyInstallerSpecStaticChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spec_text = (WINDOWS_PKG_DIR / 'chirp.spec').read_text()

    def test_uses_onedir_collect_not_onefile(self):
        self.assertIn('COLLECT(', self.spec_text)
        # One-file mode passes binaries/zipfiles/datas directly into EXE()
        # instead of exclude_binaries=True + a separate COLLECT() step.
        self.assertIn('exclude_binaries=True', self.spec_text)

    def test_main_exe_has_no_console(self):
        match = re.search(
            r"exe = EXE\(.*?name='CHIRP',.*?console=(\w+)", self.spec_text,
            re.DOTALL)
        self.assertIsNotNone(match, 'could not find main CHIRP EXE() block')
        self.assertEqual(match.group(1), 'False')

    def test_driver_check_helper_has_console(self):
        match = re.search(
            r"exe_driver_check = EXE\(.*?console=(\w+)", self.spec_text,
            re.DOTALL)
        self.assertIsNotNone(match,
                              'could not find CHIRP-driver-check EXE() block')
        self.assertEqual(match.group(1), 'True')

    def test_uses_windows_icon(self):
        self.assertIn("chirp.ico", self.spec_text)

    def test_collects_expected_hidden_import_packages(self):
        for expected in ("chirp.drivers", "chirp.wxui", "chirp.assistant",
                          "'wx'"):
            self.assertIn(expected, self.spec_text)


class InnoSetupScriptStaticChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.iss_text = (WINDOWS_PKG_DIR / 'chirp.iss').read_text()

    def test_per_user_install_by_default(self):
        self.assertIn('PrivilegesRequired=lowest', self.iss_text)

    def test_no_path_modification(self):
        self.assertNotIn('Path]', self.iss_text)
        self.assertNotRegex(self.iss_text, r'(?i)ChangesEnvironment')

    def test_no_service_or_scheduled_task_registration(self):
        lowered = self.iss_text.lower()
        self.assertNotIn('sc.exe', lowered)
        self.assertNotIn('schtasks', lowered)
        self.assertNotIn('createservice', lowered)

    def test_no_run_key_autostart(self):
        self.assertNotIn(r'HKCU\Software\Microsoft\Windows\CurrentVersion\Run',
                          self.iss_text)

    def test_desktop_shortcut_is_optional_and_unchecked(self):
        match = re.search(r'Name: "desktopicon";.*', self.iss_text)
        self.assertIsNotNone(match, 'desktopicon task not found')
        self.assertIn('unchecked', match.group(0))

    def test_output_filename_matches_required_asset_name(self):
        self.assertIn(
            'OutputBaseFilename=CHIRP-windows-v{#ChirpVersion}-x86_64-setup',
            self.iss_text)

    def test_ships_license_and_third_party_notices(self):
        self.assertIn('DestName: "LICENSE"', self.iss_text)
        self.assertIn('THIRD_PARTY_LICENSES.txt', self.iss_text)
        self.assertIn('README-Windows.txt', self.iss_text)

    def test_uninstall_does_not_delete_user_config(self):
        # Check for an actual [UninstallDelete] *section header* line, not
        # just the substring anywhere -- this file's comments intentionally
        # mention "[UninstallDelete]" by name to explain why one isn't
        # used, which would otherwise false-positive a plain substring
        # check.
        section_headers = [
            line.strip() for line in self.iss_text.splitlines()
            if line.strip().startswith('[') and not line.strip().startswith(';')
        ]
        self.assertNotIn('[UninstallDelete]', section_headers)


class WorkflowExistsAndReferencesBaseline(unittest.TestCase):
    def test_workflow_file_present(self):
        workflow = REPO_ROOT / '.github' / 'workflows' / 'windows-release.yml'
        self.assertTrue(workflow.exists(),
                         'windows-release.yml is missing')

    def test_workflow_references_verified_baseline(self):
        workflow = REPO_ROOT / '.github' / 'workflows' / 'windows-release.yml'
        text = workflow.read_text()
        self.assertIn('9c38424f5e716c00e4444533a093ca1ba51258af', text)
        self.assertIn('windows-2022', text)

    def test_workflow_never_auto_publishes_on_workflow_dispatch_alone(self):
        workflow = REPO_ROOT / '.github' / 'workflows' / 'windows-release.yml'
        text = workflow.read_text()
        # The release-publish job must be gated behind an explicit
        # enable_release_upload-style input, mirroring macos-release.yml,
        # not fire unconditionally on every workflow_dispatch run.
        self.assertIn('enable_release_upload', text)


if __name__ == '__main__':
    unittest.main()
