import unittest

from chirp import chirp_common
from chirp.assistant import capability
from chirp.assistant import models
from chirp.assistant import planner


def _cap(bounds=(0, 99), name_length=6,
         chars=chirp_common.CHARSET_UPPER_NUMERIC):
    class FakeRadio:
        def get_features(self):
            rf = chirp_common.RadioFeatures()
            rf.memory_bounds = bounds
            rf.valid_name_length = name_length
            rf.valid_characters = chars
            return rf
    return capability.snapshot(FakeRadio())


def _cand(label, freq, tx_freq=None, service=models.SERVICE_HAM,
          distance=None, confidence=models.CONFIDENCE_HIGH,
          source_id=''):
    return models.ChannelCandidate(
        source='test', source_record_id=source_id, service=service,
        group='g', label=label, freq=freq, tx_freq=tx_freq,
        distance_miles=distance, confidence=confidence)


def _existing_memory(number, freq, duplex='', offset=0, name='', empty=False):
    mem = chirp_common.Memory(number=number, empty=empty, name=name)
    mem.freq = freq
    mem.duplex = duplex
    mem.offset = offset
    return mem


class DedupTest(unittest.TestCase):
    def test_exact_duplicate_dropped(self):
        a = _cand('Repeater A', 146850000, 146250000, distance=1.0)
        b = _cand('Repeater A dup', 146850000, 146250000, distance=5.0)
        kept, dropped = planner.deduplicate([a, b])
        self.assertEqual(1, len(kept))
        self.assertEqual('Repeater A', kept[0].label)
        self.assertEqual(1, len(dropped))
        self.assertEqual(models.STATUS_DUPLICATE, dropped[0].status)
        self.assertFalse(dropped[0].include)

    def test_closer_candidate_kept_on_duplicate(self):
        far = _cand('Far', 146850000, 146250000, distance=10.0)
        near = _cand('Near', 146850000, 146250000, distance=1.0)
        kept, dropped = planner.deduplicate([far, near])
        self.assertEqual('Near', kept[0].label)

    def test_same_output_freq_different_tone_not_deduplicated(self):
        # Two repeaters sharing an output frequency are not necessarily
        # the same repeater.
        a = _cand('A', 146850000, 146250000)
        a.tmode = 'Tone'
        a.rtone = 100.0
        b = _cand('B', 146850000, 146250000)
        b.tmode = 'Tone'
        b.rtone = 88.5
        kept, dropped = planner.deduplicate([a, b])
        self.assertEqual(2, len(kept))
        self.assertEqual(0, len(dropped))

    def test_deterministic_ordering(self):
        # Same inputs (even out of order) always dedup/order the same way.
        a = _cand('A', 146850000, distance=2.0)
        b = _cand('B', 146900000, distance=1.0)
        c = _cand('C', 146950000, distance=3.0)
        kept1, _d1 = planner.deduplicate([a, b, c])
        kept2, _d2 = planner.deduplicate([c, a, b])
        self.assertEqual([x.label for x in kept1], [x.label for x in kept2])
        self.assertEqual(['B', 'A', 'C'], [x.label for x in kept1])


class ExistingConflictTest(unittest.TestCase):
    def test_conflict_excluded_by_default(self):
        existing = [(5, _existing_memory(5, 146850000, '-', 600000,
                                         name='OLDNAME'))]
        c = _cand('New', 146850000, 146250000)
        req = models.ProgrammingRequest()
        survivors = planner.flag_existing_conflicts([c], existing, req)
        self.assertEqual(0, len(survivors))
        self.assertEqual(models.STATUS_EXISTING_CONFLICT, c.status)
        self.assertFalse(c.include)

    def test_conflict_replaceable_when_allowed(self):
        existing = [(5, _existing_memory(5, 146850000, '-', 600000))]
        c = _cand('New', 146850000, 146250000)
        req = models.ProgrammingRequest(allow_duplicate_replacement=True)
        survivors = planner.flag_existing_conflicts([c], existing, req)
        self.assertEqual(1, len(survivors))
        self.assertEqual(5, c.memory_number)
        self.assertTrue(c.include)

    def test_empty_existing_memory_is_not_a_conflict(self):
        existing = [(5, _existing_memory(5, 0, empty=True))]
        c = _cand('New', 146850000, 146250000)
        req = models.ProgrammingRequest()
        survivors = planner.flag_existing_conflicts([c], existing, req)
        self.assertEqual(1, len(survivors))

    def test_different_frequency_is_not_a_conflict(self):
        existing = [(5, _existing_memory(5, 146900000))]
        c = _cand('New', 146850000)
        req = models.ProgrammingRequest()
        survivors = planner.flag_existing_conflicts([c], existing, req)
        self.assertEqual(1, len(survivors))


class AllocationTest(unittest.TestCase):
    def test_allocates_empty_slots_in_order(self):
        cands = [_cand('A', 1), _cand('B', 2), _cand('C', 3)]
        cap = _cap(bounds=(0, 9))
        capacity_limited = planner.allocate_memory_numbers(
            cands, cap, [], models.ProgrammingRequest())
        self.assertFalse(capacity_limited)
        self.assertEqual([0, 1, 2], [c.memory_number for c in cands])

    def test_skips_occupied_slots(self):
        cands = [_cand('A', 1), _cand('B', 2)]
        existing = [(0, _existing_memory(0, 999, name='X')),
                    (1, _existing_memory(1, 0, empty=True))]
        cap = _cap(bounds=(0, 9))
        planner.allocate_memory_numbers(
            cands, cap, existing, models.ProgrammingRequest())
        self.assertEqual([1, 2], [c.memory_number for c in cands])

    def test_respects_protected_ranges(self):
        cands = [_cand('A', 1)]
        req = models.ProgrammingRequest(protected_memory_ranges=((0, 4),))
        cap = _cap(bounds=(0, 9))
        planner.allocate_memory_numbers(cands, cap, [], req)
        self.assertEqual(5, cands[0].memory_number)

    def test_respects_requested_range(self):
        cands = [_cand('A', 1)]
        req = models.ProgrammingRequest(
            requested_start_memory=50, requested_end_memory=60)
        cap = _cap(bounds=(0, 99))
        planner.allocate_memory_numbers(cands, cap, [], req)
        self.assertEqual(50, cands[0].memory_number)

    def test_capacity_exceeded_blocks_excess(self):
        cands = [_cand('A', 1), _cand('B', 2), _cand('C', 3)]
        cap = _cap(bounds=(0, 1))
        capacity_limited = planner.allocate_memory_numbers(
            cands, cap, [], models.ProgrammingRequest())
        self.assertTrue(capacity_limited)
        placed = [c for c in cands if c.include]
        self.assertEqual(2, len(placed))
        blocked = [c for c in cands if not c.include]
        self.assertEqual(1, len(blocked))
        self.assertTrue(blocked[0].reason)

    def test_full_capacity_does_not_silently_drop_from_plan(self):
        cands = [_cand('A', 1), _cand('B', 2)]
        req = models.ProgrammingRequest()
        cap = _cap(bounds=(0, 0))
        plan = planner.build_plan(cands, req, cap, [])
        # Both candidates still appear somewhere in the plan.
        self.assertEqual(2, len(plan.all_candidates))
        self.assertTrue(plan.capacity_limited)


class ChannelLimitTest(unittest.TestCase):
    def test_enforces_limit_keeping_best_scored(self):
        cands = [_cand('Far', 1, distance=10.0),
                 _cand('Near', 2, distance=1.0),
                 _cand('Mid', 3, distance=5.0)]
        req = models.ProgrammingRequest(channel_limit=2)
        limited = planner.enforce_channel_limit(cands, req)
        self.assertTrue(limited)
        included = [c.label for c in cands if c.include]
        self.assertEqual({'Near', 'Mid'}, set(included))

    def test_under_limit_no_op(self):
        cands = [_cand('A', 1)]
        req = models.ProgrammingRequest(channel_limit=10)
        limited = planner.enforce_channel_limit(cands, req)
        self.assertFalse(limited)
        self.assertTrue(cands[0].include)


class NamingTest(unittest.TestCase):
    def test_names_are_uppercase_and_length_limited(self):
        cands = [_cand('Repeater alpha', 1)]
        cap = _cap(name_length=6)
        planner.assign_names(cands, cap, models.NAMING_SHORT)
        self.assertEqual('REPEAT', cands[0].name)

    def test_collisions_get_distinct_names(self):
        cands = [_cand('Repeater A', 1), _cand('Repeater A', 2)]
        cap = _cap(name_length=6)
        planner.assign_names(cands, cap, models.NAMING_SHORT)
        self.assertNotEqual(cands[0].name, cands[1].name)

    def test_naming_is_deterministic(self):
        cap = _cap(name_length=6)
        cands1 = [_cand('Repeater A', 1), _cand('Repeater B', 2)]
        planner.assign_names(cands1, cap, models.NAMING_SHORT)
        cands2 = [_cand('Repeater A', 1), _cand('Repeater B', 2)]
        planner.assign_names(cands2, cap, models.NAMING_SHORT)
        self.assertEqual([c.name for c in cands1], [c.name for c in cands2])

    def test_lowercase_chars_only_charset_not_forced_upper(self):
        cands = [_cand('lower name', 1)]
        cap = _cap(name_length=10,
                   chars='abcdefghijklmnopqrstuvwxyz ')
        planner.assign_names(cands, cap, models.NAMING_SHORT)
        self.assertEqual(cands[0].name, cands[0].name.lower())


class BuildPlanIntegrationTest(unittest.TestCase):
    def test_full_pipeline_groups_and_orders(self):
        cands = [
            _cand('Repeater A', 146850000, 146250000, distance=1.0),
            _cand('GMRS 1', 462562500, service=models.SERVICE_GMRS),
        ]
        req = models.ProgrammingRequest(channel_limit=10)
        cap = _cap(bounds=(0, 99))
        plan = planner.build_plan(cands, req, cap, [])
        group_names = {g.name for g in plan.groups}
        self.assertIn('Local Amateur Repeaters', group_names)
        self.assertIn('GMRS', group_names)
        for c in plan.all_candidates:
            if c.include:
                self.assertIsNotNone(c.memory_number)
                self.assertTrue(c.name)


if __name__ == '__main__':
    unittest.main()
