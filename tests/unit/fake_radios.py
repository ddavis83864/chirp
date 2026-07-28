"""Representative fake target radios for profile capability/adaptation
tests (section 20.2 of the design doc). These are plain, hand-built
chirp_common.RadioFeatures configurations -- not real drivers -- so
tests never depend on physical hardware or a specific vendor driver.
"""

from chirp import chirp_common


class FakeRadio:
    """The minimum surface chirp.profiles.capabilities needs: a single
    get_features() call. Deliberately not a full chirp_common.Radio
    subclass -- the profile domain layer only ever needs features."""

    def __init__(self, features):
        self._features = features

    def get_features(self):
        return self._features


def build_features(**kwargs):
    f = chirp_common.RadioFeatures()
    for key, value in kwargs.items():
        setattr(f, key, value)
    return f


def feature_rich_radio():
    """Wide bands, all duplexes, DTCS, banks, comments, long names,
    variable power -- a generous, permissive target."""
    return FakeRadio(build_features(
        valid_bands=[(118000000, 174000000), (400000000, 480000000)],
        valid_duplexes=['', '+', '-', 'split', 'off'],
        valid_modes=list(chirp_common.MODES),
        valid_tmodes=list(chirp_common.TONE_MODES),
        valid_cross_modes=list(chirp_common.CROSS_MODES),
        has_dtcs=True,
        has_rx_dtcs=True,
        valid_dtcs_codes=list(chirp_common.DTCS_CODES),
        valid_power_levels=[
            chirp_common.PowerLevel('Low', watts=1),
            chirp_common.PowerLevel('Mid', watts=5),
            chirp_common.PowerLevel('High', watts=50),
        ],
        has_name=True,
        valid_name_length=16,
        valid_characters=chirp_common.CHARSET_ASCII,
        has_comment=True,
        has_bank=True,
        has_bank_names=True,
        valid_skips=['', 'S', 'P'],
        memory_bounds=(0, 999),
    ))


def limited_analog_handheld():
    """A cheap analog-only HT: short names, no banks, FM/NFM only, a
    single VHF/UHF ham-band pair, two fixed power levels, no DTCS
    cross-mode support."""
    return FakeRadio(build_features(
        valid_bands=[(144000000, 148000000), (420000000, 450000000)],
        valid_duplexes=['', '+', '-', 'off'],
        valid_modes=['FM', 'NFM'],
        valid_tmodes=['', 'Tone', 'TSQL'],
        has_dtcs=False,
        valid_power_levels=[
            chirp_common.PowerLevel('Low', watts=1),
            chirp_common.PowerLevel('High', watts=5),
        ],
        has_name=True,
        valid_name_length=6,
        valid_characters=chirp_common.CHARSET_UPPER_NUMERIC,
        has_comment=False,
        has_bank=False,
        valid_skips=['', 'S'],
        memory_bounds=(0, 127),
    ))


def short_name_radio():
    """Only 4-character names, restricted charset."""
    return FakeRadio(build_features(
        valid_bands=[(136000000, 174000000)],
        valid_duplexes=['', '+', '-', 'off'],
        valid_modes=['FM'],
        has_name=True,
        valid_name_length=4,
        valid_characters=chirp_common.CHARSET_UPPER_NUMERIC,
        memory_bounds=(0, 199),
    ))


def no_bank_radio():
    return FakeRadio(build_features(
        valid_bands=[(136000000, 174000000)],
        valid_duplexes=['', '+', '-', 'off'],
        valid_modes=['FM'],
        has_bank=False,
        memory_bounds=(0, 199),
    ))


def restricted_range_radio():
    """Only covers the 2m ham band -- e.g. a receive-only aircraft/NOAA
    monitor frequency or an out-of-band repeater will not fit."""
    return FakeRadio(build_features(
        valid_bands=[(144000000, 148000000)],
        valid_duplexes=['', '+', '-', 'off'],
        valid_modes=['FM'],
        memory_bounds=(0, 199),
    ))


def cannot_enforce_receive_only_radio():
    """No 'off' duplex value at all -- this radio has no way to
    represent "do not transmit" for a given memory."""
    return FakeRadio(build_features(
        valid_bands=[(144000000, 148000000)],
        valid_duplexes=['', '+', '-'],
        valid_modes=['FM'],
        memory_bounds=(0, 199),
    ))


def analog_only_radio():
    """Would receive a digital-mode (e.g. DMR) channel request it
    cannot represent."""
    return FakeRadio(build_features(
        valid_bands=[(144000000, 148000000), (420000000, 450000000)],
        valid_duplexes=['', '+', '-', 'off'],
        valid_modes=['FM', 'NFM', 'AM'],
        memory_bounds=(0, 199),
    ))


def immutable_memory():
    """A pre-existing memory instance with some fields locked by the
    driver (e.g. a fixed public-safety or weather channel)."""
    mem = chirp_common.Memory()
    mem.number = 0
    mem.freq = 162550000
    mem.name = 'WX1'
    mem.immutable = ['freq', 'name']
    return mem
