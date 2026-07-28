"""Representative end-to-end planning scenarios for the Programming
Assistant, run against a real generic_csv.CSVRadio (not a hand-built
fake) with network_allowed=False throughout -- no automated test in
this suite makes a real network call, per this feature's own design
(chirp.assistant.sources never requires network access; offline mode
degrades to static tables and a clear "network disabled" warning).

Each scenario exercises chirp.assistant.service.AssistantService the
same way chirp.wxui.programming_assistant's ConfirmPage does, then
asserts on the resulting chirp_common.Memory objects and
ChannelCandidate metadata -- not just that "something" got built.
"""

import dataclasses
import unittest

from chirp import chirp_common
from chirp.assistant import models
from chirp.assistant import service
from chirp.drivers import generic_csv


def _assert_universally_valid(testcase, radio, memory):
    """Checks that apply to every candidate memory in every scenario,
    matching the acceptance criteria common to all of them."""
    rf = radio.get_features()
    lo, hi = rf.memory_bounds
    testcase.assertTrue(lo <= memory.number <= hi,
                        'memory number %s outside bounds %s-%s' %
                        (memory.number, lo, hi))
    testcase.assertGreater(memory.freq, 0)
    testcase.assertIn(memory.duplex, rf.valid_duplexes)
    testcase.assertIn(memory.mode, rf.valid_modes)
    testcase.assertLessEqual(len(memory.name), rf.valid_name_length)
    for ch in memory.name:
        testcase.assertIn(ch, rf.valid_characters)
    msgs = radio.validate_memory(chirp_common.FrozenMemory(memory))
    _warnings, errors = chirp_common.split_validation_msgs(msgs)
    testcase.assertEqual(
        [], list(errors),
        'a finalized, apply-ready memory must have no validation errors')


class ScenarioANorthIdahoTest(unittest.TestCase):
    """North Idaho general amateur-radio plan: amateur repeaters, NOAA
    Weather, 2m and 70cm simplex. Offline (no RepeaterBook network
    call), so "amateur repeaters" resolves to the static calling-
    frequency table rather than live repeater data -- that degradation
    is itself part of what's under test (see the "no invented source
    claims" requirement: nothing here may claim to be a real repeater
    when it's actually a generic calling frequency)."""

    def setUp(self):
        self.radio = generic_csv.CSVRadio(None)
        self.svc = service.AssistantService(self.radio, existing_memories=[])
        self.req = models.ProgrammingRequest(
            location_text='Coeur d\'Alene, Idaho',
            amateur_license=models.LICENSE_TECHNICIAN,
            requested_services=(models.SERVICE_HAM, models.SERVICE_WEATHER),
            channel_limit=40)

    def _build(self):
        plan = self.svc.build_plan(self.req, network_allowed=False)
        self.svc.convert_and_validate(plan)
        return plan

    def test_plan_is_deterministic_for_identical_inputs(self):
        plan_a = self._build()
        req2 = dataclasses.replace(self.req)
        svc2 = service.AssistantService(
            generic_csv.CSVRadio(None), existing_memories=[])
        plan_b = svc2.build_plan(req2, network_allowed=False)
        svc2.convert_and_validate(plan_b)

        key = lambda c: (c.service, c.freq, c.tx_freq, c.name)  # noqa: E731
        self.assertEqual(
            sorted((key(c) for c in plan_a.all_candidates)),
            sorted((key(c) for c in plan_b.all_candidates)))

    def test_no_source_ever_falsely_claims_live_repeater_data(self):
        plan = self._build()
        for c in plan.all_candidates:
            if c.service == models.SERVICE_HAM:
                # Offline: must be the static table, never described
                # as RepeaterBook/live data.
                self.assertNotIn('RepeaterBook', c.source)

    def test_weather_present_and_receive_only(self):
        plan = self._build()
        weather = [c for c in plan.all_candidates
                   if c.service == models.SERVICE_WEATHER]
        self.assertEqual(7, len(weather))
        for c in weather:
            self.assertTrue(c.receive_only)

    def test_finalized_memories_all_pass_universal_checks(self):
        plan = self._build()
        finalized = self.svc.finalize_for_apply(plan)
        self.assertGreater(len(finalized), 0)
        seen_numbers = set()
        for candidate, memory in finalized:
            _assert_universally_valid(self, self.radio, memory)
            self.assertNotIn(memory.number, seen_numbers,
                             'duplicate memory number allocated')
            seen_numbers.add(memory.number)
            self.assertTrue(candidate.source, 'candidate missing a source')


class ScenarioBReceiveOnlySafetyTest(unittest.TestCase):
    """Receive-only content mixed with transmit-capable memories: a
    receive-only candidate must never become transmit-capable, and
    protected receive-only services must use a safe (non-transmitting)
    duplex/offset combination -- never approximated as a plain simplex
    channel a user could key up on."""

    def test_receive_only_services_never_get_transmit_fields(self):
        radio = generic_csv.CSVRadio(None)
        svc = service.AssistantService(radio, existing_memories=[])
        req = models.ProgrammingRequest(
            amateur_license=models.LICENSE_EXTRA,
            requested_services=(
                models.SERVICE_HAM, models.SERVICE_WEATHER,
                models.SERVICE_AVIATION),
            channel_limit=40)
        plan = svc.build_plan(req, network_allowed=False)
        svc.convert_and_validate(plan)
        finalized = svc.finalize_for_apply(plan)

        for candidate, memory in finalized:
            if candidate.service in models.ALWAYS_RECEIVE_ONLY_SERVICES:
                self.assertTrue(candidate.receive_only)
                self.assertEqual(
                    'off', memory.duplex,
                    '%s candidate got a transmit-capable duplex (%r)' %
                    (candidate.service, memory.duplex))

    def test_ham_with_license_can_still_be_transmit_capable(self):
        # Contrast case: a licensed amateur's own calling-frequency
        # candidates ARE allowed to be transmit-capable -- confirms
        # the receive-only restriction above is service-specific, not
        # a blanket "nothing transmits" bug.
        radio = generic_csv.CSVRadio(None)
        svc = service.AssistantService(radio, existing_memories=[])
        req = models.ProgrammingRequest(
            amateur_license=models.LICENSE_TECHNICIAN,
            requested_services=(models.SERVICE_HAM,), channel_limit=40)
        plan = svc.build_plan(req, network_allowed=False)
        self.assertTrue(any(not c.receive_only for c in plan.all_candidates
                            if c.service == models.SERVICE_HAM))


class ScenarioCSparseImageTest(unittest.TestCase):
    """Mostly empty memory map: allocation must be predictable
    (ascending from the lowest free/unprotected number) and ordering
    deterministic."""

    def test_allocation_starts_low_and_is_ascending(self):
        radio = generic_csv.CSVRadio(None)
        svc = service.AssistantService(radio, existing_memories=[])
        req = models.ProgrammingRequest(
            requested_services=(models.SERVICE_WEATHER,), channel_limit=7)
        plan = svc.build_plan(req, network_allowed=False)
        numbers = [c.memory_number for c in plan.all_candidates if c.include]
        self.assertEqual(sorted(numbers), numbers)
        lo, _hi = radio.get_features().memory_bounds
        self.assertEqual(lo, numbers[0])
        self.assertEqual(list(range(lo, lo + len(numbers))), numbers)


class ScenarioDPartiallyPopulatedImageTest(unittest.TestCase):
    """Existing memories are preserved unless the user explicitly
    enables replacement; allocation skips occupied AND immutable
    locations (immutable-slot coverage already lives in
    test_assistant_radio_profiles.py -- this scenario focuses on the
    "existing memories preserved by default" acceptance criterion end
    to end, against a real driver)."""

    def setUp(self):
        self.radio = generic_csv.CSVRadio(None)
        lo, _hi = self.radio.get_features().memory_bounds
        self.occupied_number = lo
        occupied = chirp_common.Memory(number=self.occupied_number,
                                       name='EXISTING')
        occupied.freq = 146000000
        self.radio.set_memory(occupied)
        self.existing = [(n, self.radio.get_memory(n))
                         for n in range(lo, lo + 3)]

    def test_existing_memory_untouched_by_default(self):
        svc = service.AssistantService(
            self.radio, existing_memories=self.existing)
        req = models.ProgrammingRequest(
            requested_services=(models.SERVICE_WEATHER,), channel_limit=40)
        plan = svc.build_plan(req, network_allowed=False)
        allocated = {c.memory_number for c in plan.all_candidates
                     if c.include}
        self.assertNotIn(self.occupied_number, allocated)

        svc.convert_and_validate(plan)
        finalized = svc.finalize_for_apply(plan)
        for _candidate, memory in finalized:
            self.assertNotEqual(self.occupied_number, memory.number)
        # And the radio's own on-disk state for that slot is
        # untouched (nothing in build/convert/validate ever writes).
        still_there = self.radio.get_memory(self.occupied_number)
        self.assertEqual(146000000, still_there.freq)
        self.assertEqual('EXISTING', still_there.name)


class ScenarioENearFullImageTest(unittest.TestCase):
    """Nearly-full image: clear capacity warning, no silent overwrite,
    and -- since build_plan()/convert_and_validate() never call
    radio.set_memory() at all -- the user can always "cancel" (i.e.
    simply not proceed to Apply) with zero changes made, by
    construction rather than by a UI-level guard alone."""

    def test_capacity_limited_flag_and_no_writes_before_apply(self):
        radio = generic_csv.CSVRadio(None)
        lo, hi = radio.get_features().memory_bounds
        tight_hi = lo + 2
        # generic_csv.CSVRadio(None) ships a non-empty placeholder in
        # slot 0 by default -- snapshot actual before-state rather
        # than assuming "blank radio" means "every slot empty".
        before = [radio.get_memory(n) for n in range(lo, hi + 1)]
        req = models.ProgrammingRequest(
            requested_services=(models.SERVICE_WEATHER,), channel_limit=40,
            requested_start_memory=lo, requested_end_memory=tight_hi)
        svc = service.AssistantService(
            radio, existing_memories=list(zip(range(lo, hi + 1), before)))
        plan = svc.build_plan(req, network_allowed=False)

        self.assertTrue(plan.capacity_limited)
        included = [c for c in plan.all_candidates if c.include]
        self.assertLessEqual(len(included), tight_hi - lo + 1)
        excluded = [c for c in plan.all_candidates if not c.include]
        self.assertTrue(excluded)
        for c in excluded:
            self.assertTrue(c.reason, 'excluded candidate has no reason')

        # Nothing was written to the radio just by building/previewing
        # the plan -- "cancel" at this point is a true no-op.
        after = [radio.get_memory(n) for n in range(lo, hi + 1)]
        for n, (b, a) in enumerate(zip(before, after), start=lo):
            self.assertEqual(b.freq, a.freq, 'memory %i freq changed' % n)
            self.assertEqual(b.empty, a.empty,
                             'memory %i empty-state changed' % n)


if __name__ == '__main__':
    unittest.main()
