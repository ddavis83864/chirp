import unittest

from chirp import chirp_common
from chirp.profiles import capabilities
from chirp.profiles import placement
from chirp.profiles import schema
from tests.unit import fake_radios


def _mem(number, empty=False, immutable=None):
    m = chirp_common.Memory()
    m.number = number
    m.empty = empty
    if not empty:
        m.freq = 146520000
    m.immutable = immutable or []
    return m


class FillEmptyTest(unittest.TestCase):
    def test_fills_lowest_empty_numbers_first(self):
        caps = capabilities.for_radio(fake_radios.limited_analog_handheld())
        existing = [
            _mem(0), _mem(1, empty=True), _mem(2, empty=True), _mem(3)]
        decisions = placement.plan_placement(
            ['a', 'b'], existing, caps, schema.PLACEMENT_FILL_EMPTY)
        self.assertEqual([1, 2], [d.memory_number for d in decisions])
        self.assertFalse(any(d.replaces_existing for d in decisions))

    def test_never_claims_occupied_memory(self):
        caps = capabilities.for_radio(fake_radios.limited_analog_handheld())
        existing = [_mem(0), _mem(1)]
        decisions = placement.plan_placement(
            ['a'], existing, caps, schema.PLACEMENT_FILL_EMPTY)
        self.assertNotIn(decisions[0].memory_number, (0, 1))

    def test_runs_out_of_empty_slots(self):
        caps = capabilities.for_radio(fake_radios.short_name_radio())
        existing = [_mem(n) for n in range(caps.memory_bounds[1] + 1)]
        decisions = placement.plan_placement(
            ['a'], existing, caps, schema.PLACEMENT_FILL_EMPTY)
        self.assertIsNone(decisions[0].memory_number)
        self.assertEqual(schema.CONFLICT_CAPACITY_EXCEEDED,
                         decisions[0].conflict_reason)

    def test_immutable_memory_never_treated_as_available(self):
        caps = capabilities.for_radio(fake_radios.limited_analog_handheld())
        existing = [_mem(0, empty=True, immutable=['freq'])]
        decisions = placement.plan_placement(
            ['a'], existing, caps, schema.PLACEMENT_FILL_EMPTY)
        self.assertNotEqual(0, decisions[0].memory_number)


class AppendTest(unittest.TestCase):
    def test_appends_after_highest_used_number(self):
        caps = capabilities.for_radio(fake_radios.limited_analog_handheld())
        existing = [_mem(0), _mem(1), _mem(2, empty=True)]
        decisions = placement.plan_placement(
            ['a'], existing, caps, schema.PLACEMENT_APPEND)
        self.assertEqual(2, decisions[0].memory_number)

    def test_append_sequential_for_multiple_channels(self):
        caps = capabilities.for_radio(fake_radios.limited_analog_handheld())
        existing = [_mem(0)]
        decisions = placement.plan_placement(
            ['a', 'b', 'c'], existing, caps, schema.PLACEMENT_APPEND)
        self.assertEqual([1, 2, 3], [d.memory_number for d in decisions])

    def test_append_respects_upper_bound(self):
        caps = capabilities.for_radio(fake_radios.short_name_radio())
        hi = caps.memory_bounds[1]
        existing = [_mem(hi)]
        decisions = placement.plan_placement(
            ['a'], existing, caps, schema.PLACEMENT_APPEND)
        self.assertIsNone(decisions[0].memory_number)
        self.assertEqual(schema.CONFLICT_CAPACITY_EXCEEDED,
                         decisions[0].conflict_reason)


class ReplaceRangeTest(unittest.TestCase):
    def test_uses_explicit_numbers_in_order(self):
        caps = capabilities.for_radio(fake_radios.limited_analog_handheld())
        decisions = placement.plan_placement(
            ['a', 'b'], [], caps, schema.PLACEMENT_REPLACE_RANGE,
            explicit_range=[10, 11])
        self.assertEqual([10, 11], [d.memory_number for d in decisions])

    def test_marks_replacement_of_occupied_memory(self):
        caps = capabilities.for_radio(fake_radios.limited_analog_handheld())
        existing = [_mem(10)]
        decisions = placement.plan_placement(
            ['a'], existing, caps, schema.PLACEMENT_REPLACE_RANGE,
            explicit_range=[10])
        self.assertTrue(decisions[0].replaces_existing)

    def test_refuses_immutable_memory_even_in_explicit_range(self):
        caps = capabilities.for_radio(fake_radios.limited_analog_handheld())
        existing = [_mem(10, immutable=['freq'])]
        decisions = placement.plan_placement(
            ['a'], existing, caps, schema.PLACEMENT_REPLACE_RANGE,
            explicit_range=[10])
        self.assertIsNone(decisions[0].memory_number)
        self.assertEqual(schema.CONFLICT_IMMUTABLE_MEMORY,
                         decisions[0].conflict_reason)

    def test_range_shorter_than_channel_list_is_capacity_exceeded(self):
        caps = capabilities.for_radio(fake_radios.limited_analog_handheld())
        decisions = placement.plan_placement(
            ['a', 'b'], [], caps, schema.PLACEMENT_REPLACE_RANGE,
            explicit_range=[10])
        self.assertEqual(10, decisions[0].memory_number)
        self.assertIsNone(decisions[1].memory_number)
        self.assertEqual(schema.CONFLICT_CAPACITY_EXCEEDED,
                         decisions[1].conflict_reason)

    def test_out_of_bounds_number_rejected(self):
        caps = capabilities.for_radio(fake_radios.limited_analog_handheld())
        hi = caps.memory_bounds[1]
        decisions = placement.plan_placement(
            ['a'], [], caps, schema.PLACEMENT_REPLACE_RANGE,
            explicit_range=[hi + 100])
        self.assertIsNone(decisions[0].memory_number)


class DeterminismTest(unittest.TestCase):
    def test_same_inputs_produce_same_plan(self):
        caps = capabilities.for_radio(fake_radios.limited_analog_handheld())
        existing = [_mem(0), _mem(1, empty=True)]
        d1 = placement.plan_placement(
            ['a', 'b'], existing, caps, schema.PLACEMENT_FILL_EMPTY)
        d2 = placement.plan_placement(
            ['a', 'b'], existing, caps, schema.PLACEMENT_FILL_EMPTY)
        self.assertEqual([d.memory_number for d in d1],
                         [d.memory_number for d in d2])


class InvalidStrategyTest(unittest.TestCase):
    def test_unknown_strategy_raises(self):
        caps = capabilities.for_radio(fake_radios.limited_analog_handheld())
        with self.assertRaises(ValueError):
            placement.plan_placement(['a'], [], caps, 'not_a_strategy')
