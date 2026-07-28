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

"""Constants, enums, and the versioned wire schema for radio profiles.

This module intentionally re-uses value sets already defined by
chirp.chirp_common (modes, tone modes, DTCS codes/polarities) rather than
inventing a parallel vocabulary, since chirp_common is itself pure Python
and every driver already speaks in these terms.
"""

import re

from chirp import chirp_common

#: Schema version written by this release. Only the major component is
#: an enforced compatibility gate (see SCHEMA_MAJOR); the minor component
#: may grow across releases as optional fields are added.
SCHEMA_VERSION = '1.0'
SCHEMA_MAJOR = 1
SCHEMA_MINOR = 0

#: Recommended file extension for saved profiles (see wxui file dialogs).
FILE_EXTENSION = '.chirp-profile.json'

_LOGICAL_ID_RE = re.compile(r'^[a-z0-9]+(-[a-z0-9]+)*$')

#: A logical channel ID must be stable, portable across profiles/radios,
#: and safe to use as a dict key / filename component. Lowercase
#: slug-style (like the examples in the design doc:
#: "local-cda-2m-repeater-01") keeps it human-legible and diffable.
LOGICAL_ID_MAX_LEN = 128


def is_valid_logical_id(value):
    return (isinstance(value, str) and
            0 < len(value) <= LOGICAL_ID_MAX_LEN and
            bool(_LOGICAL_ID_RE.match(value)))


#: Transmit permission -- the safety-critical axis. This is deliberately
#: kept separate from, and cannot be overridden by, the shape of the
#: transmit offset (see model.TransmitBehavior).
TRANSMIT_ENABLED = 'enabled'
TRANSMIT_RECEIVE_ONLY = 'receive_only'
TRANSMIT_UNSPECIFIED = 'unspecified'
VALID_TRANSMIT_MODES = (TRANSMIT_ENABLED, TRANSMIT_RECEIVE_ONLY,
                        TRANSMIT_UNSPECIFIED)

#: Shape of the transmit frequency relative to the receive frequency.
#: Mirrors chirp_common.Memory.duplex ('', '+', '-', 'split') plus the
#: profile-domain notion that a receive-only channel simply has no
#: applicable shape.
DUPLEX_NONE = ''
DUPLEX_POSITIVE = '+'
DUPLEX_NEGATIVE = '-'
DUPLEX_SPLIT = 'split'
VALID_DUPLEXES = (DUPLEX_NONE, DUPLEX_POSITIVE, DUPLEX_NEGATIVE, DUPLEX_SPLIT)

VALID_MODES = tuple(chirp_common.MODES)
VALID_TONE_MODES = tuple(chirp_common.TONE_MODES)
VALID_CROSS_MODES = tuple(chirp_common.CROSS_MODES)
VALID_DTCS_POLARITIES = ('NN', 'RN', 'NR', 'RR')
VALID_DTCS_CODES = tuple(chirp_common.DTCS_CODES)

SCAN_INTENT_SCAN = 'scan'
SCAN_INTENT_SKIP = 'skip'
SCAN_INTENT_PRIORITY = 'priority'
VALID_SCAN_INTENTS = (SCAN_INTENT_SCAN, SCAN_INTENT_SKIP,
                      SCAN_INTENT_PRIORITY)

#: Maps a portable scan intent to the chirp_common Memory.skip value.
SCAN_INTENT_TO_SKIP = {
    SCAN_INTENT_SCAN: '',
    SCAN_INTENT_SKIP: 'S',
    SCAN_INTENT_PRIORITY: 'P',
}

#: Ordinal power tiers, highest to lowest. A tier (not an absolute dBm
#: value) is the canonical portable representation, since two radios
#: rarely share identical power levels; the adaptation engine maps a
#: tier to the nearest available RadioFeatures.valid_power_levels entry.
POWER_TIER_HIGHEST = 'highest'
POWER_TIER_HIGH = 'high'
POWER_TIER_MEDIUM = 'medium'
POWER_TIER_LOW = 'low'
POWER_TIER_LOWEST = 'lowest'
VALID_POWER_TIERS = (POWER_TIER_HIGHEST, POWER_TIER_HIGH,
                     POWER_TIER_MEDIUM, POWER_TIER_LOW, POWER_TIER_LOWEST)

#: Deterministic naming-style hints used by the adaptation engine when a
#: target radio's valid_name_length is shorter than a channel's name.
NAMING_STYLE_VERBATIM = 'verbatim'
NAMING_STYLE_ABBREVIATE = 'abbreviate'
VALID_NAMING_STYLES = (NAMING_STYLE_VERBATIM, NAMING_STYLE_ABBREVIATE)

#: What to do when a profile channel matches an existing target memory.
DUPLICATE_POLICY_UPDATE = 'update'
DUPLICATE_POLICY_SKIP = 'skip'
DUPLICATE_POLICY_PROMPT = 'prompt'
VALID_DUPLICATE_POLICIES = (DUPLICATE_POLICY_UPDATE, DUPLICATE_POLICY_SKIP,
                            DUPLICATE_POLICY_PROMPT)

#: Target-override selector scopes (section 4.6), in ascending precedence
#: order relative to each other (exact model outranks vendor family, etc).
#: The full documented precedence chain also includes base/overlay
#: composition layers; see composition.py.
SELECTOR_CAPABILITY_CLASS = 'capability_class'
SELECTOR_VENDOR_FAMILY = 'vendor_family'
SELECTOR_DRIVER = 'driver'
SELECTOR_MODEL = 'model'
SELECTOR_PRECEDENCE = (SELECTOR_CAPABILITY_CLASS, SELECTOR_VENDOR_FAMILY,
                       SELECTOR_DRIVER, SELECTOR_MODEL)

#: Fields a target-specific override is permitted to change. This is a
#: safety boundary as much as a schema: transmit permission
#: (receive-only) is deliberately NOT overridable here, so an override
#: can never re-enable transmit on a canonically receive-only channel
#: (see safety.py and section 9/4.6 of the design doc).
ALLOWED_OVERRIDE_FIELDS = frozenset({
    'name', 'power_preference', 'preferred_memory_range',
    'preferred_group', 'scan_intent',
})

#: Well-known logical group ids suggested by the design doc. Profiles
#: are free to define others; this is not an enum, just a convenience.
SUGGESTED_GROUPS = (
    'local-repeaters', 'simplex', 'weather', 'aviation', 'emergency',
)

#: Per-channel compatibility/adaptation outcome classifications
#: (section 8). Ordered least to most severe -- see adaptation.SEVERITY.
CLASS_EXACT = 'exact'
CLASS_ADAPTED = 'adapted'
CLASS_DEGRADED = 'degraded'
CLASS_INCOMPATIBLE = 'incompatible'
CLASS_UNSAFE = 'unsafe'
ALL_CLASSIFICATIONS = (CLASS_EXACT, CLASS_ADAPTED, CLASS_DEGRADED,
                       CLASS_INCOMPATIBLE, CLASS_UNSAFE)


class Issue:
    """One validation problem, with a JSON-pointer-ish field path.

    :param path: e.g. "channels[3].logical_id" or "defaults.mode"
    :param message: human-readable explanation
    """

    def __init__(self, path, message):
        self.path = path
        self.message = message

    def __str__(self):
        return '%s: %s' % (self.path, self.message)

    def __repr__(self):
        return 'Issue(%r, %r)' % (self.path, self.message)

    def __eq__(self, other):
        return (isinstance(other, Issue) and
                self.path == other.path and self.message == other.message)

    def __hash__(self):
        return hash((self.path, self.message))
