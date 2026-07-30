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

"""The one authoritative amateur band registry for the Programming
Assistant: canonical identifiers (chirp.assistant.models.BAND_*),
their frequency ranges, and human-language alias normalization.

BAND_FREQ_RANGES_HZ is derived from chirp.bandplan_na -- the same
region's band-plan data CHIRP's own memory editor already uses for
automatic repeater-offset suggestions -- rather than a second,
independently maintained copy of the same numbers. Every
chirp.bandplan_na.BANDS_* tuple's first entry is that band's own
overall span (confirmed by inspection: "160 Meter Band", "2 Meter
Band", "70 Centimeter Band", ...); every other entry in each tuple is
a sub-allocation within it, which this module has no need for.

This is the *only* place band ranges are defined for the assistant;
chirp.assistant.sources, the AI system prompt, and any later Review/
Apply-layer check must all import from here rather than hard-coding
their own copies (section 6 of the corrective task this module was
written for).
"""

import re

from chirp import bandplan_na
from chirp.assistant import models

#: canonical band id -> (lo_hz, hi_hz), taken directly from
#: chirp.bandplan_na's own authoritative band-plan data.
BAND_FREQ_RANGES_HZ = {
    models.BAND_160M: bandplan_na.BANDS_160M[0].limits,
    models.BAND_80M: bandplan_na.BANDS_80M[0].limits,
    models.BAND_40M: bandplan_na.BANDS_40M[0].limits,
    models.BAND_30M: bandplan_na.BANDS_30M[0].limits,
    models.BAND_20M: bandplan_na.BANDS_20M[0].limits,
    models.BAND_17M: bandplan_na.BANDS_17M[0].limits,
    models.BAND_15M: bandplan_na.BANDS_15M[0].limits,
    models.BAND_12M: bandplan_na.BANDS_12M[0].limits,
    models.BAND_10M: bandplan_na.BANDS_10M[0].limits,
    models.BAND_6M: bandplan_na.BANDS_6M[0].limits,
    models.BAND_2M: bandplan_na.BANDS_2M[0].limits,
    models.BAND_222: bandplan_na.BANDS_1_25M[0].limits,
    models.BAND_70CM: bandplan_na.BANDS_70CM[0].limits,
    models.BAND_33CM: bandplan_na.BANDS_33CM[0].limits,
    models.BAND_23CM: bandplan_na.BANDS_23CM[0].limits,
    models.BAND_13CM: bandplan_na.BANDS_13CM[0].limits,
}

#: canonical band id -> human-readable display name.
BAND_DISPLAY_NAMES = {
    models.BAND_160M: '160 meters',
    models.BAND_80M: '80 meters',
    models.BAND_40M: '40 meters',
    models.BAND_30M: '30 meters',
    models.BAND_20M: '20 meters',
    models.BAND_17M: '17 meters',
    models.BAND_15M: '15 meters',
    models.BAND_12M: '12 meters',
    models.BAND_10M: '10 meters',
    models.BAND_6M: '6 meters',
    models.BAND_2M: '2 meters',
    models.BAND_222: '1.25 meters (222 MHz)',
    models.BAND_70CM: '70 centimeters',
    models.BAND_33CM: '33 centimeters',
    models.BAND_23CM: '23 centimeters',
    models.BAND_13CM: '13 centimeters',
}

#: canonical band id -> every additional recognized human-language
#: spelling. The canonical id itself, and its display name, are
#: always recognized too (see _build_alias_lookup below) -- listed
#: again here only where the spelling actually differs from both.
_BAND_ALIASES = {
    models.BAND_160M: ('160 meter', '160 meters', '160m'),
    models.BAND_80M: ('80 meter', '80 meters', '80m'),
    models.BAND_40M: ('40 meter', '40 meters', '40m'),
    models.BAND_30M: ('30 meter', '30 meters', '30m'),
    models.BAND_20M: ('20 meter', '20 meters', '20m'),
    models.BAND_17M: ('17 meter', '17 meters', '17m'),
    models.BAND_15M: ('15 meter', '15 meters', '15m'),
    models.BAND_12M: ('12 meter', '12 meters', '12m'),
    models.BAND_10M: ('10 meter', '10 meters', '10m'),
    models.BAND_6M: ('6 meter', '6 meters', '6m'),
    models.BAND_2M: (
        '2 meter', '2 meters', '2m', 'two meter', 'two meters',
    ),
    models.BAND_222: (
        '1.25 meter', '1.25 meters', '1.25m', '222', '222mhz', '222 mhz',
        '222 band', 'one and a quarter meter', 'one and a quarter meters',
    ),
    models.BAND_70CM: (
        '70 centimeter', '70 centimeters', '70cm', '70 cm', '440',
        '440mhz', '440 mhz', '440 band', 'seventy centimeter',
        'seventy centimeters',
    ),
    models.BAND_33CM: ('33 centimeter', '33 centimeters', '33cm', '33 cm'),
    models.BAND_23CM: ('23 centimeter', '23 centimeters', '23cm', '23 cm'),
    models.BAND_13CM: ('13 centimeter', '13 centimeters', '13cm', '13 cm'),
}

_RECORD_TYPE_ALIASES = {
    models.RECORD_TYPE_REPEATER: ('repeaters', 'repeater channel',
                                  'repeater channels'),
    models.RECORD_TYPE_SIMPLEX: ('simplex channel', 'simplex channels',
                                 'simplex frequencies'),
}


def _normalize_token(text):
    """Lowercase, and collapse anything that isn't a letter or digit
    to a single space, so "70cm", "70 cm", "70-CM", and "70_cm" all
    normalize identically."""
    return re.sub(r'[^a-z0-9]+', ' ', text.lower()).strip()


def _build_lookup(canonical_values, display_names, aliases):
    lookup = {}
    for value in canonical_values:
        lookup[_normalize_token(value)] = value
        name = display_names.get(value)
        if name:
            lookup[_normalize_token(name)] = value
        for alias in aliases.get(value, ()):
            lookup[_normalize_token(alias)] = value
    return lookup


_BAND_LOOKUP = _build_lookup(
    models.ALL_BANDS, BAND_DISPLAY_NAMES, _BAND_ALIASES)
_RECORD_TYPE_LOOKUP = _build_lookup(
    models.ALL_RECORD_TYPES, {}, _RECORD_TYPE_ALIASES)


def normalize_band(raw):
    """Return the canonical chirp.assistant.models.BAND_* identifier
    @raw (any case/spacing/punctuation variant of a canonical id, its
    display name, or a known alias) refers to, or @raw itself,
    unchanged, if it isn't recognized.

    Deliberately never returns None for a non-empty @raw: an
    unrecognized explicit band must fail
    chirp.assistant.models.ProgrammingRequest.validate()'s existing
    "Unknown requested band(s)" check, not silently disappear into an
    empty (== unrestricted) requested_bands tuple. Broadening a
    request the user explicitly narrowed would be worse than
    rejecting it outright.
    """
    if not raw:
        return raw
    return _BAND_LOOKUP.get(_normalize_token(raw), raw)


def normalize_record_type(raw):
    """Same contract as normalize_band(), for chirp.assistant.models.
    RECORD_TYPE_* identifiers."""
    if not raw:
        return raw
    return _RECORD_TYPE_LOOKUP.get(_normalize_token(raw), raw)


def band_ranges_hz(band_ids):
    """The (lo_hz, hi_hz) ranges for every recognized id in
    @band_ids, silently dropping any id that isn't a real canonical
    band (defensive only -- every id reaching here should already
    have passed ProgrammingRequest.validate())."""
    return [BAND_FREQ_RANGES_HZ[b] for b in band_ids
            if b in BAND_FREQ_RANGES_HZ]
