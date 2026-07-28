"""Regression coverage proving Programming Assistant tests never
depend on a repository-root test.csv file.

tests/unit/test_assistant_service.py and tests/unit/test_wxui_
programming_assistant.py used to construct their test radio via
generic_csv.CSVRadio(_TEST_CSV), where _TEST_CSV was a hardcoded path
to <repo-root>/test.csv. generic_csv.CSVRadio.__init__ falls back to
a blank, in-memory-only radio when that path doesn't exist (which is
every normal checkout, since 'test.csv' is gitignored) -- but loads
real content, with real (and file-content-dependent) pre-occupied
memory numbers, whenever a file happens to exist there. An unrelated
personal file -- e.g. a developer's own real-world repeater CSV
sitting at the repo root for unrelated reasons, coincidentally named
test.csv -- silently changed test.csv:AssistantServiceTest::test_
approved_existing_conflict_replacement_still_allowed's outcome
without changing any code, confirmed by direct reproduction (clean
worktree: pass; same commit with a stray repo-root test.csv: fail).

Fixed by switching both files to generic_csv.CSVRadio(None), which is
the already-established pattern this repository uses elsewhere
(tests/unit/test_assistant_planning_scenarios.py) for exactly this
situation -- an in-memory-only radio that touches no file at all, so
there is nothing for an unrelated file to collide with, regardless of
its name, content, permissions, or presence.

This can only be verified by actually creating a stray repo-root
test.csv and observing that the affected tests are unaffected -- not
from calls made within an already-running test process, since the
whole point is proving behavior *as seen by a fresh process* that
would encounter the file the same way a real one would. Each test
here manages that file directly, refusing to run at all if one already
exists (never touching what might be real developer data), and always
cleaning up whatever it created itself.
"""

import os
import re
import shutil
import stat
import subprocess
import sys
import unittest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
_STRAY_CSV_PATH = os.path.join(_REPO_ROOT, 'test.csv')

_AFFECTED_TEST_FILES = (
    'tests/unit/test_assistant_service.py',
    'tests/unit/test_wxui_programming_assistant.py',
)

# A real-world-shaped repeater CSV, structurally identical to the kind
# of file that actually caused the original failure (a developer's own
# amateur-radio repeater list, not a purpose-built test fixture) --
# including a row at memory 5, the exact slot the regression involved.
_REAL_REPEATER_CSV = """\
Location,Name,Frequency,Duplex,Offset,Tone,rToneFreq,cToneFreq,Mode
0,Shafer Butte,145.130000,-,0.600000,Tone,100.0,88.5,FM
1,WA7FDR,145.150000,-,0.600000,Tone,100.0,88.5,FM
5,Teakean Butte,145.210000,-,0.600000,Tone,206.5,88.5,FM
"""


class ProgrammingAssistantCsvIsolationRegressionTest(unittest.TestCase):
    def setUp(self):
        # Refuse to run at all -- rather than risk touching -- a
        # genuinely pre-existing file. This suite creates and removes
        # only files it created itself, in this run.
        if os.path.exists(_STRAY_CSV_PATH):
            self.skipTest(
                '%s already exists -- refusing to run this suite '
                'against a file that might be real developer data. '
                'Move it aside yourself, outside of this test run, if '
                'you want to exercise this coverage.' % _STRAY_CSV_PATH)
        self.addCleanup(self._remove_stray_csv_if_present)

    def _remove_stray_csv_if_present(self):
        if os.path.exists(_STRAY_CSV_PATH):
            os.chmod(_STRAY_CSV_PATH, stat.S_IWRITE | stat.S_IREAD)
            os.remove(_STRAY_CSV_PATH)

    def _write_stray_csv(self, content):
        with open(_STRAY_CSV_PATH, 'w') as f:
            f.write(content)

    def _run(self, *args, timeout=120):
        env = dict(os.environ, CHIRP_TESTENV='1', PYTHONPATH=_REPO_ROOT)
        return subprocess.run(
            [sys.executable, '-m', 'pytest', '-q', *args],
            cwd=_REPO_ROOT, env=env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            timeout=timeout)

    def test_passes_with_stray_csv_absent(self):
        self.assertFalse(os.path.exists(_STRAY_CSV_PATH))
        result = self._run(*_AFFECTED_TEST_FILES)
        self.assertEqual(0, result.returncode, result.stdout)
        self.assertNotIn('FAILED', result.stdout)

    def test_passes_with_real_repeater_data_present(self):
        # The exact class of file that caused the original failure.
        self._write_stray_csv(_REAL_REPEATER_CSV)
        result = self._run(*_AFFECTED_TEST_FILES)
        self.assertEqual(0, result.returncode, result.stdout)
        self.assertNotIn('FAILED', result.stdout)

    def test_passes_with_invalid_csv_content(self):
        self._write_stray_csv(
            'this is not a valid CSV file at all\n\x00garbage\xff\n')
        result = self._run(*_AFFECTED_TEST_FILES)
        self.assertEqual(0, result.returncode, result.stdout)
        self.assertNotIn('FAILED', result.stdout)

    def test_passes_with_readonly_stray_csv(self):
        self._write_stray_csv(_REAL_REPEATER_CSV)
        os.chmod(_STRAY_CSV_PATH, stat.S_IREAD)
        result = self._run(*_AFFECTED_TEST_FILES)
        self.assertEqual(0, result.returncode, result.stdout)
        self.assertNotIn('FAILED', result.stdout)

    def test_stray_csv_is_never_opened_or_modified(self):
        self._write_stray_csv(_REAL_REPEATER_CSV)
        before_mtime = os.path.getmtime(_STRAY_CSV_PATH)
        with open(_STRAY_CSV_PATH) as f:
            before_content = f.read()

        result = self._run(*_AFFECTED_TEST_FILES)
        self.assertEqual(0, result.returncode, result.stdout)

        after_mtime = os.path.getmtime(_STRAY_CSV_PATH)
        with open(_STRAY_CSV_PATH) as f:
            after_content = f.read()
        self.assertEqual(
            before_mtime, after_mtime,
            'stray test.csv mtime changed -- something wrote to it')
        self.assertEqual(before_content, after_content)

    @staticmethod
    def _pass_fail_counts(stdout):
        # Compare only the pass/fail/skip counts, not the full final
        # summary line -- pytest's own reported wall-clock time
        # (e.g. "in 32.30s") varies run to run and is not part of the
        # outcome being compared here.
        counts = re.findall(r'(\d+) (passed|failed|skipped)', stdout)
        return sorted(counts)

    def test_results_identical_with_and_without_stray_csv(self):
        without = self._run(*_AFFECTED_TEST_FILES)
        self.assertEqual(0, without.returncode, without.stdout)

        self._write_stray_csv(_REAL_REPEATER_CSV)
        withit = self._run(*_AFFECTED_TEST_FILES)
        self.assertEqual(0, withit.returncode, withit.stdout)

        self.assertEqual(
            self._pass_fail_counts(without.stdout),
            self._pass_fail_counts(withit.stdout),
            'a stray repo-root test.csv changed the pass/fail outcome:\n%s'
            '\n---\n%s' % (without.stdout, withit.stdout))

    def test_repeated_runs_are_deterministic(self):
        first = self._run(*_AFFECTED_TEST_FILES)
        second = self._run(*_AFFECTED_TEST_FILES)
        self.assertEqual(0, first.returncode, first.stdout)
        self.assertEqual(0, second.returncode, second.stdout)
        self.assertEqual(self._pass_fail_counts(first.stdout),
                         self._pass_fail_counts(second.stdout))

    def test_parallel_execution_has_no_filename_collision(self):
        if shutil.which('true') is None:
            self.skipTest('no shell available to verify with')
        try:
            import xdist  # noqa: F401
        except ImportError:
            self.skipTest('pytest-xdist not installed')
        # CSVRadio(None) touches no file at all, so there is no
        # filename for concurrent workers to collide on -- run the
        # affected files under two parallel workers as direct proof,
        # rather than just asserting it by inspection.
        result = self._run(*_AFFECTED_TEST_FILES, '-n', '2')
        self.assertEqual(0, result.returncode, result.stdout)
        self.assertNotIn('FAILED', result.stdout)

    def test_no_file_created_in_repo_root_by_affected_tests(self):
        # Confirms CSVRadio(None) truly touches no filesystem state:
        # running the affected tests must not create any new file at
        # the repo root (not test.csv, not anything else).
        before = set(os.listdir(_REPO_ROOT))
        result = self._run(*_AFFECTED_TEST_FILES)
        after = set(os.listdir(_REPO_ROOT))
        self.assertEqual(0, result.returncode, result.stdout)
        self.assertEqual(
            before, after,
            'files appeared in the repo root during the run: %s' %
            (after - before))

    def test_no_test_csv_reference_remains_in_affected_files(self):
        # Static confirmation alongside the behavioral proof above:
        # neither file constructs a repo-root test.csv path anymore.
        # Checking for the removed _TEST_CSV symbol itself, rather
        # than the substring "test.csv" (which legitimately still
        # appears in this file's own explanatory prose, and in these
        # two files' comments about what used to happen).
        for relpath in _AFFECTED_TEST_FILES:
            with open(os.path.join(_REPO_ROOT, relpath)) as f:
                tree_source = f.read()
            self.assertNotIn(
                '_TEST_CSV =', tree_source,
                '%s still defines a repo-root test.csv path' % relpath)
            self.assertNotIn(
                'CSVRadio(_TEST_CSV)', tree_source,
                '%s still constructs a radio from a repo-root test.csv '
                'path' % relpath)
