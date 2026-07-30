import unittest
from unittest import mock

import requests

from chirp import chirp_common
from chirp.assistant import models
from chirp.assistant import sources
from chirp.sources import repeaterbook


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


class DescribeFetchFailureTest(unittest.TestCase):
    """A timeout, a connection failure, an HTTP error, and anything
    else must read as distinguishable reasons, not one generic
    str(exception) -- see remediation review of source/failure
    messaging."""

    def test_timeout_is_distinguished(self):
        msg = sources._describe_fetch_failure(
            requests.exceptions.Timeout('slow'))
        self.assertIn('timed out', msg)

    def test_connection_error_is_distinguished(self):
        msg = sources._describe_fetch_failure(
            requests.exceptions.ConnectionError('dns fail'))
        self.assertIn('offline', msg)

    def test_http_error_is_distinguished(self):
        msg = sources._describe_fetch_failure(
            requests.exceptions.HTTPError('503 Server Error'))
        self.assertIn('server returned an error', msg)

    def test_other_exception_falls_back_to_message(self):
        msg = sources._describe_fetch_failure(ValueError('weird state'))
        self.assertEqual('weird state', msg)


class FetchFailureCategorizationTest(unittest.TestCase):
    """fetch_repeaterbook/fetch_satellites must surface a categorized
    reason (not a raw exception repr) when the underlying adapter
    raises instead of reporting through QueryStatus.send_fail."""

    def test_repeaterbook_timeout_categorized(self):
        req = models.ProgrammingRequest(location_text='Idaho')
        with mock.patch.object(repeaterbook.RepeaterBook, 'do_fetch',
                               side_effect=requests.exceptions.Timeout):
            candidates, err = sources.fetch_repeaterbook(req, '')
        self.assertEqual([], candidates)
        self.assertIn('timed out', err)

    def test_satellite_connection_error_categorized(self):
        with mock.patch(
                'chirp.sources.amsats.RadioAmateurSatellites.do_fetch',
                side_effect=requests.exceptions.ConnectionError):
            candidates, err = sources.fetch_satellites(
                models.ProgrammingRequest())
        self.assertEqual([], candidates)
        self.assertIn('offline', err)


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

    def test_two_letter_abbreviation_resolved(self):
        self.assertEqual('Idaho', sources._resolve_us_state('ID'))

    def test_abbreviation_is_case_insensitive(self):
        self.assertEqual('Idaho', sources._resolve_us_state('id'))

    def test_unknown_two_letter_token_not_resolved(self):
        # Must not accidentally treat an arbitrary two-letter string as
        # a state abbreviation just because it's two characters.
        self.assertIsNone(sources._resolve_us_state('XX'))


class StateHintFromLocationTextTest(unittest.TestCase):
    """Reproduces defect: a request for repeaters "near Coeur d'Alene,
    Idaho" (the exact wording from Windows validation) produced only
    simplex frequencies, never RepeaterBook results. Root cause,
    confirmed by tracing chirp.assistant.sources.fetch_repeaterbook():
    it requires _state_hint(request) to resolve to a bare US state
    name, but the pre-fix _state_hint() only ever tried
    _resolve_us_state() against the ENTIRE location_text verbatim --
    which only succeeds if location_text is nothing but a state name.
    "Coeur d'Alene, Idaho" (a city followed by its state, the normal
    way anyone would actually type a location) never matched, so
    fetch_repeaterbook() always returned zero candidates and an
    unavailable-source warning, while static_calling_candidates()
    (simplex) was added unconditionally regardless -- exactly the
    "only simplex frequencies, no repeaters" symptom reported, and
    identical whether the request came from manual structured-field
    entry or from Interpret with AI (both populate location_text the
    same way; this defect has nothing to do with the AI provider path
    at all).
    """

    def test_bare_state_name_still_resolves(self):
        # The one case the pre-fix implementation already handled --
        # must keep working.
        req = models.ProgrammingRequest(location_text='Idaho')
        self.assertEqual('Idaho', sources._state_hint(req))

    def test_city_comma_state_resolves(self):
        req = models.ProgrammingRequest(
            location_text="Coeur d'Alene, Idaho")
        self.assertEqual('Idaho', sources._state_hint(req))

    def test_city_comma_abbreviation_resolves(self):
        req = models.ProgrammingRequest(location_text="Coeur d'Alene, ID")
        self.assertEqual('Idaho', sources._state_hint(req))

    def test_city_space_state_no_comma_resolves(self):
        req = models.ProgrammingRequest(location_text="Coeur d'Alene Idaho")
        self.assertEqual('Idaho', sources._state_hint(req))

    def test_multi_word_state_name_resolves(self):
        req = models.ProgrammingRequest(
            location_text='Raleigh, North Carolina')
        self.assertEqual('North Carolina', sources._state_hint(req))

    def test_multi_word_state_preferred_over_shorter_false_match(self):
        # A naive single-trailing-word search would try "York" (not a
        # state) before ever trying "New York" -- the real
        # implementation must prefer the longer, correct match.
        req = models.ProgrammingRequest(
            location_text='New York City, New York')
        self.assertEqual('New York', sources._state_hint(req))

    def test_city_alone_with_no_state_at_all_does_not_resolve(self):
        # No state information is present anywhere in the text --
        # correctly unresolvable, not a defect (see Phase 5: this case
        # must produce accurate "location could not be resolved"
        # feedback, not fabricate a guess).
        req = models.ProgrammingRequest(location_text="Coeur d'Alene")
        self.assertIsNone(sources._state_hint(req))

    def test_empty_location_does_not_resolve(self):
        req = models.ProgrammingRequest(location_text='')
        self.assertIsNone(sources._state_hint(req))


class RepeaterRequestReturnsRealRepeatersTest(unittest.TestCase):
    """End-to-end (within sources.py) reproduction of the reported
    defect using the exact wording from Windows validation, proving
    where the repeater records were actually lost -- not assuming it
    was an AI defect. fetch_repeaterbook() itself is mocked (no real
    network access in unit tests), but everything from location text
    to the RepeaterBook call's own @state parameter runs for real.
    """

    def test_state_resolves_and_repeaterbook_is_queried_with_it(self):
        req = models.ProgrammingRequest(
            requested_services=(models.SERVICE_HAM,),
            location_text="Coeur d'Alene, Idaho",
            radius_miles=25)
        repeater = models.ChannelCandidate(
            source='RepeaterBook', service=models.SERVICE_HAM, group='',
            label='W7ABC Coeur d\'Alene', freq=146880000,
            tx_freq=146280000, tmode='Tone', rtone=100.0,
            source_record_id='123')
        with mock.patch.object(
                sources, 'fetch_repeaterbook',
                return_value=([repeater], None)) as fetch_rb:
            candidates, warnings, skipped = sources.build_candidates(
                req, network_allowed=True)

        fetch_rb.assert_called_once()
        called_request = fetch_rb.call_args[0][0]
        self.assertEqual("Coeur d'Alene, Idaho", called_request.location_text)
        self.assertIn(repeater, candidates)
        self.assertEqual([], skipped)

    def test_pre_fix_behavior_reproduced_directly_against_state_resolution(
            self):
        # Isolates the actual defect down to the state-resolution step
        # alone, independent of the fetch_repeaterbook mock above: if
        # _state_hint() cannot find "Idaho" in this exact wording,
        # fetch_repeaterbook() gives up before ever constructing a
        # RepeaterBook query, regardless of what RepeaterBook itself
        # would have returned.
        req = models.ProgrammingRequest(
            location_text="Coeur d'Alene, Idaho")
        hint = sources._state_hint(req)
        self.assertIsNotNone(
            hint,
            '_state_hint() must resolve a state from "City, State" text '
            'for fetch_repeaterbook() to ever query RepeaterBook at all')
        self.assertEqual('Idaho', sources._resolve_us_state(hint))


class BandFilteringTest(unittest.TestCase):
    """chirp.sources.repeaterbook.RepeaterBook.do_fetch() already has
    its own band filter (included_band()); it was simply never given
    real band data before -- fetch_repeaterbook() always passed
    bands=[] (meaning "no restriction"), regardless of what the
    request asked for. requested_bands is optional and defaults to an
    empty tuple, so a request that doesn't specify bands behaves
    exactly as before this change (no filtering) -- this only adds a
    capability, it never narrows existing behavior by default.
    """

    def test_no_bands_requested_means_no_filter(self):
        self.assertEqual([], sources._band_ranges(()))

    def test_known_bands_map_to_ranges(self):
        ranges = sources._band_ranges(
            (models.BAND_2M, models.BAND_70CM))
        self.assertEqual(
            [(144000000, 148000000), (420000000, 450000000)], ranges)

    def test_unknown_band_ignored_not_fabricated(self):
        # An unknown band identifier is dropped, not turned into a
        # made-up frequency range.
        self.assertEqual(
            [(144000000, 148000000)],
            sources._band_ranges((models.BAND_2M, 'not-a-real-band')))

    def test_requested_bands_reaches_the_real_repeaterbook_query(self):
        req = models.ProgrammingRequest(
            location_text='Idaho',
            requested_bands=(models.BAND_2M, models.BAND_70CM))
        with mock.patch.object(
                repeaterbook.RepeaterBook, 'do_fetch') as do_fetch:
            sources.fetch_repeaterbook(req, '')
        params = do_fetch.call_args[0][1]
        self.assertEqual(
            [(144000000, 148000000), (420000000, 450000000)],
            params['bands'])

    def test_no_requested_bands_preserves_unfiltered_default(self):
        req = models.ProgrammingRequest(location_text='Idaho')
        with mock.patch.object(
                repeaterbook.RepeaterBook, 'do_fetch') as do_fetch:
            sources.fetch_repeaterbook(req, '')
        params = do_fetch.call_args[0][1]
        self.assertEqual([], params['bands'])


class ManualAndAIRequestsProduceEquivalentSourceBehaviorTest(
        unittest.TestCase):
    """Phase 4 requirement: manual structured-field use and Interpret
    with AI must produce equivalent planner/source behavior whenever
    their normalized requests are equivalent -- there is no separate
    "AI code path" anywhere in chirp.assistant.sources or planner.py,
    only a single ProgrammingRequest shape both routes populate (see
    chirp.assistant.providers' own trust-boundary docstring), so this
    mainly proves that equivalence is real, not just architecturally
    assumed.
    """

    def test_manually_built_and_from_dict_built_requests_behave_identically(
            self):
        # from_dict() is what providers.py uses to turn a parsed AI
        # JSON response into a ProgrammingRequest -- constructing one
        # that way, with the same field values a user would have typed
        # manually, must drive fetch_repeaterbook identically.
        manual = models.ProgrammingRequest(
            location_text="Coeur d'Alene, Idaho",
            requested_services=(models.SERVICE_HAM,),
            requested_bands=(models.BAND_2M,))
        ai_interpreted = models.ProgrammingRequest.from_dict({
            'location_text': "Coeur d'Alene, Idaho",
            'requested_services': ['ham'],
            'requested_bands': ['2m'],
        })

        self.assertEqual(manual.location_text, ai_interpreted.location_text)
        self.assertEqual(manual.requested_services,
                         ai_interpreted.requested_services)
        self.assertEqual(manual.requested_bands,
                         ai_interpreted.requested_bands)
        self.assertEqual(sources._state_hint(manual),
                         sources._state_hint(ai_interpreted))
        self.assertEqual(
            sources._band_ranges(manual.requested_bands),
            sources._band_ranges(ai_interpreted.requested_bands))


class MemoryToCandidateFieldPreservationTest(unittest.TestCase):
    """A repeater record's technical fields must survive the
    Memory -> ChannelCandidate conversion untouched -- this is the
    "normalization" step between a source query and the planner
    (deduplicate/flag_existing_conflicts/etc., none of which touch
    these fields either -- see planner.py). Location (per-candidate
    coordinates) is a pre-existing, already-documented limitation, not
    tested here: chirp_common.Memory has no field for it at all, since
    RepeaterBook's own item_to_memory() doesn't preserve Lat/Long onto
    the Memory it returns (see memory_to_candidate's own docstring)."""

    def _repeater_memory(self):
        mem = chirp_common.Memory()
        mem.number = 1
        mem.freq = 146880000
        mem.duplex = '-'
        mem.offset = 600000
        mem.mode = 'FM'
        mem.tmode = 'Tone'
        mem.rtone = 100.0
        mem.ctone = 103.5
        mem.name = 'W7ABC'
        mem.comment = 'Coeur d\'Alene repeater'
        return mem

    def test_repeater_fields_survive_conversion(self):
        candidate = sources.memory_to_candidate(
            self._repeater_memory(), 'RepeaterBook', models.SERVICE_HAM,
            source_id='42')

        self.assertEqual(146880000, candidate.freq)
        self.assertEqual(146280000, candidate.tx_freq)  # freq - offset
        self.assertEqual('FM', candidate.mode)
        self.assertEqual('Tone', candidate.tmode)
        self.assertEqual(100.0, candidate.rtone)
        self.assertEqual(103.5, candidate.ctone)
        self.assertEqual('W7ABC', candidate.label)  # call sign / name
        self.assertEqual('RepeaterBook', candidate.source)
        self.assertEqual('42', candidate.source_record_id)
        self.assertEqual(models.SERVICE_HAM, candidate.service)

    def test_attribution_is_present_and_not_from_ai(self):
        candidate = sources.memory_to_candidate(
            self._repeater_memory(), 'RepeaterBook', models.SERVICE_HAM,
            source_id='42')
        self.assertEqual('RepeaterBook', candidate.provenance.source_name)
        self.assertIsNotNone(candidate.provenance.retrieved_at)
        self.assertEqual((), candidate.provenance.fields_from_ai)

    def test_simplex_repeater_distinguished_by_tx_freq(self):
        # A simplex memory (duplex 'off' or '') produces tx_freq=None
        # or tx_freq==freq -- the same signal
        # chirp.assistant.planner.group_name() uses to classify a
        # candidate as "Local Amateur Repeaters" vs "Amateur Simplex".
        simplex = chirp_common.Memory()
        simplex.number = 1
        simplex.freq = 146520000
        simplex.duplex = ''
        candidate = sources.memory_to_candidate(
            simplex, 'RepeaterBook', models.SERVICE_HAM)
        self.assertEqual(candidate.freq, candidate.tx_freq)


class RepeaterResultsNotReplacedBySimplexTest(unittest.TestCase):
    """Repeater results and the static simplex/calling table are
    additive, not either/or -- a successful RepeaterBook query must
    not be discarded or overridden just because static_calling_
    candidates() also always runs for the ham service."""

    def test_repeater_and_simplex_both_present_when_repeaterbook_succeeds(
            self):
        req = models.ProgrammingRequest(
            requested_services=(models.SERVICE_HAM,),
            location_text='Idaho')
        repeater = models.ChannelCandidate(
            source='RepeaterBook', service=models.SERVICE_HAM, group='',
            label='W7ABC', freq=146880000, tx_freq=146280000)
        with mock.patch.object(
                sources, 'fetch_repeaterbook',
                return_value=([repeater], None)):
            candidates, warnings, skipped = sources.build_candidates(
                req, network_allowed=True)

        self.assertIn(repeater, candidates)
        simplex_sources = {c.source for c in candidates
                           if c is not repeater}
        self.assertIn('static_ham_calling', simplex_sources)
        self.assertEqual([], skipped)

    def test_repeaters_and_simplex_are_distinguishable_by_group(self):
        # planner.group_name() (not sources.py) is what actually
        # labels these for display -- confirms the two categories
        # remain distinguishable once grouped, using build_plan's own
        # real grouping logic rather than re-implementing the check.
        from chirp.assistant import planner
        repeater = models.ChannelCandidate(
            source='RepeaterBook', service=models.SERVICE_HAM, group='',
            label='W7ABC', freq=146880000, tx_freq=146280000)
        simplex = models.ChannelCandidate(
            source='static_ham_calling', service=models.SERVICE_HAM,
            group='', label='Calling 146.520', freq=146520000)
        self.assertEqual('Local Amateur Repeaters',
                         planner.group_name(repeater))
        self.assertEqual('Amateur Simplex', planner.group_name(simplex))
        self.assertNotEqual(planner.group_name(repeater),
                            planner.group_name(simplex))


class AccurateFeedbackCategorizationTest(unittest.TestCase):
    """Phase 5: the six required distinguishable feedback categories,
    each with its own message content a user can actually act on."""

    def test_no_source_configured_for_unsupported_service(self):
        req = models.ProgrammingRequest(
            requested_services=(models.SERVICE_MARINE,))
        _candidates, warnings, _skipped = sources.build_candidates(
            req, network_allowed=True)
        self.assertTrue(any(
            'no trusted data source is available' in w.message
            for w in warnings))

    def test_source_unavailable_distinguished_from_location_failure(self):
        req = models.ProgrammingRequest(
            requested_services=(models.SERVICE_HAM,),
            location_text='Idaho')
        with mock.patch.object(
                sources, 'fetch_repeaterbook',
                return_value=([], 'could not connect (network unreachable '
                                  'or offline)')):
            _candidates, warnings, _skipped = sources.build_candidates(
                req, network_allowed=True)
        message = next(w.message for w in warnings if 'unavailable' in
                       w.message)
        self.assertIn('could not connect', message)
        self.assertNotIn('location could not be resolved', message)

    def test_location_could_not_be_resolved_is_its_own_category(self):
        req = models.ProgrammingRequest(
            requested_services=(models.SERVICE_HAM,),
            location_text='Nowhere Really')
        candidates, err = sources.fetch_repeaterbook(req, '')
        self.assertEqual([], candidates)
        self.assertIn('location could not be resolved', err)

    def test_zero_matching_records_is_distinct_from_unavailable(self):
        req = models.ProgrammingRequest(
            requested_services=(models.SERVICE_HAM,),
            location_text='Idaho')
        with mock.patch.object(
                sources, 'fetch_repeaterbook', return_value=([], None)):
            _candidates, warnings, skipped = sources.build_candidates(
                req, network_allowed=True)
        message = next(w.message for w in warnings
                       if 'RepeaterBook (amateur)' in w.message)
        self.assertIn('completed but returned no matching', message)
        # Not "unavailable" -- the query succeeded; distinguishing
        # this from a real failure is the point.
        self.assertNotIn('unavailable', message)
        # And not treated as a failed/skipped source, since it wasn't
        # a failure.
        self.assertEqual([], skipped)

    def test_only_supplemental_simplex_available_is_labeled_as_such(self):
        req = models.ProgrammingRequest(
            requested_services=(models.SERVICE_HAM,), location_text='Idaho')
        with mock.patch.object(
                sources, 'fetch_repeaterbook', return_value=([], None)):
            candidates, warnings, _skipped = sources.build_candidates(
                req, network_allowed=True)
        self.assertTrue(all(c.source == 'static_ham_calling'
                            for c in candidates))
        self.assertTrue(any('no matching' in w.message for w in warnings))


class InvalidSourceRecordsRejectedTest(unittest.TestCase):
    """A malformed record from RepeaterBook (missing/invalid fields)
    must not crash the whole request -- it should be skipped or
    produce a usable fallback value, the same tolerance chirp.sources.
    repeaterbook.RepeaterBook already applies when parsing raw JSON."""

    def test_memory_to_candidate_tolerates_missing_optional_fields(self):
        mem = chirp_common.Memory()
        mem.number = 1
        mem.freq = 146520000
        # No name, no comment, no tone fields explicitly set --
        # exercises the dataclass/Memory defaults, not a crash.
        candidate = sources.memory_to_candidate(
            mem, 'RepeaterBook', models.SERVICE_HAM)
        self.assertEqual(146520000, candidate.freq)
        self.assertTrue(candidate.label)  # falls back to formatted freq

    def test_repeaterbook_do_fetch_exception_does_not_propagate(self):
        req = models.ProgrammingRequest(location_text='Idaho')
        with mock.patch.object(
                repeaterbook.RepeaterBook, 'do_fetch',
                side_effect=ValueError('malformed response')):
            candidates, err = sources.fetch_repeaterbook(req, '')
        self.assertEqual([], candidates)
        self.assertIn('malformed response', err)

    def test_build_candidates_never_raises_on_source_exception(self):
        req = models.ProgrammingRequest(
            requested_services=(models.SERVICE_HAM,), location_text='Idaho')
        with mock.patch.object(
                repeaterbook.RepeaterBook, 'do_fetch',
                side_effect=RuntimeError('unexpected')):
            candidates, warnings, skipped = sources.build_candidates(
                req, network_allowed=True)
        # Did not raise -- got here -- and produced a warning instead.
        self.assertTrue(any('unavailable' in w.message for w in warnings))
        self.assertIn('RepeaterBook (amateur)', skipped)


if __name__ == '__main__':
    unittest.main()
