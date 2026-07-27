import unittest

from chirp import chirp_common
from chirp.assistant import capability
from chirp.assistant import converter
from chirp.assistant import models
from chirp.assistant import validator


class FakeRadio:
    """A minimal, in-memory Radio good enough for import_logic's
    non-LiveRadio path (get_memory/check_set_memory_immutable_policy/
    validate_memory/filter_name)."""

    def __init__(self, bands=((144000000, 148000000),
                              (420000000, 450000000)),
                 duplexes=('', '-', '+'), name_length=8,
                 power_levels=None):
        self._bands = bands
        self._duplexes = duplexes
        self._name_length = name_length
        self._power_levels = power_levels or []
        self._memories = {}

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.valid_bands = list(self._bands)
        rf.valid_duplexes = list(self._duplexes)
        rf.valid_modes = ['FM']
        rf.valid_tmodes = ['', 'Tone', 'TSQL']
        rf.valid_name_length = self._name_length
        rf.valid_power_levels = self._power_levels
        rf.memory_bounds = (0, 99)
        return rf

    def get_memory(self, number):
        return self._memories.get(
            number, chirp_common.Memory(number=number, empty=True))

    def filter_name(self, name):
        return name[:self._name_length].upper()

    def check_set_memory_immutable_policy(self, existing, new):
        chirp_common.Radio.check_set_memory_immutable_policy(
            self, existing, new)

    def validate_memory(self, mem):
        return self.get_features().validate_memory(mem)


def _cap(radio):
    return capability.snapshot(radio)


def _cand(freq=146850000, tx_freq=146250000, receive_only=False,
          mode='FM', name='TEST', number=5):
    c = models.ChannelCandidate(
        source='t', service=models.SERVICE_HAM, group='g', label=name,
        freq=freq, tx_freq=tx_freq, mode=mode, receive_only=receive_only)
    c.memory_number = number
    c.name = name
    return c


class ConvertCandidateTest(unittest.TestCase):
    def test_repeater_converts_with_correct_duplex(self):
        radio = FakeRadio()
        c = _cand()
        mem = converter.convert_candidate(c, radio, _cap(radio))
        self.assertIsNotNone(mem)
        self.assertEqual(146850000, mem.freq)
        self.assertEqual('-', mem.duplex)
        self.assertEqual(600000, mem.offset)

    def test_simplex_converts_with_blank_duplex(self):
        radio = FakeRadio()
        c = _cand(freq=146520000, tx_freq=None)
        mem = converter.convert_candidate(c, radio, _cap(radio))
        self.assertEqual('', mem.duplex)

    def test_positive_offset(self):
        radio = FakeRadio()
        c = _cand(freq=146000000, tx_freq=146600000)
        mem = converter.convert_candidate(c, radio, _cap(radio))
        self.assertEqual('+', mem.duplex)
        self.assertEqual(600000, mem.offset)

    def test_odd_split_preserved_when_supported(self):
        radio = FakeRadio(duplexes=('', '-', '+', 'split'))
        # chirp_common.split_to_offset only chooses 'split' semantics
        # when the rx/tx gap exceeds 70 MHz -- use a genuinely large one.
        c = _cand(freq=146000000, tx_freq=220000000)
        mem = converter.convert_candidate(c, radio, _cap(radio))
        self.assertEqual('split', mem.duplex)
        self.assertEqual(220000000, mem.offset)

    def test_receive_only_converts_with_off_duplex_when_supported(self):
        radio = FakeRadio(duplexes=('', '-', '+', 'off'))
        c = _cand(freq=162400000, tx_freq=None, receive_only=True)
        mem = converter.convert_candidate(c, radio, _cap(radio))
        self.assertIsNotNone(mem)
        self.assertEqual('off', mem.duplex)

    def test_receive_only_blocked_when_radio_cannot_represent_it(self):
        # This is the critical safety case: a radio with no "off"
        # duplex must BLOCK a receive-only candidate, never silently
        # make it a transmit-capable simplex channel.
        radio = FakeRadio(duplexes=('', '-', '+'))
        c = _cand(freq=162400000, tx_freq=None, receive_only=True)
        mem = converter.convert_candidate(c, radio, _cap(radio))
        self.assertIsNone(mem)
        self.assertEqual(models.STATUS_UNSUPPORTED_BY_RADIO, c.status)
        self.assertFalse(c.include)
        self.assertTrue(c.errors)

    def test_unsupported_mode_blocked(self):
        radio = FakeRadio()  # only supports FM
        c = _cand(mode='DMR')
        mem = converter.convert_candidate(c, radio, _cap(radio))
        # import_mem with strict=False still returns a best-effort
        # memory; the destination-radio validate_memory() pass (in
        # validator.py) is what actually rejects it -- confirm that
        # handoff works.
        if mem is not None:
            validator.validate_and_classify(c, mem, radio)
            self.assertEqual(models.STATUS_BLOCKED, c.status)
            self.assertFalse(c.include)

    def test_name_truncated_by_destination(self):
        radio = FakeRadio(name_length=4)
        c = _cand(name='LongName')
        mem = converter.convert_candidate(c, radio, _cap(radio))
        self.assertEqual(4, len(mem.name))

    def test_power_adjustment_recorded(self):
        radio = FakeRadio(power_levels=[
            chirp_common.PowerLevel('Low', watts=1),
            chirp_common.PowerLevel('High', watts=5)])
        c = _cand()
        c.power = 50  # way outside range
        mem = converter.convert_candidate(c, radio, _cap(radio))
        self.assertIsNotNone(mem)
        self.assertIn('power', c.adjustments)


class ValidateAndClassifyTest(unittest.TestCase):
    def test_clean_conversion_is_ready(self):
        radio = FakeRadio()
        c = _cand(freq=146520000, tx_freq=None)
        mem = converter.convert_candidate(c, radio, _cap(radio))
        validator.validate_and_classify(c, mem, radio)
        self.assertEqual(models.STATUS_READY, c.status)
        self.assertTrue(c.include)

    def test_receive_only_status_set(self):
        radio = FakeRadio(duplexes=('', '-', '+', 'off'),
                          bands=((162000000, 163000000),))
        c = _cand(freq=162400000, tx_freq=None, receive_only=True)
        mem = converter.convert_candidate(c, radio, _cap(radio))
        validator.validate_and_classify(c, mem, radio)
        self.assertEqual(models.STATUS_RECEIVE_ONLY, c.status)

    def test_out_of_band_frequency_blocked(self):
        radio = FakeRadio(bands=((144000000, 148000000),))
        c = _cand(freq=27000000, tx_freq=None)  # CB band, unsupported
        mem = converter.convert_candidate(c, radio, _cap(radio))
        self.assertIsNotNone(mem)  # strict=False still returns it
        validator.validate_and_classify(c, mem, radio)
        self.assertEqual(models.STATUS_BLOCKED, c.status)
        self.assertFalse(c.include)
        self.assertTrue(c.errors)

    def test_adjusted_status_when_fields_changed_but_no_errors(self):
        radio = FakeRadio(name_length=3)
        c = _cand(freq=146520000, tx_freq=None, name='LongerName')
        mem = converter.convert_candidate(c, radio, _cap(radio))
        validator.validate_and_classify(c, mem, radio)
        self.assertEqual(models.STATUS_ADJUSTED, c.status)
        self.assertTrue(c.include)

    def test_revalidation_after_edit_catches_new_problem(self):
        radio = FakeRadio()
        c = _cand(freq=146520000, tx_freq=None)
        mem = converter.convert_candidate(c, radio, _cap(radio))
        validator.validate_and_classify(c, mem, radio)
        self.assertEqual(models.STATUS_READY, c.status)

        # Simulate a user edit during review that breaks the memory,
        # then a mandatory revalidation before apply.
        mem.mode = 'DMR'
        c.adjustments = ()
        validator.validate_and_classify(c, mem, radio)
        self.assertEqual(models.STATUS_BLOCKED, c.status)
        self.assertFalse(c.include)


if __name__ == '__main__':
    unittest.main()
