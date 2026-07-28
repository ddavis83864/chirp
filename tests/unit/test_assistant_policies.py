import unittest

from chirp.assistant import capability
from chirp.assistant import models
from chirp.assistant import policies
from chirp import chirp_common


def _cap(bands=((144000000, 148000000), (420000000, 450000000)),
         duplexes=('', '-', '+')):
    class FakeRadio:
        def get_features(self):
            rf = chirp_common.RadioFeatures()
            rf.valid_bands = list(bands)
            rf.valid_duplexes = list(duplexes)
            return rf
    return capability.snapshot(FakeRadio())


class TransmitEligibilityTest(unittest.TestCase):
    def test_technician_ham_repeater_transmit_enabled(self):
        req = models.ProgrammingRequest(amateur_license='technician')
        auth = policies.resolve_transmit_eligibility(
            models.SERVICE_HAM, 146850000, 146250000, req, _cap())
        self.assertTrue(auth.transmit_enabled)

    def test_no_license_ham_not_transmit_enabled(self):
        req = models.ProgrammingRequest(amateur_license=models.LICENSE_NONE)
        auth = policies.resolve_transmit_eligibility(
            models.SERVICE_HAM, 146850000, 146250000, req, _cap())
        self.assertFalse(auth.transmit_enabled)
        self.assertFalse(auth.user_declares_authorization)

    def test_gmrs_without_declared_license_not_enabled(self):
        req = models.ProgrammingRequest(has_gmrs_license=False)
        auth = policies.resolve_transmit_eligibility(
            models.SERVICE_GMRS, 462562500, None, req,
            _cap(bands=((462000000, 468000000),)))
        self.assertFalse(auth.transmit_enabled)

    def test_gmrs_with_declared_license_enabled(self):
        req = models.ProgrammingRequest(has_gmrs_license=True)
        auth = policies.resolve_transmit_eligibility(
            models.SERVICE_GMRS, 462562500, None, req,
            _cap(bands=((462000000, 468000000),)))
        self.assertTrue(auth.transmit_enabled)

    def test_frs_never_transmit_enabled_even_with_gmrs_license(self):
        req = models.ProgrammingRequest(has_gmrs_license=True)
        auth = policies.resolve_transmit_eligibility(
            models.SERVICE_FRS, 462562500, None, req,
            _cap(bands=((462000000, 468000000),)))
        self.assertFalse(auth.transmit_enabled)
        self.assertFalse(auth.service_policy_allows_transmit)

    def test_aviation_always_receive_only(self):
        req = models.ProgrammingRequest(amateur_license='extra',
                                        has_gmrs_license=True)
        auth = policies.resolve_transmit_eligibility(
            models.SERVICE_AVIATION, 121500000, None, req,
            _cap(bands=((118000000, 137000000),)))
        self.assertFalse(auth.transmit_enabled)
        self.assertFalse(auth.service_policy_allows_transmit)

    def test_weather_always_receive_only(self):
        req = models.ProgrammingRequest(amateur_license='extra')
        auth = policies.resolve_transmit_eligibility(
            models.SERVICE_WEATHER, 162400000, None, req,
            _cap(bands=((162000000, 163000000),)))
        self.assertFalse(auth.transmit_enabled)

    def test_public_safety_always_receive_only_no_bypass(self):
        # No amount of license/declaration should enable this.
        req = models.ProgrammingRequest(
            amateur_license='extra', has_gmrs_license=True,
            receive_only_services=())
        auth = policies.resolve_transmit_eligibility(
            models.SERVICE_PUBLIC_SAFETY, 154265000, None, req,
            _cap(bands=((150000000, 160000000),)))
        self.assertFalse(auth.transmit_enabled)

    def test_marine_always_receive_only(self):
        req = models.ProgrammingRequest(amateur_license='extra')
        auth = policies.resolve_transmit_eligibility(
            models.SERVICE_MARINE, 156800000, None, req,
            _cap(bands=((156000000, 163000000),)))
        self.assertFalse(auth.transmit_enabled)

    def test_business_always_receive_only(self):
        req = models.ProgrammingRequest()
        auth = policies.resolve_transmit_eligibility(
            models.SERVICE_BUSINESS, 464500000, None, req,
            _cap(bands=((450000000, 470000000),)))
        self.assertFalse(auth.transmit_enabled)

    def test_railroad_always_receive_only(self):
        req = models.ProgrammingRequest()
        auth = policies.resolve_transmit_eligibility(
            models.SERVICE_RAILROAD, 160800000, None, req,
            _cap(bands=((160000000, 162000000),)))
        self.assertFalse(auth.transmit_enabled)

    def test_murs_no_license_needed(self):
        req = models.ProgrammingRequest()
        auth = policies.resolve_transmit_eligibility(
            models.SERVICE_MURS, 151820000, None, req,
            _cap(bands=((151000000, 155000000),)))
        self.assertTrue(auth.transmit_enabled)

    def test_satellite_requires_amateur_license(self):
        req = models.ProgrammingRequest(amateur_license=models.LICENSE_NONE)
        auth = policies.resolve_transmit_eligibility(
            models.SERVICE_SATELLITE, 145900000, 435300000, req,
            _cap(bands=((144000000, 148000000), (435000000, 438000000))))
        self.assertFalse(auth.transmit_enabled)

        req.amateur_license = 'general'
        auth = policies.resolve_transmit_eligibility(
            models.SERVICE_SATELLITE, 145900000, 435300000, req,
            _cap(bands=((144000000, 148000000), (435000000, 438000000))))
        self.assertTrue(auth.transmit_enabled)

    def test_radio_cannot_technically_transmit_out_of_band(self):
        req = models.ProgrammingRequest(amateur_license='extra')
        auth = policies.resolve_transmit_eligibility(
            models.SERVICE_HAM, 146850000, 900000000, req,
            _cap(bands=((144000000, 148000000),)))
        self.assertFalse(auth.radio_can_transmit)
        self.assertFalse(auth.transmit_enabled)

    def test_no_generic_emergency_bypass(self):
        # There's no field or code path that lets any always-receive-only
        # service become transmit-enabled -- confirm this holds for every
        # one of them regardless of how "authorized" the request looks.
        req = models.ProgrammingRequest(
            amateur_license='extra', has_gmrs_license=True,
            activities=('emergency prep',))
        for service in models.ALWAYS_RECEIVE_ONLY_SERVICES:
            auth = policies.resolve_transmit_eligibility(
                service, 150000000, None, req,
                _cap(bands=((100000000, 200000000),),
                     duplexes=('', '-', '+', 'off')))
            self.assertFalse(
                auth.transmit_enabled,
                '%s should never be transmit-enabled' % service)

    def test_destination_supports_rx_only_reported(self):
        req = models.ProgrammingRequest()
        cap_with = _cap(duplexes=('', '-', '+', 'off'))
        cap_without = _cap(duplexes=('', '-', '+'))
        auth_with = policies.resolve_transmit_eligibility(
            models.SERVICE_WEATHER, 162400000, None, req, cap_with)
        auth_without = policies.resolve_transmit_eligibility(
            models.SERVICE_WEATHER, 162400000, None, req, cap_without)
        self.assertTrue(auth_with.destination_supports_rx_only)
        self.assertFalse(auth_without.destination_supports_rx_only)


if __name__ == '__main__':
    unittest.main()
