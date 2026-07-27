import os
import unittest

from chirp.assistant import models
from chirp.assistant import service
from chirp.drivers import generic_csv

_TEST_CSV = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))), 'test.csv')


class AssistantServiceTest(unittest.TestCase):
    def setUp(self):
        self.radio = generic_csv.CSVRadio(_TEST_CSV)
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
