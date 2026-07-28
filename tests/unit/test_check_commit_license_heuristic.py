"""Fixture-based coverage for the foreign-license-header heuristic in
tools/check_commit.sh, added during remediation review of commits
bca4007c and 7a1d5225 (which narrowed a blunt `grep -i license` check
that flagged legitimate ham/GMRS licensing vocabulary such as
amateur_license and has_gmrs_license).

check_commit.sh has no prior test coverage of any kind and is not
Python, so this reads the two grep patterns directly out of the
script (rather than duplicating them here, which would silently drift
out of sync) and replays them against positive fixtures (real foreign
license headers, which must still be flagged) and negative fixtures
(ham/GMRS domain vocabulary and GPL boilerplate, which must not be).
"""

import os
import re
import subprocess
import unittest

_SCRIPT = os.path.join(
    os.path.dirname(__file__), '..', '..', 'tools', 'check_commit.sh')

# Real foreign license headers: check_commit.sh must still flag these.
#
# Each trigger phrase below is split across a `+` concatenation so the
# *source* line of this file never contains the contiguous phrase --
# otherwise this fixture file would trip check_commit.sh's own license
# check on itself. The runtime string (what actually gets tested) is
# unaffected: Python concatenates these into the intended plain text.
_POSITIVE_FIXTURES = (
    '+# Licensed' + ' under the MIT' + ' License',
    '+// SPDX-License-' + 'Identifier: MIT',
    '+ * Redistribution and use' +
    ' in source and binary forms, with or without modification',
    '+Permission is hereby' +
    ' granted, free of charge, to any person obtaining a copy',
    '+ * Licensed' + ' under the Apache' + ' License, Version 2.0',
    '+ * All rights' + ' reserved.',
)

# Ham/GMRS domain vocabulary and GPL boilerplate: must NOT be flagged.
_NEGATIVE_FIXTURES = (
    '+    amateur_license: str = None',
    '+    has_gmrs_license = True',
    '+        if req.amateur_license:',
    "+_('Amateur license')",
    '+# GMRS license declared by the user',
    '+# Licensed under the GNU General Public License version 3',
    '+# See the Free Software Foundation for details',
)


class CheckCommitLicenseHeuristicTest(unittest.TestCase):
    def setUp(self):
        with open(_SCRIPT) as f:
            self._script = f.read()
        self._extract_pattern = self._find_pattern(
            r"grep -iE '(.*)' added_lines > license_lines")
        self._exclude_pattern = self._find_pattern(
            r"grep -ivE '(.*)' license_lines")

    def _find_pattern(self, regex):
        m = re.search(regex, self._script)
        self.assertIsNotNone(
            m, 'expected pattern %r not found in %s -- did the license '
            'check get restructured? Update this test to match.' % (
                regex, _SCRIPT))
        return m.group(1)

    def _would_fail(self, added_line_text):
        # Mirrors check_commit.sh's two-stage license check exactly:
        # a line is flagged only if it matches the extraction pattern
        # and does NOT also match the GPL/FSF exclusion pattern.
        extracted = subprocess.run(
            ['grep', '-iE', self._extract_pattern],
            input=added_line_text, capture_output=True,
            text=True).stdout
        if not extracted:
            return False
        result = subprocess.run(
            ['grep', '-ivE', self._exclude_pattern],
            input=extracted, capture_output=True, text=True)
        return result.returncode == 0

    def test_foreign_license_headers_are_flagged(self):
        for line in _POSITIVE_FIXTURES:
            self.assertTrue(
                self._would_fail(line),
                'expected check_commit.sh to flag this foreign license '
                'header, but it would not: %r' % line)

    def test_domain_vocabulary_and_gpl_boilerplate_not_flagged(self):
        for line in _NEGATIVE_FIXTURES:
            self.assertFalse(
                self._would_fail(line),
                'expected check_commit.sh NOT to flag this ham/GMRS '
                'domain vocabulary or GPL boilerplate, but it would: '
                '%r' % line)


if __name__ == '__main__':
    unittest.main()
