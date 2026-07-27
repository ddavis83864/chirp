"""Representative destination-radio capability profiles for the
Programming Assistant's convert/validate/plan pipeline.

tests/unit/test_assistant_converter_validator.py already covers the
basics (duplex handling, out-of-band frequencies, name truncation,
power adjustment) against one configurable FakeRadio.
tests/unit/test_assistant_service.py covers end-to-end planning
against a real generic_csv.CSVRadio.

This module fills specific capability-profile gaps identified during
remediation review: a restricted name character set, a radio that
cannot represent any tone/DTCS squelch, a radio near its numeric
memory capacity with a heavily populated existing image, a radio with
an immutable/special memory that is technically still "empty" (so it
would otherwise look like free space to the planner), and radios that
differ only in has_bank -- to confirm the assistant's behavior does
not depend on banks at all, since it never reads or writes them.
"""

import unittest

from chirp import chirp_common
from chirp.assistant import capability
from chirp.assistant import converter
from chirp.assistant import models
from chirp.assistant import planner
from chirp.assistant import service
from chirp.assistant import validator
from chirp.drivers import generic_csv


class ProfileRadio:
    """A more capability-configurable in-memory Radio than the
    converter/validator test module's FakeRadio: adds valid_characters,
    valid_tmodes/valid_dtcs_codes, has_bank, and support for seeding
    specific memory numbers (occupied and/or immutable)."""

    def __init__(self, bands=((144000000, 148000000),
                              (420000000, 450000000)),
                 duplexes=('', '-', '+'), name_length=8,
                 power_levels=None, valid_characters=None,
                 valid_tmodes=('', 'Tone', 'TSQL'),
                 valid_dtcs_codes=None, memory_bounds=(0, 99),
                 has_bank=False, immutable_numbers=()):
        self._bands = bands
        self._duplexes = duplexes
        self._name_length = name_length
        self._power_levels = power_levels or []
        self._valid_characters = (
            valid_characters if valid_characters is not None
            else chirp_common.CHARSET_UPPER_NUMERIC)
        self._valid_tmodes = valid_tmodes
        self._valid_dtcs_codes = (
            valid_dtcs_codes if valid_dtcs_codes is not None
            else list(chirp_common.DTCS_CODES))
        self._memory_bounds = memory_bounds
        self._has_bank = has_bank
        self._immutable_numbers = set(immutable_numbers)
        self._memories = {}

    def seed(self, number, **kwargs):
        mem = chirp_common.Memory(number=number)
        for key, value in kwargs.items():
            setattr(mem, key, value)
        if number in self._immutable_numbers:
            mem.immutable = list(kwargs.keys()) or ['freq']
        self._memories[number] = mem

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.valid_bands = list(self._bands)
        rf.valid_duplexes = list(self._duplexes)
        rf.valid_modes = ['FM']
        rf.valid_tmodes = list(self._valid_tmodes)
        rf.valid_dtcs_codes = list(self._valid_dtcs_codes)
        rf.valid_characters = self._valid_characters
        rf.valid_name_length = self._name_length
        rf.valid_power_levels = self._power_levels
        rf.memory_bounds = self._memory_bounds
        rf.has_bank = self._has_bank
        return rf

    def get_memory(self, number):
        if number in self._memories:
            return self._memories[number]
        mem = chirp_common.Memory(number=number, empty=True)
        if number in self._immutable_numbers:
            # A special channel that is immutable but still reads as
            # "empty" -- e.g. a fixed priority/call slot nobody has
            # programmed content into yet.
            mem.immutable = ['freq']
        return mem

    def filter_name(self, name):
        # Mirrors chirp_common.Radio.filter_name's default logic.
        rf = self.get_features()
        if rf.valid_characters == rf.valid_characters.upper():
            name = name.upper()
        return ''.join(x for x in name[:rf.valid_name_length]
                       if x in rf.valid_characters)

    def check_set_memory_immutable_policy(self, existing, new):
        for field in existing.immutable:
            if getattr(existing, field) != getattr(new, field):
                raise chirp_common.ImmutableValueError(
                    'Field %s is not mutable on memory %i' %
                    (field, existing.number))

    def validate_memory(self, mem):
        return self.get_features().validate_memory(mem)

    def set_memory(self, mem):
        existing = self.get_memory(mem.number)
        self.check_set_memory_immutable_policy(existing, mem)
        self._memories[mem.number] = mem


def _cap(radio):
    return capability.snapshot(radio)


def _cand(freq=146850000, tx_freq=146250000, receive_only=False,
          mode='FM', name='TEST', number=None, tmode='', rtone=88.5,
          dtcs=23):
    c = models.ChannelCandidate(
        source='t', service=models.SERVICE_HAM, group='g', label=name,
        freq=freq, tx_freq=tx_freq, mode=mode, receive_only=receive_only,
        tmode=tmode, rtone=rtone, dtcs=dtcs)
    c.memory_number = number
    c.name = name
    return c


class RestrictedCharsetProfileTest(unittest.TestCase):
    """A radio whose name field only accepts CHARSET_UPPER_NUMERIC --
    the actual default used by most real drivers."""

    def test_lowercase_and_symbols_stripped_from_name(self):
        radio = ProfileRadio()
        c = _cand(name="Coeur d'Alene Rptr!")
        mem = converter.convert_candidate(c, radio, _cap(radio))
        self.assertIsNotNone(mem)
        for ch in mem.name:
            self.assertIn(ch, chirp_common.CHARSET_UPPER_NUMERIC)


class ToneRestrictedProfileTest(unittest.TestCase):
    """A radio that cannot do any tone/DTCS squelch at all -- e.g. a
    basic scanner-style receive radio. A real RepeaterBook result can
    carry a required Tone/TSQL; the destination must not silently
    claim to reproduce that if it structurally cannot."""

    def test_tone_squelch_not_silently_dropped_as_valid(self):
        radio = ProfileRadio(valid_tmodes=('',))
        c = _cand(freq=146850000, tx_freq=146250000, tmode='Tone',
                  rtone=100.0)
        mem = converter.convert_candidate(c, radio, _cap(radio))
        # strict=False still returns a best-effort memory (likely with
        # tmode coerced to ''); the destination validate_memory() pass
        # is what must catch the mismatch if it's not representable.
        if mem is not None:
            validator.validate_and_classify(c, mem, radio)
            if mem.tmode != 'Tone':
                # Coerced away -- must not be presented as READY
                # without at least a recorded adjustment/warning.
                self.assertTrue(c.adjustments or c.warnings or
                                not c.include)


class NearFullCapacityProfileTest(unittest.TestCase):
    """A radio with a tiny numeric range that's already mostly
    occupied by an existing codeplug."""

    def test_capacity_limited_and_nothing_silently_dropped(self):
        radio = ProfileRadio(memory_bounds=(0, 4))
        for n in (0, 1, 2, 3):
            radio.seed(n, freq=146000000 + n * 100000, name='EXIST%i' % n)
        existing = [(n, radio.get_memory(n)) for n in range(0, 5)]

        req = models.ProgrammingRequest(
            requested_services=(models.SERVICE_WEATHER,), channel_limit=20)
        svc = service.AssistantService(radio, existing_memories=existing)
        plan = svc.build_plan(req, network_allowed=False)

        self.assertTrue(plan.capacity_limited)
        included = [c for c in plan.all_candidates if c.include]
        # Only memory number 4 was free.
        self.assertLessEqual(len(included), 1)
        # All 7 weather candidates are still present in the plan,
        # just not all included -- nothing vanished silently.
        self.assertEqual(7, len(plan.all_candidates))
        for c in plan.all_candidates:
            if not c.include:
                self.assertTrue(c.reason)


class ImmutableSpecialMemoryProfileTest(unittest.TestCase):
    """A memory number that reads as empty (so it looks like free
    space) but is marked immutable -- e.g. a fixed priority/call
    channel. The planner must not hand out a slot that Apply cannot
    actually write to."""

    def test_immutable_empty_slot_is_not_allocated(self):
        radio = ProfileRadio(memory_bounds=(0, 1), immutable_numbers={0})
        existing = [(n, radio.get_memory(n)) for n in range(0, 2)]
        candidates = [
            _cand(freq=146520000, tx_freq=None, number=None)
            for _ in range(2)]
        request = models.ProgrammingRequest(channel_limit=20)

        planner.allocate_memory_numbers(
            candidates, capability.snapshot(radio), existing, request)

        allocated = [c.memory_number for c in candidates if c.include]
        self.assertNotIn(0, allocated,
                         'planner allocated the immutable slot 0; Apply '
                         'would raise ImmutableValueError for it')


class BankAgnosticProfileTest(unittest.TestCase):
    """The assistant never reads or writes bank assignments (see
    capability.py's has_bank field, which nothing else in
    chirp.assistant consumes) -- confirm identical, correct behavior
    whether the destination radio has banks or not."""

    def test_plan_identical_regardless_of_has_bank(self):
        no_bank = ProfileRadio(has_bank=False)
        with_bank = ProfileRadio(has_bank=True)
        req = models.ProgrammingRequest(
            requested_services=(models.SERVICE_WEATHER,), channel_limit=20)

        svc_no_bank = service.AssistantService(no_bank, existing_memories=[])
        svc_with_bank = service.AssistantService(
            with_bank, existing_memories=[])
        plan_no_bank = svc_no_bank.build_plan(req, network_allowed=False)
        plan_with_bank = svc_with_bank.build_plan(req, network_allowed=False)

        self.assertEqual(
            [c.freq for c in plan_no_bank.all_candidates],
            [c.freq for c in plan_with_bank.all_candidates])
        for radio in (no_bank, with_bank):
            self.assertFalse(hasattr(radio, 'get_bank_model'))


class GenericCSVNearCapacityProfileTest(unittest.TestCase):
    """The same near-capacity scenario against a real driver
    (generic_csv.CSVRadio), not a hand-built fake, to confirm the
    planner's capacity handling holds up against actual chirp_common
    validate_memory()/filter_name() behavior."""

    def test_capacity_limited_against_real_csv_radio(self):
        # CSVRadio's default memory_bounds is (0, 999) -- generous, not
        # a near-capacity profile on its own. Simulate a user who has
        # restricted the assistant to a small existing range (e.g. "only
        # use channels 0-2 of my codeplug"), which is the realistic way
        # this scenario occurs against a real driver with a big range.
        radio = generic_csv.CSVRadio(None)
        rf = radio.get_features()
        lo, _hi = rf.memory_bounds
        tight_hi = lo + 2
        for n in range(lo, tight_hi):
            mem = chirp_common.Memory(number=n, name='EXIST%i' % n)
            mem.freq = 146000000 + n * 10000
            radio.set_memory(mem)
        existing = [(n, radio.get_memory(n)) for n in range(lo, tight_hi + 1)]

        req = models.ProgrammingRequest(
            requested_services=(models.SERVICE_WEATHER,), channel_limit=20,
            requested_start_memory=lo, requested_end_memory=tight_hi)
        svc = service.AssistantService(radio, existing_memories=existing)
        plan = svc.build_plan(req, network_allowed=False)
        svc.convert_and_validate(plan)
        finalized = svc.finalize_for_apply(plan)

        self.assertLessEqual(len(finalized), 1)
        for _candidate, memory in finalized:
            self.assertEqual(tight_hi, memory.number)


if __name__ == '__main__':
    unittest.main()
