import unittest

from chirp import chirp_common
from chirp.profiles import conflicts
from chirp.profiles import matching
from chirp.profiles import placement
from chirp.profiles import schema


def _mem(number, name='', freq=146520000):
    m = chirp_common.Memory()
    m.number = number
    m.name = name
    m.freq = freq
    return m


class DuplicateTargetTest(unittest.TestCase):
    def test_two_channels_placed_at_same_number_conflict(self):
        placements = {
            'a': placement.PlacementDecision('a', 5),
            'b': placement.PlacementDecision('b', 5),
        }
        matches = {
            'a': matching.MatchResult(schema.MATCH_NONE),
            'b': matching.MatchResult(schema.MATCH_NONE),
        }
        found = conflicts.detect_conflicts(placements, matches, {})
        types = [c.conflict_type for c in found]
        self.assertIn(schema.CONFLICT_DUPLICATE_TARGET, types)

    def test_distinct_numbers_no_conflict(self):
        placements = {
            'a': placement.PlacementDecision('a', 5),
            'b': placement.PlacementDecision('b', 6),
        }
        matches = {
            'a': matching.MatchResult(schema.MATCH_NONE),
            'b': matching.MatchResult(schema.MATCH_NONE),
        }
        found = conflicts.detect_conflicts(placements, matches, {})
        self.assertEqual([], found)


class CapacityExceededTest(unittest.TestCase):
    def test_capacity_exceeded_reported(self):
        placements = {
            'a': placement.PlacementDecision(
                'a', None, conflict_reason=schema.CONFLICT_CAPACITY_EXCEEDED),
        }
        found = conflicts.detect_conflicts(placements, {}, {})
        self.assertEqual(1, len(found))
        self.assertEqual(schema.CONFLICT_CAPACITY_EXCEEDED,
                         found[0].conflict_type)
        self.assertEqual(('a',), found[0].logical_ids)


class ImmutableMemoryTest(unittest.TestCase):
    def test_immutable_conflict_reported(self):
        placements = {
            'a': placement.PlacementDecision(
                'a', None, conflict_reason=schema.CONFLICT_IMMUTABLE_MEMORY),
        }
        found = conflicts.detect_conflicts(placements, {}, {})
        self.assertEqual(schema.CONFLICT_IMMUTABLE_MEMORY,
                         found[0].conflict_type)


class LocationOccupiedTest(unittest.TestCase):
    def test_replace_range_overwrite_reported(self):
        placements = {
            'a': placement.PlacementDecision(
                'a', 5, replaces_existing=True),
        }
        found = conflicts.detect_conflicts(placements, {}, {})
        self.assertEqual(schema.CONFLICT_LOCATION_OCCUPIED,
                         found[0].conflict_type)
        self.assertEqual(5, found[0].memory_number)


class AmbiguousMatchConflictTest(unittest.TestCase):
    def test_ambiguous_match_reported(self):
        candidates = (_mem(1), _mem(2))
        matches = {
            'a': matching.MatchResult(
                schema.MATCH_AMBIGUOUS, candidates=candidates),
        }
        found = conflicts.detect_conflicts({}, matches, {})
        self.assertEqual(1, len(found))
        self.assertEqual(schema.CONFLICT_AMBIGUOUS_MATCH,
                         found[0].conflict_type)
        self.assertEqual(('a',), found[0].logical_ids)


class NameCollisionTest(unittest.TestCase):
    def test_two_proposed_memories_same_name_conflict(self):
        proposed = {
            'a': _mem(1, name='SAME'),
            'b': _mem(2, name='SAME'),
        }
        found = conflicts.detect_conflicts({}, {}, proposed)
        self.assertEqual(1, len(found))
        self.assertEqual(schema.CONFLICT_NAME_COLLISION,
                         found[0].conflict_type)
        self.assertEqual(('a', 'b'), found[0].logical_ids)

    def test_distinct_names_no_conflict(self):
        proposed = {
            'a': _mem(1, name='ONE'),
            'b': _mem(2, name='TWO'),
        }
        found = conflicts.detect_conflicts({}, {}, proposed)
        self.assertEqual([], found)

    def test_empty_names_never_collide(self):
        proposed = {
            'a': _mem(1, name=''),
            'b': _mem(2, name=''),
        }
        found = conflicts.detect_conflicts({}, {}, proposed)
        self.assertEqual([], found)


class DeterminismTest(unittest.TestCase):
    def test_same_inputs_produce_same_conflicts(self):
        placements = {
            'a': placement.PlacementDecision('a', 5),
            'b': placement.PlacementDecision('b', 5),
        }
        matches = {
            'a': matching.MatchResult(schema.MATCH_NONE),
            'b': matching.MatchResult(schema.MATCH_NONE),
        }
        f1 = conflicts.detect_conflicts(placements, matches, {})
        f2 = conflicts.detect_conflicts(placements, matches, {})
        self.assertEqual([(c.conflict_type, c.logical_ids) for c in f1],
                         [(c.conflict_type, c.logical_ids) for c in f2])
