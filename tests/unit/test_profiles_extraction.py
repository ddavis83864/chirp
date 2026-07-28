import unittest

from chirp import chirp_common
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
