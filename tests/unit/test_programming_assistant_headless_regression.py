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
        # _env_without_display() simulates "no display" the way real
        # headless Linux CI actually lacks one: by removing the X11/
        # Wayland environment variables wx.App() consults on that
        # platform. Windows has no equivalent env-var-gated display
        # check -- wx.App() succeeds there regardless, using whatever
        # desktop session the runner already has -- so this specific
        # technique for reaching _ensure_wx_app()'s SystemExit-to-skip
        # path only exercises anything on Linux. The underlying skip
        # behavior itself is still covered there; this is a test-
        # methodology limitation, not an untested code path.
        if sys.platform != 'linux':
            self.skipTest(
                'this test simulates "no display" via X11-specific '
                'environment variables, which only affects wx.App() '
                'on Linux')
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
        # pytest omits ", N skipped" entirely when the skip count is
        # zero (e.g. on Windows, where test_wxui_linux_launcher.py's
        # own sys.modules['wx'] isolation doesn't produce any skips the
        # way Linux's headless-CI display detection does) -- the
        # skipped group is optional, and treated as 0 when absent,
        # rather than requiring the literal ", N skipped" text.
        counts_re = r'(\d+) passed(?:, (\d+) skipped)?'

        def _counts(result):
            match = re.search(counts_re, result.stdout)
            self.assertIsNotNone(
                match, 'no pass/skip summary found in:\n%s' % result.stdout)
            passed, skipped = match.groups()
            return passed, skipped or '0'

        self.assertEqual(
            _counts(forward), _counts(reverse),
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

    def test_memquery_collection_order_survives_non_linux_platform(self):
        # Confirms test_wxui_memquery.py's own wx sys.modules isolation
        # (mirroring test_wxui_linux_launcher.py / test_wxui_
        # radiothread.py) holds even on the code path that only runs
        # when sys.platform != 'linux' (chirp/wxui/memedit.py's
        # SearchBox filter box, never constructed on Linux). Without
        # that isolation, chirp.wxui.memquery.SearchBox -- a real class
        # that subclasses wx.TextCtrl -- gets built against
        # test_wxui_memquery.py's fake wx if that file is collected
        # first: subclassing a MagicMock attribute doesn't raise, it
        # silently produces a MagicMock standing in for the class, whose
        # first call succeeds and every subsequent call raises
        # StopIteration. This only ever showed up on Windows CI, which
        # is the only environment where that branch runs -- so this
        # test forces the same runtime condition (sys.platform != linux)
        # here, via a plugin loaded through PYTEST_PLUGINS, so a
        # regression is caught on any platform's ordinary test run, not
        # only on a real Windows machine. Confirmed by direct
        # reproduction that this fails (StopIteration in
        # memquery.SearchBox) without test_wxui_memquery.py's isolation
        # fix, and passes with it, in both collection orders.
        #
        # Requires a real display, like test_display_present_runs_gui_
        # fully below: the code path under test only executes inside
        # ChirpMemEdit's real wx.Frame construction, which needs one.
        # This repository's own headless CI sets up no Xvfb anywhere
        # (see this file's module docstring), so this test is skipped
        # there -- it is a real-display development/CI-with-a-display
        # regression check, not a substitute for exercising the actual
        # Windows runner (which does have a usable desktop), and does
        # not by itself prove Windows CI is green.
        if not os.environ.get('DISPLAY'):
            self.skipTest('no DISPLAY in this process to verify against')
        env = dict(os.environ, CHIRP_TESTENV='1', PYTHONPATH=_REPO_ROOT)
        env['PYTEST_PLUGINS'] = 'tests.unit._force_non_linux_platform_plugin'
        forward = self._run(
            ['-m', 'pytest', '-q',
             'tests/unit/test_wxui_memquery.py',
             'tests/unit/test_wxui_programming_assistant.py'], env)
        reverse = self._run(
            ['-m', 'pytest', '-q',
             'tests/unit/test_wxui_programming_assistant.py',
             'tests/unit/test_wxui_memquery.py'], env)
        for result, label in ((forward, 'memquery-first'),
                              (reverse, 'programming_assistant-first')):
            self.assertEqual(0, result.returncode,
                             '%s: %s' % (label, result.stdout))
            self.assertNotIn('StopIteration', result.stdout, label)
            self.assertNotIn('FAILED', result.stdout, label)
            self.assertNotIn('ERROR collecting', result.stdout, label)

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
        self.assertRegex(result.stdout, r'56 passed')

    def test_wx_app_singleton_destroyed_before_process_exit(self):
        # Regression for a second, independent defect from the same
        # Windows CI run this file's other tests were added for:
        # test_wxui_programming_assistant.py's module-level wx.App
        # singleton (_APP) used to be left alive, referenced only by
        # that module global, until the *process* itself exited and
        # CPython's own interpreter-finalization GC pass collected it
        # instead of ordinary refcounting. By then the GIL had already
        # been released for shutdown, and wx's native App/window
        # teardown could still try to call back into Python (e.g. a
        # queued wx.CallLater callback), crashing with "Fatal Python
        # error: PyThreadState_Get: ... the GIL is released" --
        # confirmed on real Windows CI, never reproducible on Linux.
        #
        # This validates the actual lifecycle contract -- the App is
        # explicitly torn down by tearDownModule(), not merely that no
        # crash message appears -- by checking _APP's value directly
        # in the same subprocess right after its own test run
        # completes, in-process, before that process exits and any
        # interpreter-shutdown-timing difference between platforms
        # could matter.
        if not os.environ.get('DISPLAY'):
            self.skipTest('no DISPLAY in this process to verify against')
        env = dict(os.environ, CHIRP_TESTENV='1', PYTHONPATH=_REPO_ROOT)
        result = self._run(
            ['-c',
             'import sys\n'
             'import pytest\n'
             'rc = pytest.main(["-q",'
             ' "tests/unit/test_wxui_programming_assistant.py"])\n'
             'import tests.unit.test_wxui_programming_assistant as m\n'
             'sys.stdout.write("MODULE_APP_AFTER_RUN=%r\\n" % (m._APP,))\n'
             'sys.exit(rc)'],
            env)
        self.assertEqual(0, result.returncode, result.stdout)
        self.assertIn(
            'MODULE_APP_AFTER_RUN=None', result.stdout,
            'wx.App singleton was not torn down by tearDownModule() -- '
            'still referenced after the test run completed:\n%s'
            % result.stdout)
