"""Coverage for chirp/_version.py and its two consumers, chirp/
__init__.py (runtime CHIRP_VERSION/CHIRP_VERSION_IS_DEV) and setup.py
(installed package version metadata) -- see chirp/_version.py's module
docstring for why there's exactly one implementation shared between
them.

Fixes the pre-existing defect where CHIRP_VERSION was a hardcoded
"py3dev" string, completely disconnected from the actual git tag/
commit a given checkout, dev install, or built AppImage came from --
so About dialogs, bug reports, and the CHIRP/<version> HTTP User-Agent
always reported the same fixed string regardless of what was actually
running.
"""

import importlib
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import chirp
from chirp import _version

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))


class DeriveVersionFromGitFormatTest(unittest.TestCase):
    """Exercises derive_version_from_git()'s output-normalization logic
    against a small, disposable git repo this test builds itself, with
    tags/commits it fully controls -- rather than depending on the
    real repository's own current tag/commit state, which changes over
    time and would make this test brittle.
    """

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.addCleanup(
            lambda: subprocess.run(['rm', '-rf', self.tmpdir]))
        self._git('init', '-q')
        self._git('config', 'user.email', 'test@example.com')
        self._git('config', 'user.name', 'Test')

    def _git(self, *args, check=True):
        return subprocess.run(
            ['git', *args], cwd=self.tmpdir, check=check,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)

    def _commit(self, message):
        with open(os.path.join(self.tmpdir, 'f'), 'a') as f:
            f.write(message + '\n')
        self._git('add', 'f')
        self._git('commit', '-q', '-m', message)

    def test_no_git_repo_at_all_returns_none(self):
        empty = tempfile.mkdtemp()
        self.addCleanup(lambda: subprocess.run(['rm', '-rf', empty]))
        self.assertIsNone(_version.derive_version_from_git(empty))

    def test_no_tags_reachable_returns_bare_sha_form(self):
        self._commit('one')
        version = _version.derive_version_from_git(self.tmpdir)
        self.assertRegex(version, r'^0\+g[0-9a-f]+$')
        self.assertTrue(_version.is_dev_version(version))

    def test_exactly_on_plain_tag_is_clean(self):
        self._commit('one')
        self._git('tag', '1.2.3')
        version = _version.derive_version_from_git(self.tmpdir)
        self.assertEqual('1.2.3', version)
        self.assertFalse(_version.is_dev_version(version))

    def test_exactly_on_appimage_prefixed_tag_strips_prefix(self):
        self._commit('one')
        self._git('tag', 'appimage-v9.9.9')
        version = _version.derive_version_from_git(self.tmpdir)
        self.assertEqual('9.9.9', version)
        self.assertFalse(_version.is_dev_version(version))

    def test_commits_past_a_tag_include_count_and_sha(self):
        self._commit('one')
        self._git('tag', 'appimage-v1.0.0')
        self._commit('two')
        self._commit('three')
        version = _version.derive_version_from_git(self.tmpdir)
        self.assertRegex(version, r'^1\.0\.0\+2\.g[0-9a-f]+$')
        self.assertTrue(_version.is_dev_version(version))

    def test_dirty_tree_on_exact_tag(self):
        self._commit('one')
        self._git('tag', '1.0.0')
        with open(os.path.join(self.tmpdir, 'f'), 'a') as f:
            f.write('uncommitted\n')
        version = _version.derive_version_from_git(self.tmpdir)
        self.assertEqual('1.0.0+dirty', version)
        self.assertTrue(_version.is_dev_version(version))

    def test_dirty_tree_past_a_tag(self):
        self._commit('one')
        self._git('tag', '1.0.0')
        self._commit('two')
        with open(os.path.join(self.tmpdir, 'f'), 'a') as f:
            f.write('uncommitted\n')
        version = _version.derive_version_from_git(self.tmpdir)
        self.assertRegex(version, r'^1\.0\.0\+1\.g[0-9a-f]+\.dirty$')
        self.assertTrue(_version.is_dev_version(version))


class IsDevVersionTest(unittest.TestCase):
    def test_clean_tag_is_not_dev(self):
        self.assertFalse(_version.is_dev_version('1.12.0'))

    def test_everything_else_is_dev(self):
        versions = ('1.12.0+3.gabcdef1', '1.12.0+dirty',
                    '1.12.0+3.gabcdef1.dirty', '0+gabcdef1',
                    '0+gabcdef1.dirty', '0+unknown')
        for version in versions:
            self.assertTrue(_version.is_dev_version(version), version)


class GetVersionFallbackChainTest(unittest.TestCase):
    """chirp.__init__._get_version()'s own fallback chain, exercised
    directly with mocks -- independent of DeriveVersionFromGitFormatTest
    above, which only covers derive_version_from_git()'s own output
    normalization, not what chirp/__init__.py does with it.
    """

    def test_prefers_live_git_over_installed_metadata(self):
        # chirp/__init__.py did `from chirp._version import
        # derive_version_from_git`, copying the name into its own
        # namespace -- patching it there (not on the chirp._version
        # module) is what actually affects chirp._get_version()'s own
        # global lookup.
        with (
            mock.patch.object(
                chirp, 'derive_version_from_git',
                return_value='1.2.3+9.gabcdef1'),
            mock.patch(
                'importlib.metadata.version',
                return_value='should not be used'),
        ):
            self.assertEqual('1.2.3+9.gabcdef1', chirp._get_version())

    def test_falls_back_to_installed_metadata_without_git(self):
        with (
            mock.patch.object(
                chirp, 'derive_version_from_git', return_value=None),
            mock.patch('importlib.metadata.version', return_value='1.2.3'),
        ):
            self.assertEqual('1.2.3', chirp._get_version())

    def test_falls_back_to_placeholder_with_neither(self):
        with (
            mock.patch.object(
                chirp, 'derive_version_from_git', return_value=None),
            mock.patch(
                'importlib.metadata.version',
                side_effect=importlib.metadata.PackageNotFoundError),
        ):
            version = chirp._get_version()
            self.assertEqual('0+unknown', version)
            self.assertTrue(_version.is_dev_version(version))


class ChirpVersionConsistencyTest(unittest.TestCase):
    def test_chirp_version_is_dev_matches_is_dev_version(self):
        self.assertEqual(_version.is_dev_version(chirp.CHIRP_VERSION),
                         chirp.CHIRP_VERSION_IS_DEV)

    def test_chirp_version_derived_from_this_checkout(self):
        # This test file runs from a real git checkout (this repo), so
        # CHIRP_VERSION should reflect it rather than any static
        # placeholder -- confirming the live-git path is actually
        # wired up, not just individually correct in isolation.
        live = _version.derive_version_from_git(_REPO_ROOT)
        self.assertIsNotNone(
            live, 'expected this test to run from a real git checkout')
        self.assertEqual(live, chirp.CHIRP_VERSION)


class MainPyDevCheckTest(unittest.TestCase):
    def test_main_py_no_longer_uses_the_fragile_string_check(self):
        # CHIRP_VERSION.endswith('dev') only ever matched the old
        # hardcoded "py3dev" placeholder -- a real git-derived dev
        # version like "1.12.0+3.gabcdef1" never ends in "dev", so the
        # automatic update-check throttle it gated would have silently
        # stopped applying to every dev build once CHIRP_VERSION
        # became git-derived. Confirms the fix (CHIRP_VERSION_IS_DEV)
        # replaced it rather than leaving both in place.
        path = os.path.join(_REPO_ROOT, 'chirp', 'wxui', 'main.py')
        with open(path) as f:
            source = f.read()
        self.assertNotIn("CHIRP_VERSION.endswith('dev')", source)
        self.assertIn('CHIRP_VERSION_IS_DEV', source)


class SetupPyVersionTest(unittest.TestCase):
    def test_setup_py_reports_a_valid_nonzero_version(self):
        result = subprocess.run(
            [sys.executable, 'setup.py', '--version'],
            cwd=_REPO_ROOT, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, timeout=60)
        self.assertEqual(0, result.returncode, result.stdout)
        version = result.stdout.strip().splitlines()[-1]
        self.assertNotEqual('0', version)
        self.assertEqual(version, _version.derive_version_from_git(
            _REPO_ROOT))
