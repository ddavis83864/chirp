import unittest

from chirp.profiles import model
from chirp.profiles import safety
from chirp.profiles import schema


class ReceiveOnlyPreservationTest(unittest.TestCase):
    def test_receive_only_channel_with_off_duplex_is_safe(self):
        ch = model.ProfileChannel(
            logical_id='noaa-weather-01',
            transmit=model.TransmitBehavior(
                mode=schema.TRANSMIT_RECEIVE_ONLY))
        self.assertIsNone(safety.check_receive_only_preserved(ch, 'off'))

    def test_receive_only_channel_proposed_as_transmit_capable_is_unsafe(self):
        ch = model.ProfileChannel(
            logical_id='aviation-emergency-guard',
            transmit=model.TransmitBehavior(
                mode=schema.TRANSMIT_RECEIVE_ONLY))
        for bad_duplex in ('', '+', '-', 'split'):
            violation = safety.check_receive_only_preserved(ch, bad_duplex)
            self.assertIsNotNone(violation, bad_duplex)
            self.assertEqual(
                safety.REASON_RX_ONLY_WOULD_TRANSMIT, violation.reason_code)
            self.assertEqual('aviation-emergency-guard', violation.logical_id)

    def test_transmit_enabled_channel_is_unaffected(self):
        ch = model.ProfileChannel(
            logical_id='local-simplex-01',
            transmit=model.TransmitBehavior(mode=schema.TRANSMIT_ENABLED))
        self.assertIsNone(safety.check_receive_only_preserved(ch, '+'))
        self.assertIsNone(safety.check_receive_only_preserved(ch, 'off'))


class OverrideSafetyTest(unittest.TestCase):
    def test_override_cannot_carry_transmit_permission_field(self):
        override = model.TargetOverride(
            selector=model.TargetSelector(scope=schema.SELECTOR_MODEL,
                                          value='FT-60'),
            fields={'transmit_mode': schema.TRANSMIT_ENABLED})
        violation = safety.check_override_does_not_remove_safety(override)
        self.assertIsNotNone(violation)
        self.assertEqual(safety.REASON_OVERRIDE_REMOVES_SAFETY,
                         violation.reason_code)

    def test_override_with_only_allowed_fields_is_safe(self):
        override = model.TargetOverride(
            selector=model.TargetSelector(scope=schema.SELECTOR_MODEL,
                                          value='FT-60'),
            fields={'name': 'ABBREV'})
        self.assertIsNone(safety.check_override_does_not_remove_safety(
            override))


class UnknownCapabilityFailsClosedTest(unittest.TestCase):
    def test_none_capability_reported_as_unknown_not_assumed_safe(self):
        violation = safety.check_capability_known('has_dtcs', None)
        self.assertIsNotNone(violation)
        self.assertEqual(safety.REASON_UNKNOWN_CAPABILITY,
                         violation.reason_code)

    def test_known_capability_value_passes(self):
        self.assertIsNone(safety.check_capability_known('has_dtcs', True))
        self.assertIsNone(safety.check_capability_known('has_dtcs', False))
