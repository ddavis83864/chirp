import unittest

from chirp.profiles import model
from chirp.profiles import schema


class ProfileIdentityTest(unittest.TestCase):
    def test_new_profile_gets_stable_uuid(self):
        p1 = model.Profile()
        p2 = model.Profile()
        self.assertTrue(p1.profile_id)
        self.assertNotEqual(p1.profile_id, p2.profile_id)

    def test_rename_does_not_change_profile_id(self):
        p = model.Profile(name='Original Name')
        original_id = p.profile_id
        original_created = p.created_at
        p.rename('New Name')
        self.assertEqual('New Name', p.name)
        self.assertEqual(original_id, p.profile_id)
        self.assertEqual(original_created, p.created_at)

    def test_rename_updates_modified_at(self):
        p = model.Profile(name='A')
        before = p.modified_at
        p.modified_at = '2020-01-01T00:00:00+00:00'
        p.rename('B')
        self.assertNotEqual('2020-01-01T00:00:00+00:00', p.modified_at)
        self.assertIsNotNone(before)

    def test_round_trip_preserves_profile_id(self):
        p = model.Profile(name='Round Trip')
        data = p.to_dict()
        p2 = model.Profile.from_dict(data)
        self.assertEqual(p.profile_id, p2.profile_id)
        self.assertEqual(p.created_at, p2.created_at)
        self.assertEqual(p.modified_at, p2.modified_at)

    def test_missing_profile_id_generates_new_one(self):
        # Used only by from_dict() called directly with partial data;
        # serialization.from_dict() enforces profile_id is present in a
        # loaded document before ever reaching here.
        data = model.Profile(name='X').to_dict()
        del data['profile_id']
        p = model.Profile.from_dict(data)
        self.assertTrue(p.profile_id)


class ChannelIdentityTest(unittest.TestCase):
    def test_logical_id_stable_across_memory_reassignment(self):
        # The model has no memory-number field on ProfileChannel at all
        # -- placement decides a target memory number later, entirely
        # outside the canonical channel identity.
        ch = model.ProfileChannel(logical_id='local-cda-2m-repeater-01',
                                  name='CDA Repeater')
        self.assertFalse(hasattr(ch, 'number'))
        self.assertEqual('local-cda-2m-repeater-01', ch.logical_id)

    def test_valid_logical_ids(self):
        values = ('local-cda-2m-repeater-01', 'national-2m-simplex',
                  'noaa-weather-01', 'a', 'a1-b2-c3')
        for value in values:
            self.assertTrue(schema.is_valid_logical_id(value), value)

    def test_invalid_logical_ids(self):
        values = ('', 'Has-Upper', 'has_underscore', 'trailing-',
                  '-leading', 'double--hyphen', 'has space', None, 123)
        for value in values:
            self.assertFalse(schema.is_valid_logical_id(value), value)

    def test_get_channel_by_logical_id(self):
        p = model.Profile()
        ch = model.ProfileChannel(logical_id='noaa-weather-01', name='WX1')
        p.add_channel(ch)
        self.assertIs(ch, p.get_channel('noaa-weather-01'))
        self.assertIsNone(p.get_channel('does-not-exist'))

    def test_remove_channel(self):
        p = model.Profile()
        p.add_channel(model.ProfileChannel(logical_id='a-1'))
        p.add_channel(model.ProfileChannel(logical_id='a-2'))
        p.remove_channel('a-1')
        self.assertIsNone(p.get_channel('a-1'))
        self.assertIsNotNone(p.get_channel('a-2'))


class TransmitBehaviorTest(unittest.TestCase):
    def test_receive_only_property(self):
        rx_only = model.TransmitBehavior(mode=schema.TRANSMIT_RECEIVE_ONLY)
        enabled = model.TransmitBehavior(mode=schema.TRANSMIT_ENABLED)
        self.assertTrue(rx_only.receive_only)
        self.assertFalse(enabled.receive_only)

    def test_channel_receive_only_delegates_to_transmit(self):
        ch = model.ProfileChannel(
            logical_id='aviation-emergency-guard',
            transmit=model.TransmitBehavior(
                mode=schema.TRANSMIT_RECEIVE_ONLY))
        self.assertTrue(ch.receive_only)

    def test_round_trip_preserves_transmit_mode(self):
        ch = model.ProfileChannel(
            logical_id='noaa-weather-01',
            transmit=model.TransmitBehavior(
                mode=schema.TRANSMIT_RECEIVE_ONLY))
        data = ch.to_dict()
        ch2 = model.ProfileChannel.from_dict(data)
        self.assertTrue(ch2.receive_only)
        self.assertEqual(schema.TRANSMIT_RECEIVE_ONLY, ch2.transmit.mode)


class FrequencySerializationTest(unittest.TestCase):
    def test_frequency_is_integer_hz(self):
        ch = model.ProfileChannel(logical_id='x-1', rx_freq_hz=146520000)
        data = ch.to_dict()
        self.assertIsInstance(data['rx_freq_hz'], int)
        self.assertEqual(146520000, data['rx_freq_hz'])

    def test_split_tx_frequency_round_trips(self):
        ch = model.ProfileChannel(
            logical_id='x-2', rx_freq_hz=146520000,
            transmit=model.TransmitBehavior(
                mode=schema.TRANSMIT_ENABLED, duplex=schema.DUPLEX_SPLIT,
                tx_freq_hz=146920000))
        ch2 = model.ProfileChannel.from_dict(ch.to_dict())
        self.assertEqual(146920000, ch2.transmit.tx_freq_hz)


class DefaultsAndOverridesTest(unittest.TestCase):
    def test_channel_inherits_profile_default_mode(self):
        p = model.Profile(defaults=model.ProfileDefaults(mode='FM'))
        ch = model.ProfileChannel(logical_id='x-1')  # mode=None -> inherit
        resolved = model.resolve_channel(p, ch)
        self.assertEqual('FM', resolved.mode)

    def test_channel_overrides_profile_default_mode(self):
        p = model.Profile(defaults=model.ProfileDefaults(mode='FM'))
        ch = model.ProfileChannel(logical_id='x-1', mode='NFM')
        resolved = model.resolve_channel(p, ch)
        self.assertEqual('NFM', resolved.mode)

    def test_channel_inherits_default_power_preference(self):
        p = model.Profile(defaults=model.ProfileDefaults(
            power_preference=model.PowerPreference(tier='high')))
        ch = model.ProfileChannel(logical_id='x-1')
        resolved = model.resolve_channel(p, ch)
        self.assertEqual('high', resolved.power_preference.tier)

    def test_channel_own_power_preference_wins(self):
        p = model.Profile(defaults=model.ProfileDefaults(
            power_preference=model.PowerPreference(tier='high')))
        ch = model.ProfileChannel(
            logical_id='x-1',
            power_preference=model.PowerPreference(tier='low'))
        resolved = model.resolve_channel(p, ch)
        self.assertEqual('low', resolved.power_preference.tier)

    def test_target_override_field_whitelist(self):
        override = model.TargetOverride(
            selector=model.TargetSelector(
                scope=schema.SELECTOR_MODEL, value='FT-60'),
            fields={'name': 'CDA RPTR'})
        self.assertIn('name', schema.ALLOWED_OVERRIDE_FIELDS)
        self.assertEqual('CDA RPTR', override.fields['name'])

    def test_override_round_trip(self):
        ch = model.ProfileChannel(
            logical_id='x-1',
            overrides=(model.TargetOverride(
                selector=model.TargetSelector(scope=schema.SELECTOR_MODEL,
                                              value='FT-60'),
                fields={'name': 'CDA RPTR'}),))
        ch2 = model.ProfileChannel.from_dict(ch.to_dict())
        self.assertEqual(1, len(ch2.overrides))
        self.assertEqual('FT-60', ch2.overrides[0].selector.value)
        self.assertEqual('CDA RPTR', ch2.overrides[0].fields['name'])


class GroupMembershipTest(unittest.TestCase):
    def test_channel_can_belong_to_multiple_groups(self):
        ch = model.ProfileChannel(
            logical_id='x-1', groups=('local-repeaters', 'emergency'))
        ch2 = model.ProfileChannel.from_dict(ch.to_dict())
        self.assertEqual(('local-repeaters', 'emergency'), ch2.groups)

    def test_groups_survive_profile_round_trip(self):
        p = model.Profile()
        p.groups['local-repeaters'] = model.LogicalGroup(
            id='local-repeaters', name='Local Repeaters')
        p2 = model.Profile.from_dict(p.to_dict())
        self.assertIn('local-repeaters', p2.groups)
        self.assertEqual('Local Repeaters', p2.groups['local-repeaters'].name)
