import unittest

from chirp import chirp_common
from chirp.profiles import errors
from chirp.profiles import extraction
from chirp.profiles import schema
from tests.unit import fake_radios


class _NamedFakeRadio(fake_radios.FakeRadio):
    VENDOR = 'Acme'
    MODEL = 'Test-9000'
    VARIANT = ''

    def get_name(self):
        return '%s %s' % (self.VENDOR, self.MODEL)

    def get_mapping_models(self):
        return []


class _FakeMapping:
    def __init__(self, index, name):
        self._index = index
        self._name = name

    def get_name(self):
        return self._name

    def get_index(self):
        return self._index


class _FakeMappingModel:
    def __init__(self, mapping_by_number):
        self._mapping_by_number = mapping_by_number

    def get_memory_mappings(self, memory):
        mapping = self._mapping_by_number.get(memory.number)
        return [mapping] if mapping else []


class _RadioWithBanks(_NamedFakeRadio):
    def __init__(self, features, mapping_model):
        super().__init__(features)
        self._mapping_model = mapping_model

    def get_mapping_models(self):
        return [self._mapping_model]


def _mem(number, freq=146520000, name='', duplex='', offset=0, empty=False,
         skip='', comment='', power=None):
    m = chirp_common.Memory()
    m.number = number
    m.empty = empty
    m.freq = freq
    m.name = name
    m.duplex = duplex
    m.offset = offset
    m.skip = skip
    m.comment = comment
    m.power = power
    return m


class BasicExtractionTest(unittest.TestCase):
    def test_extracts_non_empty_memories(self):
        radio = _NamedFakeRadio(fake_radios.build_features(has_comment=True))
        memories = [_mem(0, name='CDA RPTR'), _mem(1, empty=True)]
        result = extraction.extract_profile(radio, memories)
        self.assertEqual(1, result.summary.channels_extracted)
        self.assertEqual(1, result.summary.channels_omitted)
        self.assertEqual(1, len(result.profile.channels))
        self.assertEqual('CDA RPTR', result.profile.channels[0].name)

    def test_special_channels_omitted(self):
        radio = _NamedFakeRadio(fake_radios.build_features())
        special = _mem(0, name='WX1')
        special.extd_number = 'WX1'
        result = extraction.extract_profile(radio, [special])
        self.assertEqual(0, result.summary.channels_extracted)
        self.assertEqual(1, result.summary.channels_omitted)


class LogicalIdGenerationTest(unittest.TestCase):
    def test_logical_id_derived_from_name(self):
        radio = _NamedFakeRadio(fake_radios.build_features())
        memories = [_mem(0, name='CDA Repeater')]
        result = extraction.extract_profile(radio, memories)
        logical_id = result.profile.channels[0].logical_id
        self.assertTrue(schema.is_valid_logical_id(logical_id))
        self.assertEqual('cda-repeater', logical_id)

    def test_unnamed_memory_falls_back_to_number(self):
        radio = _NamedFakeRadio(fake_radios.build_features())
        memories = [_mem(0, name='')]
        result = extraction.extract_profile(radio, memories)
        self.assertEqual('channel-0', result.profile.channels[0].logical_id)

    def test_duplicate_names_get_disambiguated(self):
        radio = _NamedFakeRadio(fake_radios.build_features())
        memories = [_mem(0, name='REPEATER'), _mem(1, name='REPEATER')]
        result = extraction.extract_profile(radio, memories)
        ids = [c.logical_id for c in result.profile.channels]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(['repeater', 'repeater-2'], ids)

    def test_source_memory_number_kept_only_as_provenance(self):
        radio = _NamedFakeRadio(fake_radios.build_features())
        memories = [_mem(5, name='X')]
        result = extraction.extract_profile(radio, memories)
        channel = result.profile.channels[0]
        self.assertFalse(hasattr(channel, 'number'))
        self.assertEqual(5, channel.source['source_memory_number'])


class ReceiveOnlyPreservationTest(unittest.TestCase):
    def test_off_duplex_extracted_as_receive_only(self):
        radio = _NamedFakeRadio(fake_radios.build_features())
        memories = [_mem(0, name='NOAA1', duplex='off')]
        result = extraction.extract_profile(radio, memories)
        channel = result.profile.channels[0]
        self.assertTrue(channel.receive_only)
        self.assertIn(channel.logical_id, result.summary.receive_only_detected)

    def test_ordinary_simplex_is_transmit_enabled(self):
        radio = _NamedFakeRadio(fake_radios.build_features())
        memories = [_mem(0, name='X', duplex='')]
        result = extraction.extract_profile(radio, memories)
        channel = result.profile.channels[0]
        self.assertFalse(channel.receive_only)
        self.assertEqual(schema.TRANSMIT_ENABLED, channel.transmit.mode)


class LostFieldReportingTest(unittest.TestCase):
    def test_comment_lost_when_target_has_no_comment_support(self):
        radio = _NamedFakeRadio(fake_radios.build_features(has_comment=False))
        memories = [_mem(0, name='X', comment='hello')]
        result = extraction.extract_profile(radio, memories)
        self.assertIn('comment', result.summary.fields_lost)
        self.assertEqual('', result.profile.channels[0].comment)

    def test_comment_preserved_when_supported(self):
        radio = _NamedFakeRadio(fake_radios.build_features(has_comment=True))
        memories = [_mem(0, name='X', comment='hello')]
        result = extraction.extract_profile(radio, memories)
        self.assertNotIn('comment', result.summary.fields_lost)
        self.assertEqual('hello', result.profile.channels[0].comment)

    def test_skip_state_reported_as_converted(self):
        radio = _NamedFakeRadio(fake_radios.build_features())
        memories = [_mem(0, name='X', skip='S')]
        result = extraction.extract_profile(radio, memories)
        self.assertIn('scan/skip state', result.summary.fields_converted)
        self.assertEqual(schema.SCAN_INTENT_SKIP,
                         result.profile.channels[0].scan_intent)

    def test_bank_membership_unknown_reported_when_no_mapping_support(self):
        radio = _NamedFakeRadio(fake_radios.build_features(has_bank=True))

        def _raise():
            raise NotImplementedError()
        radio.get_mapping_models = _raise
        memories = [_mem(0, name='X')]
        result = extraction.extract_profile(radio, memories)
        self.assertTrue(any('bank/group' in f
                            for f in result.summary.fields_lost))


class GroupExtractionTest(unittest.TestCase):
    def test_bank_membership_extracted_when_available(self):
        mapping_model = _FakeMappingModel(
            {0: _FakeMapping(1, 'Local Repeaters')})
        radio = _RadioWithBanks(
            fake_radios.build_features(has_bank=True), mapping_model)
        memories = [_mem(0, name='X')]
        result = extraction.extract_profile(radio, memories)
        channel = result.profile.channels[0]
        self.assertIn('local-repeaters', channel.groups)
        self.assertIn('local-repeaters', result.profile.groups)
        self.assertEqual('Local Repeaters',
                         result.profile.groups['local-repeaters'].name)


class DeterminismTest(unittest.TestCase):
    def test_same_memories_produce_same_profile_structure(self):
        radio = _NamedFakeRadio(fake_radios.build_features())
        memories = [_mem(0, name='A'), _mem(1, name='B')]
        r1 = extraction.extract_profile(radio, memories)
        r2 = extraction.extract_profile(radio, memories)
        ids1 = [c.logical_id for c in r1.profile.channels]
        ids2 = [c.logical_id for c in r2.profile.channels]
        self.assertEqual(ids1, ids2)


class _BoundedMemoryRadio(_NamedFakeRadio):
    """A fixed-capacity radio: get_memory() works for the declared
    memory_bounds range and nowhere else, matching how a real
    hardware/image-backed driver behaves."""

    def __init__(self, memories):
        features = fake_radios.build_features(
            memory_bounds=(0, len(memories) - 1))
        super().__init__(features)
        self._memories = list(memories)

    def get_memory(self, number):
        return self._memories[number]


class _DynamicMemoryRadio(_NamedFakeRadio):
    """A dynamic, file-backed radio in the same shape as
    chirp.drivers.generic_csv.CSVRadio: has_infinite_number=True (no
    fixed ceiling on how large the backing list may grow later), but
    memory_bounds always reflects the *actual current* length of a
    real, concrete, in-memory list -- never an unbounded range."""

    def __init__(self, memories):
        features = fake_radios.build_features(
            memory_bounds=(0, len(memories) - 1),
            has_infinite_number=True)
        super().__init__(features)
        self._memories = list(memories)

    def get_memory(self, number):
        return self._memories[number]


class _FlakyReadRadio(_BoundedMemoryRadio):
    """Raises reading one specific memory number, to prove a single
    bad read does not abort enumeration of the rest."""

    def __init__(self, memories, fail_number):
        super().__init__(memories)
        self._fail_number = fail_number

    def get_memory(self, number):
        if number == self._fail_number:
            raise IOError('simulated read failure')
        return super().get_memory(number)


class _MalformedFeatures:
    """A real chirp_common.RadioFeatures validates memory_bounds on
    every assignment (a 2-item NTUPLE), so no conformant driver can
    ever produce a malformed value there -- this plain stand-in exists
    only to prove enumerate_source_memories() fails closed with a
    specific, typed error rather than an unhandled exception, should
    some later or otherwise adversarial get_features() implementation
    ever manage to return one anyway."""

    memory_bounds = None


class _UnenumerableRadio:
    """A radio whose declared memory_bounds cannot be interpreted as a
    (lo, hi) pair at all -- the only case enumerate_source_memories()
    still refuses, regardless of has_infinite_number."""

    def get_features(self):
        return _MalformedFeatures()

    def get_memory(self, number):
        raise AssertionError('should never be called')


class EnumerateSourceMemoriesTest(unittest.TestCase):
    def test_fixed_capacity_radio_enumerates_full_declared_range(self):
        memories = [_mem(i, name='CH%d' % i, empty=(i % 2 == 0))
                    for i in range(5)]
        radio = _BoundedMemoryRadio(memories)
        result = extraction.enumerate_source_memories(radio)
        self.assertEqual([m.number for m in memories],
                         [m.number for m in result])

    def test_dynamic_radio_is_no_longer_refused(self):
        memories = [_mem(0, name='TEST', empty=False)]
        radio = _DynamicMemoryRadio(memories)
        result = extraction.enumerate_source_memories(radio)
        self.assertEqual(1, len(result))
        self.assertEqual('TEST', result[0].name)

    def test_dynamic_radio_enumerates_exactly_its_current_bounds(self):
        # No arbitrary ceiling (100/500/1000/...) is ever invented --
        # a 3-row backing list yields exactly 3 enumerated slots.
        memories = [_mem(i, empty=True) for i in range(3)]
        radio = _DynamicMemoryRadio(memories)
        result = extraction.enumerate_source_memories(radio)
        self.assertEqual(3, len(result))

    def test_dynamic_radio_partially_populated_extracts_only_populated(
            self):
        memories = [
            _mem(0, name='A', empty=False),
            _mem(1, empty=True),
            _mem(2, name='B', empty=False),
            _mem(3, empty=True),
        ]
        radio = _DynamicMemoryRadio(memories)
        enumerated = extraction.enumerate_source_memories(radio)
        result = extraction.extract_profile(radio, enumerated)
        names = [c.name for c in result.profile.channels]
        self.assertEqual(['A', 'B'], names)
        self.assertEqual(2, result.summary.channels_extracted)
        self.assertEqual(2, result.summary.channels_omitted)

    def test_dynamic_radio_entirely_empty_produces_zero_channels(self):
        memories = [_mem(i, empty=True) for i in range(4)]
        radio = _DynamicMemoryRadio(memories)
        enumerated = extraction.enumerate_source_memories(radio)
        result = extraction.extract_profile(radio, enumerated)
        self.assertEqual(0, result.summary.channels_extracted)
        self.assertEqual(0, len(result.profile.channels))

    def test_flaky_read_is_skipped_not_fatal(self):
        memories = [_mem(i, name='CH%d' % i, empty=False) for i in range(3)]
        radio = _FlakyReadRadio(memories, fail_number=1)
        result = extraction.enumerate_source_memories(radio)
        self.assertEqual(2, len(result))
        self.assertEqual(['CH0', 'CH2'], [m.name for m in result])

    def test_unenumerable_radio_raises_capability_unknown_error(self):
        radio = _UnenumerableRadio()
        with self.assertRaises(errors.CapabilityUnknownError):
            extraction.enumerate_source_memories(radio)

    def test_dynamic_radio_ordering_is_deterministic(self):
        memories = [_mem(i, name='CH%d' % i, empty=False)
                    for i in range(6)]
        radio = _DynamicMemoryRadio(memories)
        r1 = [m.number for m in extraction.enumerate_source_memories(radio)]
        r2 = [m.number for m in extraction.enumerate_source_memories(radio)]
        self.assertEqual(r1, r2)
        self.assertEqual(list(range(6)), r1)
