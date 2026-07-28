import unittest

from chirp.assistant import models
from chirp.assistant import service
from chirp.drivers import generic_csv


class AssistantServiceTest(unittest.TestCase):
    def setUp(self):
        # CSVRadio(None) builds a blank, in-memory-only radio (see
        # generic_csv.CSVRadio.__init__) -- no file is read or
        # written, so this can never collide with an unrelated
        # developer file (e.g. a personal test.csv left at the repo
        # root), differ by working directory, or leak state between
        # tests or parallel runs. This was previously
        # generic_csv.CSVRadio applied to a hardcoded repo-root
        # 'test.csv' filename
        # -- when absent (every normal checkout) CSVRadio already fell
        # back to this same blank-radio behavior, so this is not a
        # behavior change; it makes that reliance explicit instead of
        # accidental, and removes the failure mode where a same-named
        # file that does exist gets loaded instead, with different
        # (and non-deterministic) pre-occupied memory content.
        self.radio = generic_csv.CSVRadio(None)
        self.svc = service.AssistantService(self.radio)

    def test_reads_existing_memories(self):
        occupied = [n for n, m in self.svc.existing_memories if not m.empty]
        self.assertGreater(len(occupied), 0)

    def test_invalid_request_raises(self):
        req = models.ProgrammingRequest(channel_limit=-1)
        with self.assertRaises(ValueError):
            self.svc.build_plan(req, network_allowed=False)

    def test_offline_weather_aviation_plan(self):
        req = models.ProgrammingRequest(
            requested_services=(models.SERVICE_WEATHER,
                                models.SERVICE_AVIATION),
            channel_limit=20)
        plan = self.svc.build_plan(req, network_allowed=False)
        self.svc.convert_and_validate(plan)
        for c in plan.all_candidates:
            if c.include:
                self.assertTrue(c.receive_only)
                self.assertEqual(models.STATUS_RECEIVE_ONLY, c.status)

    def test_ham_without_license_gets_calling_freqs_receive_flagged(self):
        # No amateur license declared: candidates still get generated
        # (the calling-frequency static source doesn't gate on license),
        # but none may be transmit-enabled.
        req = models.ProgrammingRequest(
            amateur_license=models.LICENSE_NONE,
            requested_services=(models.SERVICE_HAM,), channel_limit=20)
        plan = self.svc.build_plan(req, network_allowed=False)
        for c in plan.all_candidates:
            if c.service == models.SERVICE_HAM:
                self.assertTrue(c.receive_only)

    def test_technician_ham_calling_freq_transmit_enabled(self):
        req = models.ProgrammingRequest(
            amateur_license='technician',
            requested_services=(models.SERVICE_HAM,), channel_limit=20)
        plan = self.svc.build_plan(req, network_allowed=False)
        ham_candidates = [c for c in plan.all_candidates
                          if c.service == models.SERVICE_HAM]
        self.assertTrue(any(not c.receive_only for c in ham_candidates))

    def test_finalize_for_apply_only_returns_valid_included(self):
        req = models.ProgrammingRequest(
            requested_services=(models.SERVICE_WEATHER,), channel_limit=20)
        plan = self.svc.build_plan(req, network_allowed=False)
        self.svc.convert_and_validate(plan)
        finalized = self.svc.finalize_for_apply(plan)
        self.assertEqual(7, len(finalized))
        for candidate, memory in finalized:
            self.assertTrue(candidate.include)
            self.assertEqual((), candidate.errors)
            self.assertEqual(candidate.memory_number, memory.number)

    def test_finalize_blocks_slot_occupied_since_plan_was_built(self):
        # Edge case: something else (a manual edit, or re-finalizing an
        # already-applied plan) occupies a candidate's target memory
        # AFTER the plan was built but BEFORE finalize_for_apply()
        # actually runs -- it must be blocked, not silently
        # overwritten when applied.
        req = models.ProgrammingRequest(
            requested_services=(models.SERVICE_WEATHER,), channel_limit=2)
        plan = self.svc.build_plan(req, network_allowed=False)
        self.svc.convert_and_validate(plan)
        targets = [
            c.memory_number for c in plan.all_candidates if c.include]
        self.assertEqual(2, len(targets))

        manual = self.radio.get_memory(targets[0])
        manual.name = 'MANUAL'
        manual.freq = 442000000
        manual.empty = False
        self.radio.set_memory(manual)

        finalized = self.svc.finalize_for_apply(plan)
        finalized_numbers = {memory.number for _c, memory in finalized}
        self.assertNotIn(targets[0], finalized_numbers)
        self.assertIn(targets[1], finalized_numbers)

        blocked = [
            c for c in plan.all_candidates
            if c.memory_number == targets[0]][0]
        self.assertFalse(blocked.include)
        self.assertTrue(blocked.errors)

        # And the manual edit itself is provably untouched.
        still_manual = self.radio.get_memory(targets[0])
        self.assertEqual('MANUAL', still_manual.name)
        self.assertEqual(442000000, still_manual.freq)

    def test_reapplying_the_same_plan_is_blocked_not_silently_repeated(self):
        req = models.ProgrammingRequest(
            requested_services=(models.SERVICE_WEATHER,), channel_limit=20)
        plan = self.svc.build_plan(req, network_allowed=False)
        self.svc.convert_and_validate(plan)
        first = self.svc.finalize_for_apply(plan)
        self.assertEqual(7, len(first))
        for _c, memory in first:
            self.radio.set_memory(memory)

        second = self.svc.finalize_for_apply(plan)
        self.assertEqual(
            [], second,
            'finalize_for_apply() let an already-applied plan through '
            'a second time instead of blocking the now-occupied slots')

    def test_approved_existing_conflict_replacement_still_allowed(self):
        # The occupancy re-check must NOT block a candidate the
        # planner already flagged as an approved replacement -- that
        # would defeat "allow duplicate replacement" entirely.
        existing_number = 5
        existing = self.radio.get_memory(existing_number)
        existing.freq = 162400000  # matches NOAA Weather 1
        existing.name = 'OLDWX'
        existing.mode = 'FM'
        existing.empty = False
        self.radio.set_memory(existing)
        svc = service.AssistantService(
            self.radio,
            existing_memories=[(existing_number,
                                self.radio.get_memory(existing_number))])

        req = models.ProgrammingRequest(
            requested_services=(models.SERVICE_WEATHER,), channel_limit=20,
            allow_duplicate_replacement=True)
        plan = svc.build_plan(req, network_allowed=False)
        # Right after planning (before convert_and_validate() below
        # reclassifies .status from validation results -- a separate,
        # pre-existing quirk where STATUS_EXISTING_CONFLICT doesn't
        # survive that pass), confirm the planner did flag this as an
        # approved replacement in the first place.
        conflict = [
            c for c in plan.all_candidates
            if c.memory_number == existing_number]
        self.assertEqual(1, len(conflict))
        self.assertIn('replace existing memory', conflict[0].reason.lower())

        svc.convert_and_validate(plan)
        finalized = svc.finalize_for_apply(plan)
        finalized_numbers = {memory.number for _c, memory in finalized}
        self.assertIn(existing_number, finalized_numbers)

    def test_protected_ranges_never_allocated(self):
        req = models.ProgrammingRequest(
            requested_services=(models.SERVICE_WEATHER,),
            protected_memory_ranges=((0, 999),),
            requested_start_memory=0, requested_end_memory=999,
            channel_limit=20)
        plan = self.svc.build_plan(req, network_allowed=False)
        # Every weather candidate should fail to find a slot since the
        # entire requested range is protected.
        for c in plan.all_candidates:
            self.assertFalse(c.include)

    def test_capacity_limited_flag_set_when_over_limit(self):
        req = models.ProgrammingRequest(
            requested_services=(models.SERVICE_WEATHER,
                                models.SERVICE_AVIATION),
            channel_limit=1)
        plan = self.svc.build_plan(req, network_allowed=False)
        self.assertTrue(plan.capacity_limited)
        included = [c for c in plan.all_candidates if c.include]
        self.assertEqual(1, len(included))
        # Nothing was silently dropped from the plan itself.
        self.assertEqual(9, len(plan.all_candidates))

    def test_zero_writable_memories_does_not_crash(self):
        # The entire numeric range protected: no candidate can ever be
        # allocated a slot. Must degrade to a clean, empty apply-ready
        # result, not raise.
        req = models.ProgrammingRequest(
            requested_services=(models.SERVICE_WEATHER,), channel_limit=20,
            protected_memory_ranges=((0, 999),))
        plan = self.svc.build_plan(req, network_allowed=False)
        self.svc.convert_and_validate(plan)
        finalized = self.svc.finalize_for_apply(plan)

        self.assertEqual([], finalized)
        self.assertTrue(plan.capacity_limited)
        # Still not silently discarded from the plan itself.
        self.assertEqual(7, len(plan.all_candidates))
        for c in plan.all_candidates:
            self.assertFalse(c.include)
            self.assertTrue(c.reason)

    def test_planner_returning_no_usable_rows_does_not_crash(self):
        # Only unsupported-service requests: build_candidates()
        # returns nothing to plan at all.
        req = models.ProgrammingRequest(
            requested_services=(models.SERVICE_MARINE,), channel_limit=20)
        plan = self.svc.build_plan(req, network_allowed=False)
        self.svc.convert_and_validate(plan)
        finalized = self.svc.finalize_for_apply(plan)

        self.assertEqual([], plan.all_candidates)
        self.assertEqual([], finalized)
        self.assertIn('Marine', plan.skipped_sources)

    def test_existing_memories_preserved_by_default(self):
        before = {n: m.freq for n, m in self.svc.existing_memories
                  if not m.empty}
        req = models.ProgrammingRequest(
            requested_services=(models.SERVICE_WEATHER,), channel_limit=20)
        plan = self.svc.build_plan(req, network_allowed=False)
        allocated = {c.memory_number for c in plan.all_candidates
                     if c.include}
        self.assertEqual(set(), allocated & set(before.keys()))


if __name__ == '__main__':
    unittest.main()
