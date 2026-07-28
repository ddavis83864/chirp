"""Save/reopen persistence for the Programming Assistant's apply
output, using a real file-backed generic_csv.CSVRadio -- no wx
dependency needed here since Apply only ever calls
chirp_common.Radio.set_memory()/save(), both of which are already
exercised the same way a normal hand-edit or CSVRadio round trip
would be.
"""

import os
import tempfile
import unittest

from chirp import chirp_common
from chirp.assistant import models
from chirp.assistant import service
from chirp.drivers import generic_csv


class SaveReopenTest(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix='.csv')
        os.close(fd)
        self.addCleanup(os.unlink, self.path)
        # A blank CSVRadio(None) needs an initial save to exist as a
        # real file on disk before it can be treated as "already
        # open" the way the wizard would encounter it.
        blank = generic_csv.CSVRadio(None)
        blank.save(self.path)

    def _apply_plan_directly(self, radio, req):
        """Mirrors exactly what ResultPage._apply() does, without any
        wx/undo_context machinery, which isn't needed to prove
        save/reopen persistence."""
        svc = service.AssistantService(radio)
        plan = svc.build_plan(req, network_allowed=False)
        svc.convert_and_validate(plan)
        finalized = svc.finalize_for_apply(plan)
        for _candidate, memory in finalized:
            radio.set_memory(memory)
        return plan, finalized

    def test_applied_fields_persist_through_save_and_reopen(self):
        radio = generic_csv.CSVRadio(self.path)
        req = models.ProgrammingRequest(
            requested_services=(models.SERVICE_WEATHER,), channel_limit=20)
        _plan, finalized = self._apply_plan_directly(radio, req)
        self.assertEqual(7, len(finalized))
        expected = {}
        for _c, memory in finalized:
            expected[memory.number] = (
                memory.freq, memory.name, memory.mode, memory.duplex,
                memory.tmode)

        radio.save(self.path)
        reopened = generic_csv.CSVRadio(self.path)

        for number, (freq, name, mode, duplex, tmode) in expected.items():
            mem = reopened.get_memory(number)
            self.assertFalse(mem.empty, 'memory %i lost on reopen' % number)
            self.assertEqual(freq, mem.freq)
            self.assertEqual(name, mem.name)
            self.assertEqual(mode, mem.mode)
            self.assertEqual(duplex, mem.duplex)
            self.assertEqual(tmode, mem.tmode)

    def test_excluded_candidate_absent_after_reopen(self):
        radio = generic_csv.CSVRadio(self.path)
        req = models.ProgrammingRequest(
            requested_services=(models.SERVICE_WEATHER,), channel_limit=20)
        svc = service.AssistantService(radio)
        plan = svc.build_plan(req, network_allowed=False)
        svc.convert_and_validate(plan)
        weather = [
            c for c in plan.all_candidates
            if c.service == models.SERVICE_WEATHER]
        excluded = weather[0]
        excluded.include = False
        excluded_number = excluded.memory_number

        finalized = svc.finalize_for_apply(plan)
        for _candidate, memory in finalized:
            radio.set_memory(memory)
        radio.save(self.path)

        reopened = generic_csv.CSVRadio(self.path)
        self.assertTrue(reopened.get_memory(excluded_number).empty)

    def test_receive_only_safety_persists_through_reopen(self):
        radio = generic_csv.CSVRadio(self.path)
        req = models.ProgrammingRequest(
            requested_services=(models.SERVICE_WEATHER,
                                models.SERVICE_AVIATION),
            channel_limit=20)
        _plan, finalized = self._apply_plan_directly(radio, req)
        radio.save(self.path)
        reopened = generic_csv.CSVRadio(self.path)

        for candidate, memory in finalized:
            if candidate.receive_only:
                mem = reopened.get_memory(memory.number)
                self.assertEqual(
                    'off', mem.duplex,
                    'memory %i lost its receive-only duplex on reopen' %
                    memory.number)

    def test_preexisting_unrelated_memory_unchanged_after_reopen(self):
        radio = generic_csv.CSVRadio(self.path)
        lo, _hi = radio.get_features().memory_bounds
        unrelated_number = lo + 90
        unrelated = chirp_common.Memory(number=unrelated_number,
                                        name='KEEPME')
        unrelated.freq = 446000000
        radio.set_memory(unrelated)
        radio.save(self.path)

        radio = generic_csv.CSVRadio(self.path)
        req = models.ProgrammingRequest(
            requested_services=(models.SERVICE_WEATHER,), channel_limit=20)
        self._apply_plan_directly(radio, req)
        radio.save(self.path)

        reopened = generic_csv.CSVRadio(self.path)
        mem = reopened.get_memory(unrelated_number)
        self.assertFalse(mem.empty)
        self.assertEqual(446000000, mem.freq)
        self.assertEqual('KEEPME', mem.name)


if __name__ == '__main__':
    unittest.main()
