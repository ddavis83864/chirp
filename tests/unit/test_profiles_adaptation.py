import unittest

from chirp.profiles import adaptation
from chirp.profiles import capabilities
from chirp.profiles import model
from chirp.profiles import schema
from tests.unit import fake_radios


def _profile(**defaults_kwargs):
    return model.Profile(name='Test',
                         defaults=model.ProfileDefaults(**defaults_kwargs))


class NameAdaptationTest(unittest.TestCase):
    def test_name_that_fits_is_unchanged(self):
        name, changed, notes = adaptation.adapt_name('CDA', 6, None)
        self.assertEqual('CDA', name)
        self.assertFalse(changed)
        self.assertEqual([], notes)

    def test_deterministic_abbreviation(self):
        result1 = adaptation.adapt_name('REPEATER', 4, None)
        result2 = adaptation.adapt_name('REPEATER', 4, None)
        self.assertEqual(result1, result2)
        name, changed, notes = result1
        self.assertLessEqual(len(name), 4)
        self.assertTrue(changed)
        self.assertTrue(notes)

    def test_invalid_characters_filtered_and_reported(self):
        from chirp import chirp_common
        name, changed, notes = adaptation.adapt_name(
            'café!', 16, chirp_common.CHARSET_UPPER_NUMERIC)
        self.assertTrue(changed)
        self.assertTrue(any('charset' in n for n in notes))

    def test_name_dropped_entirely_is_reported(self):
        name, changed, notes = adaptation.adapt_name('café', 16, '0123456789')
        # every character invalid for a digits-only charset -> empty result
        self.assertEqual('', name)
        self.assertTrue(any('dropped' in n for n in notes))

    def test_hard_truncate_fallback_when_no_vowels_left(self):
        name, changed, notes = adaptation.adapt_name('BCDFGHJKL', 4, None)
        self.assertEqual(4, len(name))
        self.assertTrue(changed)


class ExactClassificationTest(unittest.TestCase):
    def test_ordinary_repeater_channel_is_exact(self):
        caps = capabilities.for_radio(fake_radios.feature_rich_radio())
        profile = _profile(mode='FM')
        channel = model.ProfileChannel(
            logical_id='local-cda-2m-repeater-01',
            name='CDA RPTR',
            rx_freq_hz=146520000,
            transmit=model.TransmitBehavior(
                mode=schema.TRANSMIT_ENABLED, duplex=schema.DUPLEX_POSITIVE,
                offset_hz=600000),
        )
        result = adaptation.adapt_channel(profile, channel, caps)
        self.assertEqual(schema.CLASS_EXACT, result.classification)
        self.assertFalse(result.blocked)
        self.assertFalse(result.requires_user_action)
        self.assertIsNotNone(result.proposed_memory)
        self.assertEqual('+', result.proposed_memory.duplex)


class ReceiveOnlyPreservationTest(unittest.TestCase):
    def test_receive_only_channel_proposed_as_off_duplex(self):
        caps = capabilities.for_radio(fake_radios.feature_rich_radio())
        profile = _profile()
        channel = model.ProfileChannel(
            logical_id='noaa-weather-01',
            name='NOAA1',
            rx_freq_hz=162550000,
            transmit=model.TransmitBehavior(
                mode=schema.TRANSMIT_RECEIVE_ONLY))
        result = adaptation.adapt_channel(profile, channel, caps)
        self.assertFalse(result.blocked)
        self.assertEqual('off', result.proposed_memory.duplex)

    def test_receive_only_channel_on_radio_that_cannot_enforce_it_is_unsafe(
            self):
        caps = capabilities.for_radio(
            fake_radios.cannot_enforce_receive_only_radio())
        profile = _profile()
        channel = model.ProfileChannel(
            logical_id='aviation-emergency-guard',
            rx_freq_hz=146520000,
            transmit=model.TransmitBehavior(
                mode=schema.TRANSMIT_RECEIVE_ONLY))
        result = adaptation.adapt_channel(profile, channel, caps)
        self.assertEqual(schema.CLASS_UNSAFE, result.classification)
        self.assertTrue(result.blocked)
        self.assertIsNone(result.proposed_memory)

    def test_unspecified_transmit_defaults_to_receive_only_not_enabled(self):
        caps = capabilities.for_radio(fake_radios.feature_rich_radio())
        profile = _profile()
        channel = model.ProfileChannel(
            logical_id='x-1', rx_freq_hz=146520000,
            transmit=model.TransmitBehavior(
                mode=schema.TRANSMIT_UNSPECIFIED))
        result = adaptation.adapt_channel(profile, channel, caps)
        self.assertEqual(schema.CLASS_DEGRADED, result.classification)
        self.assertFalse(result.blocked)
        self.assertEqual('off', result.proposed_memory.duplex)
        self.assertIn('transmit permission', result.lost)

    def test_out_of_band_transmit_falls_back_to_receive_only(self):
        caps = capabilities.for_radio(fake_radios.restricted_range_radio())
        profile = _profile()
        # A +100MHz offset pushes tx frequency out of this radio's one
        # declared band.
        channel = model.ProfileChannel(
            logical_id='x-2', rx_freq_hz=146520000,
            transmit=model.TransmitBehavior(
                mode=schema.TRANSMIT_ENABLED, duplex=schema.DUPLEX_POSITIVE,
                offset_hz=100000000))
        result = adaptation.adapt_channel(profile, channel, caps)
        self.assertEqual(schema.CLASS_DEGRADED, result.classification)
        self.assertFalse(result.blocked)
        self.assertEqual('off', result.proposed_memory.duplex)

    def test_out_of_band_transmit_with_no_off_duplex_is_unsafe(self):
        caps = capabilities.for_radio(
            fake_radios.cannot_enforce_receive_only_radio())
        profile = _profile()
        channel = model.ProfileChannel(
            logical_id='x-3', rx_freq_hz=146520000,
            transmit=model.TransmitBehavior(
                mode=schema.TRANSMIT_ENABLED, duplex=schema.DUPLEX_POSITIVE,
                offset_hz=100000000))  # pushes tx freq out of band
        result = adaptation.adapt_channel(profile, channel, caps)
        self.assertEqual(schema.CLASS_UNSAFE, result.classification)
        self.assertTrue(result.blocked)


class IncompatibleClassificationTest(unittest.TestCase):
    def test_frequency_out_of_range_is_incompatible(self):
        caps = capabilities.for_radio(fake_radios.restricted_range_radio())
        profile = _profile()
        channel = model.ProfileChannel(
            logical_id='x-1', rx_freq_hz=162550000,
            transmit=model.TransmitBehavior(mode=schema.TRANSMIT_ENABLED))
        result = adaptation.adapt_channel(profile, channel, caps)
        self.assertEqual(schema.CLASS_INCOMPATIBLE, result.classification)
        self.assertIsNone(result.proposed_memory)

    def test_digital_mode_on_analog_only_radio_is_incompatible(self):
        caps = capabilities.for_radio(fake_radios.analog_only_radio())
        profile = _profile(mode='DMR')
        channel = model.ProfileChannel(
            logical_id='x-1', rx_freq_hz=146520000,
            transmit=model.TransmitBehavior(mode=schema.TRANSMIT_ENABLED))
        result = adaptation.adapt_channel(profile, channel, caps)
        self.assertEqual(schema.CLASS_INCOMPATIBLE, result.classification)

    def test_unsupported_tone_mode_is_incompatible(self):
        caps = capabilities.for_radio(fake_radios.limited_analog_handheld())
        profile = _profile()
        channel = model.ProfileChannel(
            logical_id='x-1', rx_freq_hz=146520000,
            tone_mode='DTCS',
            transmit=model.TransmitBehavior(mode=schema.TRANSMIT_ENABLED))
        result = adaptation.adapt_channel(profile, channel, caps)
        self.assertEqual(schema.CLASS_INCOMPATIBLE, result.classification)


class DegradedClassificationTest(unittest.TestCase):
    def test_comment_dropped_on_target_without_comment_support(self):
        caps = capabilities.for_radio(fake_radios.limited_analog_handheld())
        profile = _profile()
        channel = model.ProfileChannel(
            logical_id='x-1', rx_freq_hz=146520000, comment='hello',
            transmit=model.TransmitBehavior(mode=schema.TRANSMIT_ENABLED))
        result = adaptation.adapt_channel(profile, channel, caps)
        self.assertEqual(schema.CLASS_DEGRADED, result.classification)
        self.assertIn('comment', result.lost)

    def test_groups_lost_on_radio_without_banks(self):
        caps = capabilities.for_radio(fake_radios.no_bank_radio())
        profile = _profile()
        profile.groups['local-repeaters'] = model.LogicalGroup(
            id='local-repeaters', name='Local Repeaters')
        channel = model.ProfileChannel(
            logical_id='x-1', rx_freq_hz=146520000,
            groups=('local-repeaters',),
            transmit=model.TransmitBehavior(mode=schema.TRANSMIT_ENABLED))
        result = adaptation.adapt_channel(profile, channel, caps)
        self.assertEqual(schema.CLASS_DEGRADED, result.classification)
        self.assertIn('group membership', result.lost)


class AdaptedClassificationTest(unittest.TestCase):
    def test_long_name_abbreviated_is_adapted(self):
        caps = capabilities.for_radio(fake_radios.short_name_radio())
        profile = _profile()
        channel = model.ProfileChannel(
            logical_id='x-1', name='REPEATER ONE', rx_freq_hz=146520000,
            transmit=model.TransmitBehavior(mode=schema.TRANSMIT_ENABLED))
        result = adaptation.adapt_channel(profile, channel, caps)
        self.assertIn(result.classification,
                      (schema.CLASS_ADAPTED, schema.CLASS_DEGRADED))
        self.assertLessEqual(len(result.proposed_memory.name), 4)

    def test_power_tier_mapped_to_nearest_level(self):
        caps = capabilities.for_radio(fake_radios.limited_analog_handheld())
        profile = _profile(
            power_preference=model.PowerPreference(tier='medium'))
        channel = model.ProfileChannel(
            logical_id='x-1', rx_freq_hz=146520000,
            transmit=model.TransmitBehavior(mode=schema.TRANSMIT_ENABLED))
        result = adaptation.adapt_channel(profile, channel, caps)
        self.assertIsNotNone(result.proposed_memory.power)


class DeterminismTest(unittest.TestCase):
    def test_same_inputs_produce_identical_result(self):
        caps = capabilities.for_radio(fake_radios.feature_rich_radio())
        profile = _profile(mode='FM')
        channel = model.ProfileChannel(
            logical_id='x-1', name='TEST', rx_freq_hz=146520000,
            transmit=model.TransmitBehavior(mode=schema.TRANSMIT_ENABLED))
        r1 = adaptation.adapt_channel(profile, channel, caps)
        r2 = adaptation.adapt_channel(profile, channel, caps)
        self.assertEqual(r1.classification, r2.classification)
        self.assertEqual(r1.reason_code, r2.reason_code)
        self.assertEqual(r1.proposed, r2.proposed)
        self.assertEqual(r1.lost, r2.lost)
