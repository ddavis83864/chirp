import unittest

from chirp import chirp_common
from chirp.profiles import matching
from chirp.profiles import schema


def _mem(number, freq, name='', duplex='', offset=0, tmode=''):
    m = chirp_common.Memory()
    m.number = number
    m.freq = freq
    m.name = name
    m.duplex = duplex
    m.offset = offset
    m.tmode = tmode
    return m


class ExactMatchTest(unittest.TestCase):
    def test_identical_memory_is_exact_match(self):
        existing = [_mem(
            0, 146520000, name='CDA', duplex='+', offset=600000)]
        proposed = _mem(
            -1, 146520000, name='CDA', duplex='+', offset=600000)
        result = matching.match_channel(proposed, existing)
        self.assertEqual(schema.MATCH_EXACT, result.match_type)
        self.assertEqual(0, result.existing_memory.number)

    def test_name_only_difference_is_update_candidate_not_exact(self):
        # Operationally identical (same freq/duplex/offset/tone/etc --
        # chirp_common's own DUPE_SIGNATURE_FIELDS excludes name) but a
        # different display name still means something should change.
        existing = [_mem(
            0, 146520000, name='OLD NAME', duplex='+', offset=600000)]
        proposed = _mem(
            -1, 146520000, name='NEW NAME', duplex='+', offset=600000)
        result = matching.match_channel(proposed, existing)
        self.assertEqual(schema.MATCH_UPDATE_CANDIDATE, result.match_type)
        self.assertEqual(0, result.existing_memory.number)

    def test_name_alone_never_causes_exact_match(self):
        existing = [_mem(0, 146520000, name='SAME NAME', duplex='')]
        proposed = _mem(-1, 999000000, name='SAME NAME', duplex='')
        result = matching.match_channel(proposed, existing)
        self.assertNotEqual(schema.MATCH_EXACT, result.match_type)


class UpdateCandidateTest(unittest.TestCase):
    def test_same_freq_duplex_offset_different_tone_is_update_candidate(self):
        existing = [_mem(
            0, 146520000, name='CDA', duplex='+', offset=600000,
            tmode='')]
        proposed = _mem(
            -1, 146520000, name='CDA', duplex='+', offset=600000,
            tmode='Tone')
        result = matching.match_channel(proposed, existing)
        self.assertEqual(schema.MATCH_UPDATE_CANDIDATE, result.match_type)
        self.assertEqual(0, result.existing_memory.number)


class AmbiguousMatchTest(unittest.TestCase):
    def test_two_existing_memories_same_core_signature_is_ambiguous(self):
        existing = [
            _mem(0, 146520000, name='A', duplex='+', offset=600000),
            _mem(1, 146520000, name='B', duplex='+', offset=600000,
                 tmode='Tone'),
        ]
        proposed = _mem(
            -1, 146520000, name='C', duplex='+', offset=600000,
            tmode='TSQL')
        result = matching.match_channel(proposed, existing)
        self.assertEqual(schema.MATCH_AMBIGUOUS, result.match_type)
        self.assertEqual(2, len(result.candidates))


class NoMatchTest(unittest.TestCase):
    def test_unrelated_frequency_is_no_match(self):
        existing = [_mem(0, 146520000, duplex='+', offset=600000)]
        proposed = _mem(-1, 445000000, duplex='')
        result = matching.match_channel(proposed, existing)
        self.assertEqual(schema.MATCH_NONE, result.match_type)

    def test_empty_target_image_is_no_match(self):
        empty = chirp_common.Memory()
        empty.number = 0
        empty.empty = True
        proposed = _mem(-1, 146520000)
        result = matching.match_channel(proposed, [empty])
        self.assertEqual(schema.MATCH_NONE, result.match_type)

    def test_special_channels_are_ignored(self):
        special = _mem(0, 146520000, duplex='')
        special.extd_number = 'WX1'
        proposed = _mem(-1, 146520000, duplex='')
        result = matching.match_channel(proposed, [special])
        self.assertEqual(schema.MATCH_NONE, result.match_type)


class DeterminismTest(unittest.TestCase):
    def test_repeated_matching_is_stable(self):
        existing = [_mem(0, 146520000, duplex='+', offset=600000)]
        proposed = _mem(-1, 146520000, duplex='+', offset=600000)
        r1 = matching.match_channel(proposed, existing)
        r2 = matching.match_channel(proposed, existing)
        self.assertEqual(r1.match_type, r2.match_type)

    def test_probe_memory_is_not_mutated(self):
        existing = [_mem(0, 146520000, duplex='+', offset=600000)]
        proposed = _mem(7, 146520000, duplex='+', offset=600000)
        matching.match_channel(proposed, existing)
        self.assertEqual(7, proposed.number)
