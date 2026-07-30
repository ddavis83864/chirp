# Copyright 2026
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import unittest

import ddt

from chirp.assistant import bands
from chirp.assistant import models


@ddt.ddt
class BandRegistryCoverageTest(unittest.TestCase):
    """Not limited to 2m/70cm: every canonical band models.ALL_BANDS
    declares must actually be registered, with a real, ordered
    frequency range and a display name."""

    def test_every_canonical_band_is_registered(self):
        for band in models.ALL_BANDS:
            self.assertIn(band, bands.BAND_FREQ_RANGES_HZ,
                          '%s has no frequency range' % band)
            self.assertIn(band, bands.BAND_DISPLAY_NAMES,
                          '%s has no display name' % band)

    def test_every_range_is_well_formed(self):
        for band, (lo, hi) in bands.BAND_FREQ_RANGES_HZ.items():
            self.assertLess(lo, hi, '%s has an inverted/empty range' % band)
            self.assertGreater(lo, 0, '%s has a non-positive lower edge'
                               % band)

    def test_no_two_bands_share_identical_ranges(self):
        seen = {}
        for band, rng in bands.BAND_FREQ_RANGES_HZ.items():
            self.assertNotIn(
                rng, seen,
                '%s and %s have identical ranges' % (band, seen.get(rng)))
            seen[rng] = band

    @ddt.data(*models.ALL_BANDS)
    def test_canonical_id_normalizes_to_itself(self, band):
        self.assertEqual(band, bands.normalize_band(band))

    @ddt.data(*models.ALL_BANDS)
    def test_display_name_normalizes_to_canonical_id(self, band):
        name = bands.BAND_DISPLAY_NAMES[band]
        self.assertEqual(band, bands.normalize_band(name))

    @ddt.data(*models.ALL_BANDS)
    def test_representative_in_band_frequency_is_within_range(self, band):
        lo, hi = bands.BAND_FREQ_RANGES_HZ[band]
        midpoint = (lo + hi) // 2
        self.assertTrue(lo <= midpoint <= hi)

    @ddt.data(*models.ALL_BANDS)
    def test_lower_and_upper_boundary_are_inclusive(self, band):
        lo, hi = bands.BAND_FREQ_RANGES_HZ[band]
        from chirp.assistant import sources
        self.assertTrue(sources._matches_requested_constraints(
            models.ChannelCandidate(
                source='t', service=models.SERVICE_HAM, group='',
                label='lo', freq=lo),
            models.ProgrammingRequest(requested_bands=(band,))))
        self.assertTrue(sources._matches_requested_constraints(
            models.ChannelCandidate(
                source='t', service=models.SERVICE_HAM, group='',
                label='hi', freq=hi),
            models.ProgrammingRequest(requested_bands=(band,))))

    @ddt.data(*models.ALL_BANDS)
    def test_just_outside_boundary_is_excluded(self, band):
        lo, hi = bands.BAND_FREQ_RANGES_HZ[band]
        from chirp.assistant import sources
        req = models.ProgrammingRequest(requested_bands=(band,))
        self.assertFalse(sources._matches_requested_constraints(
            models.ChannelCandidate(
                source='t', service=models.SERVICE_HAM, group='',
                label='below', freq=lo - 1), req))
        self.assertFalse(sources._matches_requested_constraints(
            models.ChannelCandidate(
                source='t', service=models.SERVICE_HAM, group='',
                label='above', freq=hi + 1), req))


@ddt.ddt
class BandAliasNormalizationTest(unittest.TestCase):
    @ddt.data(
        ('2m', models.BAND_2M),
        ('2 meter', models.BAND_2M),
        ('2 meters', models.BAND_2M),
        ('two meter', models.BAND_2M),
        ('two meters', models.BAND_2M),
        ('TWO METERS', models.BAND_2M),
        ('70cm', models.BAND_70CM),
        ('70 cm', models.BAND_70CM),
        ('70 centimeter', models.BAND_70CM),
        ('70 centimeters', models.BAND_70CM),
        ('440', models.BAND_70CM),
        ('440 band', models.BAND_70CM),
        ('1.25 meter', models.BAND_222),
        ('1.25 meters', models.BAND_222),
        ('222', models.BAND_222),
        ('160 meters', models.BAND_160M),
        ('160m', models.BAND_160M),
        ('80 meters', models.BAND_80M),
        ('40 meters', models.BAND_40M),
        ('30 meters', models.BAND_30M),
        ('20 meters', models.BAND_20M),
        ('17 meters', models.BAND_17M),
        ('15 meters', models.BAND_15M),
        ('12 meters', models.BAND_12M),
        ('10 meters', models.BAND_10M),
        ('6 meter', models.BAND_6M),
        ('6m', models.BAND_6M),
        ('33 centimeters', models.BAND_33CM),
        ('23 centimeters', models.BAND_23CM),
        ('13 centimeters', models.BAND_13CM),
    )
    @ddt.unpack
    def test_alias_normalizes_to_canonical(self, alias, expected):
        self.assertEqual(expected, bands.normalize_band(alias))

    def test_unrecognized_band_passes_through_unchanged(self):
        # Never silently dropped/blanked -- see bands.normalize_band's
        # own docstring for why: an unrecognized explicit band must
        # fail validation, not disappear into "no restriction".
        self.assertEqual('not-a-real-band',
                         bands.normalize_band('not-a-real-band'))

    def test_empty_or_none_passes_through(self):
        self.assertEqual('', bands.normalize_band(''))
        self.assertIsNone(bands.normalize_band(None))

    @ddt.data(
        ('repeater', models.RECORD_TYPE_REPEATER),
        ('repeaters', models.RECORD_TYPE_REPEATER),
        ('REPEATER', models.RECORD_TYPE_REPEATER),
        ('simplex', models.RECORD_TYPE_SIMPLEX),
        ('simplex channels', models.RECORD_TYPE_SIMPLEX),
    )
    @ddt.unpack
    def test_record_type_alias_normalizes(self, alias, expected):
        self.assertEqual(expected, bands.normalize_record_type(alias))

    def test_unrecognized_record_type_passes_through_unchanged(self):
        self.assertEqual('not-a-real-type',
                         bands.normalize_record_type('not-a-real-type'))


class UnsupportedButClassifiableCategoryTest(unittest.TestCase):
    """A band may be recognized/classifiable even though no external
    discovery source currently returns data for it -- distinct from
    an unrecognized band (which fails validation)."""

    def test_hf_band_normalizes_and_classifies_with_no_discovery_source(
            self):
        # 20 meters has no RepeaterBook-style discovery source in this
        # release (RepeaterBook only covers ham VHF/UHF repeaters and
        # GMRS), but the band itself is still a real, recognized,
        # classifiable entry in the registry.
        self.assertEqual(models.BAND_20M, bands.normalize_band('20 meters'))
        lo, hi = bands.BAND_FREQ_RANGES_HZ[models.BAND_20M]
        from chirp.assistant import sources
        candidate = models.ChannelCandidate(
            source='t', service=models.SERVICE_HAM, group='',
            label='HF', freq=(lo + hi) // 2)
        req = models.ProgrammingRequest(requested_bands=(models.BAND_20M,))
        self.assertTrue(
            sources._matches_requested_constraints(candidate, req))


if __name__ == '__main__':
    unittest.main()
