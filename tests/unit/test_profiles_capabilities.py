import unittest

from chirp.profiles import capabilities
from tests.unit import fake_radios


class MemoryBoundsTest(unittest.TestCase):
    def test_bounded_radio_reports_count(self):
        caps = capabilities.for_radio(fake_radios.limited_analog_handheld())
        self.assertEqual((0, 127), caps.memory_bounds)
        self.assertEqual(128, caps.num_memories)

    def test_infinite_number_radio_reports_unbounded(self):
        radio = fake_radios.FakeRadio(
            fake_radios.build_features(has_infinite_number=True))
        caps = capabilities.for_radio(radio)
        self.assertIsNone(caps.memory_bounds)
        self.assertIsNone(caps.num_memories)


class BandCheckTest(unittest.TestCase):
    def test_in_band_frequency(self):
        caps = capabilities.for_radio(fake_radios.restricted_range_radio())
        self.assertTrue(caps.frequency_in_band(146520000))

    def test_out_of_band_frequency(self):
        caps = capabilities.for_radio(fake_radios.restricted_range_radio())
        self.assertFalse(caps.frequency_in_band(162550000))

    def test_no_declared_bands_means_not_restricted(self):
        radio = fake_radios.FakeRadio(fake_radios.build_features())
        caps = capabilities.for_radio(radio)
        self.assertIsNone(caps.valid_bands)
        self.assertTrue(caps.frequency_in_band(1))
        self.assertTrue(caps.frequency_in_band(999999999999))


class ReceiveOnlyEnforcementTest(unittest.TestCase):
    def test_radio_with_off_duplex_can_enforce(self):
        caps = capabilities.for_radio(fake_radios.limited_analog_handheld())
        self.assertTrue(caps.can_enforce_receive_only())

    def test_radio_without_off_duplex_cannot_enforce(self):
        caps = capabilities.for_radio(
            fake_radios.cannot_enforce_receive_only_radio())
        self.assertFalse(caps.can_enforce_receive_only())


class ModeAndToneTest(unittest.TestCase):
    def test_analog_only_radio_rejects_digital_mode(self):
        caps = capabilities.for_radio(fake_radios.analog_only_radio())
        self.assertFalse(caps.supports_mode('DMR'))
        self.assertTrue(caps.supports_mode('FM'))

    def test_dtcs_support_reflects_flag(self):
        rich = capabilities.for_radio(fake_radios.feature_rich_radio())
        limited = capabilities.for_radio(
            fake_radios.limited_analog_handheld())
        self.assertTrue(rich.supports_dtcs())
        self.assertFalse(limited.supports_dtcs())


class NamingTest(unittest.TestCase):
    def test_short_name_radio_reports_length(self):
        caps = capabilities.for_radio(fake_radios.short_name_radio())
        self.assertEqual(4, caps.name_length)

    def test_no_name_support_reports_zero_length(self):
        radio = fake_radios.FakeRadio(
            fake_radios.build_features(has_name=False))
        caps = capabilities.for_radio(radio)
        self.assertFalse(caps.supports_names())
        self.assertEqual(0, caps.name_length)


class BankSupportTest(unittest.TestCase):
    def test_no_bank_radio_reports_false(self):
        caps = capabilities.for_radio(fake_radios.no_bank_radio())
        self.assertFalse(caps.supports_banks())

    def test_feature_rich_radio_reports_true(self):
        caps = capabilities.for_radio(fake_radios.feature_rich_radio())
        self.assertTrue(caps.supports_banks())
        self.assertTrue(caps.supports_named_banks())


class UnmodeledCapabilityTest(unittest.TestCase):
    def test_scan_list_support_is_unknown(self):
        caps = capabilities.for_radio(fake_radios.feature_rich_radio())
        self.assertIsNone(caps.scan_list_support())

    def test_empty_memory_behavior_is_unknown(self):
        caps = capabilities.for_radio(fake_radios.feature_rich_radio())
        self.assertIsNone(caps.empty_memory_behavior())


class ImmutableFieldsTest(unittest.TestCase):
    def test_immutable_fields_read_from_memory(self):
        mem = fake_radios.immutable_memory()
        self.assertEqual(['freq', 'name'], capabilities.immutable_fields(mem))


class ValidateMemoryDelegationTest(unittest.TestCase):
    def test_delegates_to_radio_features_validate_memory(self):
        caps = capabilities.for_radio(fake_radios.restricted_range_radio())
        from chirp import chirp_common
        mem = chirp_common.Memory()
        mem.number = 0
        mem.freq = 162550000  # out of this radio's declared band
        msgs = caps.validate_memory(mem)
        self.assertTrue(any('out' in str(m).lower() for m in msgs))
