import unittest
from unittest import mock

from chirp.assistant import models
from chirp.assistant import sources


class StaticSourceTest(unittest.TestCase):
    def test_weather_has_seven_channels(self):
        req = models.ProgrammingRequest()
        candidates = sources.static_weather_candidates(req)
        self.assertEqual(7, len(candidates))
        for c in candidates:
            self.assertEqual(models.SERVICE_WEATHER, c.service)
            self.assertTrue(c.provenance.source_name)

    def test_weather_deterministic(self):
        req = models.ProgrammingRequest()
        a = sources.static_weather_candidates(req)
        b = sources.static_weather_candidates(req)
        self.assertEqual([c.freq for c in a], [c.freq for c in b])

    def test_aviation_is_guard_emergency_only(self):
        req = models.ProgrammingRequest()
        candidates = sources.static_aviation_candidates(req)
        self.assertEqual(2, len(candidates))
        freqs = {c.freq for c in candidates}
        self.assertEqual({121500000, 243000000}, freqs)
        for c in candidates:
            self.assertEqual(models.SERVICE_AVIATION, c.service)
            self.assertTrue(c.reason)  # explains the airport-DB limitation

    def test_calling_frequencies_are_ham_service(self):
        req = models.ProgrammingRequest()
        candidates = sources.static_calling_candidates(req)
        self.assertGreater(len(candidates), 0)
        for c in candidates:
            self.assertEqual(models.SERVICE_HAM, c.service)
            self.assertEqual(models.CONFIDENCE_MEDIUM, c.confidence)

    def test_no_source_ever_produces_ai_provenance(self):
        req = models.ProgrammingRequest()
        for fn in (sources.static_weather_candidates,
                   sources.static_aviation_candidates,
                   sources.static_calling_candidates):
            for c in fn(req):
                self.assertEqual((), c.provenance.fields_from_ai)


class BuildCandidatesDispatchTest(unittest.TestCase):
    def test_unsupported_services_produce_warning_not_data(self):
        req = models.ProgrammingRequest(
            requested_services=(models.SERVICE_MARINE,
                                models.SERVICE_PUBLIC_SAFETY))
        candidates, warnings, skipped = sources.build_candidates(
            req, network_allowed=False)
        self.assertEqual([], candidates)
        self.assertEqual(2, len(warnings))
        self.assertIn('Marine', skipped)
        self.assertIn('Public safety', skipped)

    def test_weather_and_aviation_available_offline(self):
        req = models.ProgrammingRequest(
            requested_services=(models.SERVICE_WEATHER,
                                models.SERVICE_AVIATION))
        candidates, warnings, skipped = sources.build_candidates(
            req, network_allowed=False)
        self.assertEqual(9, len(candidates))  # 7 weather + 2 aviation
        self.assertEqual([], skipped)

    def test_remote_disabled_still_gives_calling_freqs_for_ham(self):
        req = models.ProgrammingRequest(requested_services=(
            models.SERVICE_HAM,))
        candidates, warnings, skipped = sources.build_candidates(
            req, network_allowed=False)
        self.assertGreater(len(candidates), 0)
        self.assertTrue(any('Network sources disabled' in w.message
                            for w in warnings))

    def test_gmrs_skipped_when_remote_queries_disallowed(self):
        req = models.ProgrammingRequest(requested_services=(
            models.SERVICE_GMRS,))
        candidates, warnings, skipped = sources.build_candidates(
            req, network_allowed=False)
        self.assertEqual([], candidates)
        self.assertIn('RepeaterBook (GMRS)', skipped)

    def test_repeaterbook_failure_produces_warning_not_crash(self):
        req = models.ProgrammingRequest(
            requested_services=(models.SERVICE_HAM,),
            location_text='Nonexistent Place')
        with mock.patch.object(
                sources, 'fetch_repeaterbook',
                return_value=([], 'simulated failure')):
            candidates, warnings, skipped = sources.build_candidates(
                req, network_allowed=True)
        self.assertTrue(any('unavailable' in w.message for w in warnings))
        self.assertIn('RepeaterBook (amateur)', skipped)
        # Static calling frequencies still get included even though the
        # network source failed.
        self.assertGreater(len(candidates), 0)

    def test_satellite_failure_produces_warning_not_crash(self):
        req = models.ProgrammingRequest(
            requested_services=(models.SERVICE_SATELLITE,))
        with mock.patch.object(
                sources, 'fetch_satellites',
                return_value=([], 'simulated failure')):
            candidates, warnings, skipped = sources.build_candidates(
                req, network_allowed=True)
        self.assertEqual([], candidates)
        self.assertIn('Radio Amateur Satellites', skipped)

    def test_no_remote_call_when_remote_queries_disallowed(self):
        req = models.ProgrammingRequest(
            requested_services=(models.SERVICE_HAM, models.SERVICE_GMRS,
                                models.SERVICE_SATELLITE))
        with mock.patch.object(sources, 'fetch_repeaterbook') as fetch_rb, \
                mock.patch.object(sources, 'fetch_satellites') as fetch_sat:
            sources.build_candidates(req, network_allowed=False)
        fetch_rb.assert_not_called()
        fetch_sat.assert_not_called()


class ResolveStateTest(unittest.TestCase):
    def test_exact_state_name_resolved(self):
        self.assertEqual('Idaho', sources._resolve_us_state('Idaho'))

    def test_case_insensitive(self):
        self.assertEqual('Idaho', sources._resolve_us_state('idaho'))

    def test_city_name_not_resolved(self):
        self.assertIsNone(sources._resolve_us_state("Coeur d'Alene"))

    def test_empty_not_resolved(self):
        self.assertIsNone(sources._resolve_us_state(''))
        self.assertIsNone(sources._resolve_us_state(None))


if __name__ == '__main__':
    unittest.main()
