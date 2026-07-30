"""Regression coverage for headless-CI compatibility of
tests/unit/test_wxui_programming_assistant.py.

That file used to construct a real wx.App() unconditionally at module
import time (`_APP = wx.App()`), which requires a real or virtual X
display. Headless CI (this repo's GitHub Actions workflow and its
composite py3-tox action set up no Xvfb or other virtual display
anywhere) has none, so wx.App() raised SystemExit during collection --
aborting the *entire* `pytest tests/unit` run before any test in any
file could execute, not just this one file's own tests.

Fixed by making wx.App() construction lazy (test_wxui_programming_
assistant.py's _ensure_wx_app()), called only from the setUp()/test
methods that actually need a real wx.Frame, converting the SystemExit
into a clean per-test skip instead of a collection-time crash.

This can only be verified in a genuinely separate process with
DISPLAY/WAYLAND_DISPLAY unset -- not from calls made within an
already-running (and therefore already-displayed) test process. Each
test here launches an isolated subprocess and asserts the outcome;
several of them fail against the pre-fix implementation and pass
against the fix, confirmed by direct comparison before finalizing.
"""

import os
import re
import subprocess
import sys
import unittest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))


class ProgrammingAssistantHeadlessRegressionTest(unittest.TestCase):
    def _env_without_display(self):
        env = dict(os.environ)
        env.pop('DISPLAY', None)
        env.pop('WAYLAND_DISPLAY', None)
        env['CHIRP_TESTENV'] = '1'
        env['PYTHONPATH'] = _REPO_ROOT
        return env

    def _run(self, args, env, timeout=120):
        return subprocess.run(
            [sys.executable, *args], cwd=_REPO_ROOT, env=env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            timeout=timeout)

    def test_module_imports_without_display(self):
        # The narrowest possible reproduction of the original bug:
        # just importing the module, with no pytest involved at all,
        # used to raise SystemExit before this fix.
        result = self._run(
            ['-c',
             'import sys\n'
             'import tests.unit.test_wxui_programming_assistant\n'
             'sys.stdout.write("OK\\n")'],
            self._env_without_display(), timeout=60)
        self.assertEqual(0, result.returncode, result.stdout)
        self.assertIn('OK', result.stdout)

    def test_focused_collection_and_execution_succeed_without_display(self):
        result = self._run(
            ['-m', 'pytest', '-q',
             'tests/unit/test_wxui_programming_assistant.py'],
            self._env_without_display())
        self.assertEqual(0, result.returncode, result.stdout)
        self.assertNotIn('ERROR collecting', result.stdout)
        self.assertNotIn('INTERNALERROR', result.stdout)
        self.assertRegex(result.stdout, r'\d+ passed')

    def test_full_unit_directory_collection_succeeds_without_display(self):
        # The actual originally-reported symptom: the whole
        # `pytest tests/unit -k "not network"` run aborted at
        # *collection*, before any test in any file could execute --
        # collect-only (not a full execution) directly proves that's
        # fixed. Deliberately not a full execution here: this test is
        # itself part of tests/unit, so spawning a full, non-collect-
        # only run of the whole directory from inside it would
        # recursively re-run the entire suite (including this test
        # again) in a nested subprocess -- needlessly slow, and prone
        # to timing out under CPU contention with its own parent run.
        # Full-suite execution (not just collection) without DISPLAY
        # is covered directly, not recursively, by running
        # `pytest tests/unit -k "not network"` from the command line.
        result = self._run(
            ['-m', 'pytest', '--collect-only', '-q', 'tests/unit',
             '-k', 'not network'],
            self._env_without_display(), timeout=60)
        self.assertEqual(0, result.returncode, result.stdout)
        self.assertNotIn('ERROR collecting', result.stdout)
        self.assertNotIn('INTERNALERROR', result.stdout)

    def test_not_a_blanket_module_skip(self):
        # Confirm tests that never touch a real wx.Frame -- pure
        # logic (HelperFunctionTest's _parse_ranges/_freq_str
        # coverage) and config-only (MenuIntegrationTest) -- actually
        # RUN (not skip) headlessly, proving this isn't a whole-module
        # skip in disguise. Tests that construct a real wx.Frame are
        # expected to skip; these specific ones must not.
        result = self._run(
            ['-m', 'pytest', '-v',
             'tests/unit/test_wxui_programming_assistant.py'],
            self._env_without_display())
        self.assertEqual(0, result.returncode, result.stdout)
        for nodeid in (
                'HelperFunctionTest::test_parse_ranges_basic',
                'HelperFunctionTest::test_freq_str_formats_mhz',
                'MenuIntegrationTest::test_assistant_disabled_by_default',
                'MenuIntegrationTest::test_set_assistant_enabled_persists'):
            self.assertIn('%s PASSED' % nodeid, result.stdout,
                          '%s did not run headlessly' % nodeid)

    def test_gui_tests_skip_with_clear_reason_not_error(self):
        result = self._run(
            ['-m', 'pytest', '-ra',
             'tests/unit/test_wxui_programming_assistant.py'
             '::RealWizardEventFlowTest'
             '::test_full_wizard_flow_populates_review_and_applies_result'],
            self._env_without_display())
        self.assertEqual(0, result.returncode, result.stdout)
        self.assertIn('skipped', result.stdout)
        self.assertIn('no display available for wx GUI tests', result.stdout)

    def test_mixed_collection_order_with_linux_launcher_both_ways(self):
        # Confirms this fix doesn't reintroduce or interact badly with
        # the previously-repaired wx sys.modules isolation defect
        # (test_wxui_linux_launcher.py / test_wxui_radiothread.py),
        # and that collection order doesn't change the outcome.
        env = self._env_without_display()
        forward = self._run(
            ['-m', 'pytest', '-q',
             'tests/unit/test_wxui_linux_launcher.py',
             'tests/unit/test_wxui_programming_assistant.py'], env)
        reverse = self._run(
            ['-m', 'pytest', '-q',
             'tests/unit/test_wxui_programming_assistant.py',
             'tests/unit/test_wxui_linux_launcher.py'], env)
        for result, label in ((forward, 'linux_launcher-first'),
                              (reverse, 'programming_assistant-first')):
            self.assertEqual(0, result.returncode,
                             '%s: %s' % (label, result.stdout))
            self.assertNotIn('ERROR collecting', result.stdout, label)
        # Compare pass/skip counts specifically, not the full summary
        # line -- a DeprecationWarning's count can legitimately differ
        # by collection order (it's only emitted the first time
        # chirp.wxui.memedit is imported in each subprocess, and which
        # file triggers that import first depends on the order), which
        # is unrelated to whether this fix's own outcome is order
        # -independent.
        counts_re = r'(\d+) passed, (\d+) skipped'
        self.assertEqual(
            re.search(counts_re, forward.stdout).groups(),
            re.search(counts_re, reverse.stdout).groups(),
            'collection order changed the pass/skip counts:\n%s\n---\n%s'
            % (forward.stdout, reverse.stdout))

    def test_three_file_combination_from_original_report(self):
        result = self._run(
            ['-m', 'pytest', '-q',
             'tests/unit/test_wxui_radiothread.py',
             'tests/unit/test_wxui_linux_launcher.py',
             'tests/unit/test_wxui_programming_assistant.py'],
            self._env_without_display())
        self.assertEqual(0, result.returncode, result.stdout)
        self.assertNotIn('ERROR collecting', result.stdout)

    def test_display_present_runs_gui_tests_fully(self):
        # The fix must not accidentally skip GUI tests when a real
        # display genuinely is available. Only meaningful (and only
        # run) in an environment that actually has one.
        if not os.environ.get('DISPLAY'):
            self.skipTest('no DISPLAY in this process to verify against')
        env = dict(os.environ, CHIRP_TESTENV='1', PYTHONPATH=_REPO_ROOT)
        result = self._run(
            ['-m', 'pytest', '-q',
             'tests/unit/test_wxui_programming_assistant.py'], env)
        self.assertEqual(0, result.returncode, result.stdout)
        self.assertNotIn('skipped', result.stdout)
        self.assertRegex(result.stdout, r'136 passed')
