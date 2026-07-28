import unittest

from chirp import chirp_common
from chirp.profiles import capabilities
from chirp.profiles import changeset
from chirp.profiles import errors
from chirp.profiles import model
from chirp.profiles import schema
from tests.unit import fake_radios


def _profile(*channels):
    p = model.Profile(name='Test Profile',
                      defaults=model.ProfileDefaults(mode='FM'))
    for ch in channels:
        p.add_channel(ch)
    return p


def _repeater(logical_id='local-cda-2m-repeater-01', freq=146520000):
    return model.ProfileChannel(
        logical_id=logical_id, name='CDA RPTR', rx_freq_hz=freq,
        transmit=model.TransmitBehavior(
            mode=schema.TRANSMIT_ENABLED, duplex=schema.DUPLEX_POSITIVE,
            offset_hz=600000))


def _rx_only(logical_id='noaa-weather-01', freq=162550000):
    return model.ProfileChannel(
        logical_id=logical_id, name='NOAA1', rx_freq_hz=freq,
        transmit=model.TransmitBehavior(mode=schema.TRANSMIT_RECEIVE_ONLY))


def _mem(number, empty=True):
    m = chirp_common.Memory()
    m.number = number
    m.empty = empty
    return m


class AddNewChannelTest(unittest.TestCase):
    def test_new_channel_on_empty_image_is_add(self):
        caps = capabilities.for_radio(fake_radios.feature_rich_radio())
        profile = _profile(_repeater())
        cs = changeset.build_changeset(profile, caps, [])
        item = cs.get('local-cda-2m-repeater-01')
        self.assertEqual(schema.ACTION_ADD, item.action)
        self.assertEqual(schema.CLASS_EXACT, item.classification)
        self.assertIsNotNone(item.target_memory_number)
        self.assertEqual(schema.APPROVAL_PENDING, item.approval_state)


class KeepAlreadyPresentTest(unittest.TestCase):
    def test_already_present_channel_is_keep(self):
        caps = capabilities.for_radio(fake_radios.feature_rich_radio())
        profile = _profile(_repeater())
        existing = chirp_common.Memory()
        existing.number = 3
        existing.freq = 146520000
        existing.duplex = '+'
        existing.offset = 600000
        existing.name = 'CDA RPTR'  # matches _repeater()'s name exactly
        cs = changeset.build_changeset(profile, caps, [existing])
        item = cs.get('local-cda-2m-repeater-01')
        self.assertEqual(schema.ACTION_KEEP, item.action)
        self.assertEqual(3, item.target_memory_number)
        self.assertEqual(schema.APPROVAL_APPROVED, item.approval_state)


class ModifyExistingTest(unittest.TestCase):
    def test_same_channel_different_name_is_modify(self):
        caps = capabilities.for_radio(fake_radios.feature_rich_radio())
        profile = _profile(_repeater())
        existing = chirp_common.Memory()
        existing.number = 3
        existing.freq = 146520000
        existing.duplex = '+'
        existing.offset = 600000
        existing.name = 'OLD NAME'
        cs = changeset.build_changeset(profile, caps, [existing])
        item = cs.get('local-cda-2m-repeater-01')
        self.assertEqual(schema.ACTION_MODIFY, item.action)
        self.assertEqual(3, item.target_memory_number)


class BlockedUnsafeTest(unittest.TestCase):
    def test_receive_only_channel_blocked_on_radio_that_cannot_enforce_it(
            self):
        caps = capabilities.for_radio(
            fake_radios.cannot_enforce_receive_only_radio())
        profile = _profile(_rx_only(freq=146520000))
        cs = changeset.build_changeset(profile, caps, [])
        item = cs.get('noaa-weather-01')
        self.assertEqual(schema.ACTION_BLOCKED, item.action)
        self.assertTrue(item.blocked)
        self.assertEqual(schema.APPROVAL_BLOCKED, item.approval_state)

    def test_blocked_item_cannot_be_approved(self):
        caps = capabilities.for_radio(
            fake_radios.cannot_enforce_receive_only_radio())
        profile = _profile(_rx_only(freq=146520000))
        cs = changeset.build_changeset(profile, caps, [])
        with self.assertRaises(errors.UnsafeOperationError):
            cs.set_approval('noaa-weather-01', schema.APPROVAL_APPROVED)


class IncompatibleSkipTest(unittest.TestCase):
    def test_out_of_range_channel_is_skip(self):
        caps = capabilities.for_radio(fake_radios.restricted_range_radio())
        profile = _profile(_repeater(freq=999000000))
        cs = changeset.build_changeset(profile, caps, [])
        item = cs.get('local-cda-2m-repeater-01')
        self.assertEqual(schema.ACTION_SKIP, item.action)
        self.assertIsNone(item.target_memory_number)


class ConflictDetectionTest(unittest.TestCase):
    def test_ambiguous_match_surfaces_as_conflict_item(self):
        caps = capabilities.for_radio(fake_radios.feature_rich_radio())
        # tone_mode 'TSQL' matches neither existing memory's tmode below,
        # so neither is a full-signature (near-exact) match -- both only
        # tie at the weaker freq+duplex+offset level, which is genuinely
        # ambiguous.
        channel = _repeater(freq=146520000)
        channel.tone_mode = 'TSQL'
        profile = _profile(channel)
        m1 = chirp_common.Memory()
        m1.number = 1
        m1.freq = 146520000
        m1.duplex = '+'
        m1.offset = 600000
        m2 = chirp_common.Memory()
        m2.number = 2
        m2.freq = 146520000
        m2.duplex = '+'
        m2.offset = 600000
        m2.tmode = 'Tone'
        cs = changeset.build_changeset(profile, caps, [m1, m2])
        item = cs.get('local-cda-2m-repeater-01')
        self.assertEqual(schema.ACTION_CONFLICT, item.action)
        self.assertTrue(item.conflicts)
        self.assertEqual(schema.CONFLICT_AMBIGUOUS_MATCH,
                         item.conflicts[0].conflict_type)

    def test_capacity_exceeded_surfaces_as_conflict(self):
        caps = capabilities.for_radio(fake_radios.short_name_radio())
        hi = caps.memory_bounds[1]
        full = [_mem(n, empty=False) for n in range(hi + 1)]
        for m in full:
            m.freq = 146520000 + m.number  # keep in-band, distinct
        # An in-band but otherwise-unmatched frequency: this must fail
        # on "no room left", not "out of range".
        profile = _profile(_repeater(freq=146520000 + hi + 1))
        cs = changeset.build_changeset(profile, caps, full)
        item = cs.get('local-cda-2m-repeater-01')
        self.assertEqual(schema.ACTION_CONFLICT, item.action)
        self.assertTrue(any(
            c.conflict_type == schema.CONFLICT_CAPACITY_EXCEEDED
            for c in item.conflicts))


class ApprovalWorkflowTest(unittest.TestCase):
    def test_approve_and_collect(self):
        caps = capabilities.for_radio(fake_radios.feature_rich_radio())
        profile = _profile(_repeater())
        cs = changeset.build_changeset(profile, caps, [])
        self.assertEqual([], cs.approved_items())
        cs.set_approval('local-cda-2m-repeater-01', schema.APPROVAL_APPROVED)
        approved = cs.approved_items()
        self.assertEqual(1, len(approved))
        self.assertEqual('local-cda-2m-repeater-01', approved[0].logical_id)

    def test_reject_excludes_from_approved(self):
        caps = capabilities.for_radio(fake_radios.feature_rich_radio())
        profile = _profile(_repeater())
        cs = changeset.build_changeset(profile, caps, [])
        cs.set_approval('local-cda-2m-repeater-01', schema.APPROVAL_REJECTED)
        self.assertEqual([], cs.approved_items())

    def test_unknown_logical_id_raises(self):
        caps = capabilities.for_radio(fake_radios.feature_rich_radio())
        profile = _profile(_repeater())
        cs = changeset.build_changeset(profile, caps, [])
        with self.assertRaises(KeyError):
            cs.set_approval('does-not-exist', schema.APPROVAL_APPROVED)


class DeterminismTest(unittest.TestCase):
    def test_same_inputs_produce_identical_changeset(self):
        caps = capabilities.for_radio(fake_radios.feature_rich_radio())
        profile = _profile(_repeater(), _rx_only())
        existing = [_mem(0)]
        cs1 = changeset.build_changeset(profile, caps, existing)
        cs2 = changeset.build_changeset(profile, caps, existing)
        summary1 = [
            (i.logical_id, i.action, i.target_memory_number)
            for i in cs1.items]
        summary2 = [
            (i.logical_id, i.action, i.target_memory_number)
            for i in cs2.items]
        self.assertEqual(summary1, summary2)


class DoesNotMutateInputTest(unittest.TestCase):
    def test_existing_memories_list_is_untouched(self):
        caps = capabilities.for_radio(fake_radios.feature_rich_radio())
        profile = _profile(_repeater())
        existing = [_mem(0)]
        before = existing[0].freq
        changeset.build_changeset(profile, caps, existing)
        self.assertEqual(before, existing[0].freq)
