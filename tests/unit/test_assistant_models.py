import dataclasses
import unittest

from chirp.assistant import models


class ProgrammingRequestValidationTest(unittest.TestCase):
    def test_valid_request(self):
        req = models.ProgrammingRequest(
            amateur_license='technician', has_gmrs_license=True,
            requested_services=('ham', 'gmrs'), radius_miles=25,
            channel_limit=40)
        self.assertEqual([], req.validate())
        self.assertTrue(req.is_valid)

    def test_invalid_license_class(self):
        req = models.ProgrammingRequest(amateur_license='super-extra')
        errors = req.validate()
        self.assertTrue(any('license' in e for e in errors))
        self.assertFalse(req.is_valid)

    def test_invalid_service(self):
        req = models.ProgrammingRequest(requested_services=('cb_radio',))
        errors = req.validate()
        self.assertTrue(any('service' in e for e in errors))

    def test_invalid_receive_only_service(self):
        req = models.ProgrammingRequest(receive_only_services=('nonsense',))
        errors = req.validate()
        self.assertTrue(any('receive-only service' in e for e in errors))

    def test_excessive_radius(self):
        req = models.ProgrammingRequest(
            radius_miles=models.MAX_RADIUS_MILES + 1)
        errors = req.validate()
        self.assertTrue(any('radius_miles' in e for e in errors))

    def test_zero_radius_rejected(self):
        req = models.ProgrammingRequest(radius_miles=0)
        self.assertTrue(req.validate())

    def test_excessive_channel_count(self):
        req = models.ProgrammingRequest(
            channel_limit=models.MAX_CHANNEL_LIMIT + 1)
        errors = req.validate()
        self.assertTrue(any('channel_limit' in e for e in errors))

    def test_channel_limit_not_int(self):
        req = models.ProgrammingRequest(channel_limit=40.5)
        errors = req.validate()
        self.assertTrue(any('channel_limit' in e for e in errors))

    def test_invalid_naming_style(self):
        req = models.ProgrammingRequest(naming_style='fancy')
        errors = req.validate()
        self.assertTrue(any('naming_style' in e for e in errors))

    def test_bad_latitude_longitude(self):
        req = models.ProgrammingRequest(latitude=200, longitude=-200)
        errors = req.validate()
        self.assertEqual(2, len(errors))

    def test_bad_protected_range(self):
        req = models.ProgrammingRequest(protected_memory_ranges=((10, 5),))
        errors = req.validate()
        self.assertTrue(any('protected range' in e for e in errors))

    def test_start_after_end(self):
        req = models.ProgrammingRequest(
            requested_start_memory=50, requested_end_memory=10)
        errors = req.validate()
        self.assertTrue(any('after' in e for e in errors))


class ProgrammingRequestFromDictTest(unittest.TestCase):
    def test_missing_required_values_use_defaults(self):
        req = models.ProgrammingRequest.from_dict({})
        self.assertEqual([], req.validate())
        self.assertEqual(models.LICENSE_NONE, req.amateur_license)

    def test_unknown_ai_output_fields_ignored(self):
        req = models.ProgrammingRequest.from_dict({
            'location_text': 'Boise',
            'freq': 146520000,           # not a real field -- must be
            'repeater_offset': 600000,   # dropped, not silently accepted
            'evil': '__import__("os").system("true")',
        })
        self.assertEqual('Boise', req.location_text)
        self.assertFalse(hasattr(req, 'freq'))
        self.assertFalse(hasattr(req, 'repeater_offset'))
        self.assertFalse(hasattr(req, 'evil'))

    def test_malformed_type_ignored_not_crashed(self):
        req = models.ProgrammingRequest.from_dict({
            'radius_miles': 'a lot',
            'channel_limit': 'forty',
            'has_gmrs_license': 'yes',  # not a real bool
        })
        # Falls back to defaults for each malformed field rather than
        # raising or accepting the wrong type.
        self.assertEqual(25.0, req.radius_miles)
        self.assertEqual(40, req.channel_limit)
        self.assertFalse(req.has_gmrs_license)

    def test_non_dict_input(self):
        req = models.ProgrammingRequest.from_dict('not a dict')
        self.assertEqual([], req.validate())

    def test_no_reorder_field_exists(self):
        # allow_reordering was removed during remediation review: it
        # was accepted from AI/dict input and stored, but nothing in
        # chirp.assistant.planner ever read it, so setting it had zero
        # effect -- an inoperative control. Guard against silently
        # reintroducing another one of these without wiring it up.
        field_names = {f.name for f in
                       dataclasses.fields(models.ProgrammingRequest)}
        self.assertFalse(
            any('reorder' in name for name in field_names),
            'a reorder-related field exists on ProgrammingRequest but '
            'nothing in planner.py implements reordering -- either wire '
            'it up or remove it, do not leave an inoperative control')

    def test_round_trip(self):
        req = models.ProgrammingRequest(
            location_text='Coeur d\'Alene', amateur_license='general',
            has_gmrs_license=True, requested_services=('ham', 'gmrs'),
            protected_memory_ranges=((0, 9),))
        req2 = models.ProgrammingRequest.from_dict(req.to_dict())
        self.assertEqual(req.location_text, req2.location_text)
        self.assertEqual(req.requested_services, req2.requested_services)
        self.assertEqual(req.protected_memory_ranges,
                         req2.protected_memory_ranges)


class ChannelCandidateTest(unittest.TestCase):
    def test_dedup_key_distinguishes_service(self):
        a = models.ChannelCandidate(
            source='s', service=models.SERVICE_HAM, group='g', label='A',
            freq=462562500, mode='FM')
        b = models.ChannelCandidate(
            source='s', service=models.SERVICE_GMRS, group='g', label='B',
            freq=462562500, mode='FM')
        self.assertNotEqual(a.dedup_key(), b.dedup_key())

    def test_dedup_key_same_for_equivalent_channel(self):
        a = models.ChannelCandidate(
            source='s1', service=models.SERVICE_HAM, group='g', label='A',
            freq=146850000, tx_freq=146250000, mode='FM', tmode='Tone',
            rtone=100.0)
        b = models.ChannelCandidate(
            source='s2', service=models.SERVICE_HAM, group='g', label='B',
            freq=146850000, tx_freq=146250000, mode='FM', tmode='Tone',
            rtone=100.0)
        self.assertEqual(a.dedup_key(), b.dedup_key())


class ChannelPlanTest(unittest.TestCase):
    def test_counts_only_includes_included(self):
        included = models.ChannelCandidate(
            source='s', service='ham', group='g', label='A', freq=1,
            status=models.STATUS_READY, include=True)
        excluded = models.ChannelCandidate(
            source='s', service='ham', group='g', label='B', freq=2,
            status=models.STATUS_DUPLICATE, include=False)
        plan = models.ChannelPlan(groups=[
            models.PlanGroup(name='g', candidates=[included, excluded])])
        counts = plan.counts()
        self.assertEqual({models.STATUS_READY: 1}, counts)

    def test_all_candidates_flattens_groups(self):
        c1 = models.ChannelCandidate(source='s', service='ham', group='g',
                                     label='A', freq=1)
        c2 = models.ChannelCandidate(source='s', service='ham', group='g',
                                     label='B', freq=2)
        plan = models.ChannelPlan(groups=[
            models.PlanGroup(name='g1', candidates=[c1]),
            models.PlanGroup(name='g2', candidates=[c2])])
        self.assertEqual([c1, c2], plan.all_candidates)


class ServiceAuthorizationTest(unittest.TestCase):
    def test_transmit_enabled_requires_all_three(self):
        auth = models.ServiceAuthorization(
            service='ham', radio_can_receive=True, radio_can_transmit=True,
            user_declares_authorization=True,
            service_policy_allows_transmit=True,
            destination_supports_rx_only=True)
        self.assertTrue(auth.transmit_enabled)

        auth.user_declares_authorization = False
        self.assertFalse(auth.transmit_enabled)


if __name__ == '__main__':
    unittest.main()
