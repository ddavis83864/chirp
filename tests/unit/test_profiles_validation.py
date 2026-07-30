import unittest

from chirp.profiles import errors
from chirp.profiles import model
from chirp.profiles import schema
from chirp.profiles import validation


def _valid_profile():
    p = model.Profile(name='Test Profile')
    p.groups['local-repeaters'] = model.LogicalGroup(
        id='local-repeaters', name='Local Repeaters')
    p.add_channel(model.ProfileChannel(
        logical_id='local-cda-2m-repeater-01',
        name='CDA Repeater',
        rx_freq_hz=146520000,
        transmit=model.TransmitBehavior(mode=schema.TRANSMIT_ENABLED,
                                        duplex=schema.DUPLEX_POSITIVE,
                                        offset_hz=600000),
        groups=('local-repeaters',),
    ))
    return p


class ValidProfileTest(unittest.TestCase):
    def test_freshly_built_profile_is_valid(self):
        issues = validation.validate_profile(_valid_profile())
        self.assertEqual([], issues, [str(i) for i in issues])


class DuplicateLogicalIdTest(unittest.TestCase):
    def test_duplicate_logical_ids_reported(self):
        p = _valid_profile()
        p.add_channel(model.ProfileChannel(
            logical_id='local-cda-2m-repeater-01', rx_freq_hz=146540000))
        issues = validation.validate_profile(p)
        self.assertTrue(any('Duplicate logical_id' in i.message
                            for i in issues))

    def test_duplicate_logical_id_raises_on_strict_load(self):
        p = _valid_profile()
        p.add_channel(model.ProfileChannel(
            logical_id='local-cda-2m-repeater-01', rx_freq_hz=146540000))
        with self.assertRaises(errors.ProfileValidationError):
            validation.validate_profile_or_raise(p)


class LogicalIdValidationTest(unittest.TestCase):
    def test_invalid_logical_id_reported_with_path(self):
        p = _valid_profile()
        p.channels[0].logical_id = 'Not A Valid Id!'
        issues = validation.validate_profile(p)
        self.assertTrue(any(i.path == 'channels[0].logical_id'
                            for i in issues))


class FrequencyValidationTest(unittest.TestCase):
    def test_zero_frequency_rejected(self):
        p = _valid_profile()
        p.channels[0].rx_freq_hz = 0
        issues = validation.validate_profile(p)
        self.assertTrue(any('rx_freq_hz' in i.path for i in issues))

    def test_float_frequency_rejected(self):
        p = _valid_profile()
        p.channels[0].rx_freq_hz = 146520000.5
        issues = validation.validate_profile(p)
        self.assertTrue(any('rx_freq_hz' in i.path for i in issues))

    def test_negative_frequency_rejected(self):
        p = _valid_profile()
        p.channels[0].rx_freq_hz = -1
        issues = validation.validate_profile(p)
        self.assertTrue(any('rx_freq_hz' in i.path for i in issues))

    def test_split_duplex_requires_tx_freq(self):
        p = _valid_profile()
        p.channels[0].transmit = model.TransmitBehavior(
            mode=schema.TRANSMIT_ENABLED, duplex=schema.DUPLEX_SPLIT)
        issues = validation.validate_profile(p)
        self.assertTrue(any('tx_freq_hz' in i.path for i in issues))


class EnumValidationTest(unittest.TestCase):
    def test_invalid_mode_rejected(self):
        p = _valid_profile()
        p.channels[0].mode = 'NOT_A_MODE'
        issues = validation.validate_profile(p)
        self.assertTrue(any(i.path == 'channels[0].mode' for i in issues))

    def test_invalid_tone_mode_rejected(self):
        p = _valid_profile()
        p.channels[0].tone_mode = 'NOT_A_TONE_MODE'
        issues = validation.validate_profile(p)
        self.assertTrue(any(i.path == 'channels[0].tone_mode'
                            for i in issues))

    def test_invalid_transmit_mode_rejected(self):
        p = _valid_profile()
        p.channels[0].transmit.mode = 'bogus'
        issues = validation.validate_profile(p)
        self.assertTrue(any('transmit.mode' in i.path for i in issues))

    def test_invalid_duplex_rejected(self):
        p = _valid_profile()
        p.channels[0].transmit.duplex = 'bogus'
        issues = validation.validate_profile(p)
        self.assertTrue(any('transmit.duplex' in i.path for i in issues))

    def test_invalid_power_tier_rejected(self):
        p = _valid_profile()
        p.channels[0].power_preference = model.PowerPreference(tier='ultra')
        issues = validation.validate_profile(p)
        self.assertTrue(any('power_preference.tier' in i.path
                            for i in issues))


class GroupReferenceTest(unittest.TestCase):
    def test_channel_referencing_unknown_group_rejected(self):
        p = _valid_profile()
        p.channels[0].groups = ('does-not-exist',)
        issues = validation.validate_profile(p)
        self.assertTrue(any('unknown group' in i.message for i in issues))

    def test_override_referencing_unknown_group_rejected(self):
        p = _valid_profile()
        p.channels[0].overrides = (model.TargetOverride(
            selector=model.TargetSelector(scope=schema.SELECTOR_MODEL,
                                          value='FT-60'),
            fields={'preferred_group': 'does-not-exist'}),)
        issues = validation.validate_profile(p)
        self.assertTrue(any('preferred_group' in i.path for i in issues))


class OverrideSafetyFieldTest(unittest.TestCase):
    def test_override_cannot_carry_disallowed_field(self):
        p = _valid_profile()
        p.channels[0].overrides = (model.TargetOverride(
            selector=model.TargetSelector(scope=schema.SELECTOR_MODEL,
                                          value='FT-60'),
            fields={'transmit_mode': schema.TRANSMIT_ENABLED}),)
        issues = validation.validate_profile(p)
        self.assertTrue(any('disallowed field' in i.message
                            for i in issues))


class SchemaVersionTest(unittest.TestCase):
    def test_unknown_major_version_rejected(self):
        data = _valid_profile().to_dict()
        data['schema_version'] = '2.0'
        with self.assertRaises(errors.ProfileSchemaVersionError):
            validation.check_schema_version(data)

    def test_malformed_version_rejected(self):
        data = _valid_profile().to_dict()
        data['schema_version'] = 'not-a-version'
        with self.assertRaises(errors.ProfileSchemaVersionError):
            validation.check_schema_version(data)

    def test_missing_version_rejected(self):
        data = _valid_profile().to_dict()
        del data['schema_version']
        with self.assertRaises(errors.ProfileSchemaVersionError):
            validation.check_schema_version(data)

    def test_compatible_minor_version_accepted(self):
        data = _valid_profile().to_dict()
        data['schema_version'] = '1.99'
        validation.check_schema_version(data)  # does not raise


class RequiredFieldTest(unittest.TestCase):
    def test_missing_required_field_reported(self):
        data = _valid_profile().to_dict()
        del data['profile_id']
        issues = validation.check_required_root_fields(data)
        self.assertTrue(any(i.path == 'profile_id' for i in issues))
