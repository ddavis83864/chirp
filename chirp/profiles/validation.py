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

"""Structural and semantic validation for the profile domain model.

Unlike chirp.memcolors.profile (which silently drops malformed fields
and substitutes defaults), profile files are validated strictly: every
problem is collected as a chirp.profiles.schema.Issue with a field path,
and chirp.profiles.serialization raises ProfileValidationError listing
all of them rather than guessing at intent. Untrusted/hand-edited JSON
must fail loudly, not be silently reinterpreted.
"""

import datetime
import uuid

from chirp.profiles import errors
from chirp.profiles import schema


def parse_schema_version(raw):
    """Split a "major.minor" string into (major, minor) ints.

    Raises errors.ProfileSchemaVersionError if @raw isn't a string in
    that shape at all (this is checked before any other validation,
    since an unknown-shaped version string means we can't trust our
    assumptions about the rest of the document).
    """
    if not isinstance(raw, str) or raw.count('.') != 1:
        raise errors.ProfileSchemaVersionError(
            'Missing or malformed schema_version %r' % (raw,))
    major_s, minor_s = raw.split('.')
    if not (major_s.isdigit() and minor_s.isdigit()):
        raise errors.ProfileSchemaVersionError(
            'Malformed schema_version %r' % (raw,))
    return int(major_s), int(minor_s)


def check_schema_version(data):
    """Reject unknown schema *major* versions outright (section 4).

    A newer minor version from a future compatible release is allowed
    through (its unknown-to-us fields are simply not read), but a major
    version bump means the document shape may be incompatible.
    """
    major, _minor = parse_schema_version(data.get('schema_version'))
    if major != schema.SCHEMA_MAJOR:
        raise errors.ProfileSchemaVersionError(
            'Unsupported profile schema major version %d (this release '
            'supports major version %d)' % (major, schema.SCHEMA_MAJOR))


#: Top-level keys a loaded profile document must contain. Their *values*
#: may still be semantically invalid (caught by validate_profile); this
#: only guards against a document that is missing pieces entirely, e.g.
#: a hand-truncated file.
REQUIRED_ROOT_FIELDS = (
    'schema_version', 'profile_id', 'name', 'created_at', 'modified_at',
    'channels',
)


def check_required_root_fields(data):
    return [
        schema.Issue(field, 'Missing required field')
        for field in REQUIRED_ROOT_FIELDS if field not in data
    ]


def _valid_uuid(value):
    try:
        uuid.UUID(str(value))
        return True
    except (ValueError, AttributeError, TypeError):
        return False


def _valid_iso_timestamp(value):
    if not isinstance(value, str):
        return False
    try:
        datetime.datetime.fromisoformat(value)
        return True
    except ValueError:
        return False


def _valid_freq(value):
    # bool is an int subclass in Python; explicitly excluded so a
    # malformed `"rx_freq_hz": true` doesn't slip through as 1.
    return (isinstance(value, int) and not isinstance(value, bool) and
            value > 0)


def validate_defaults(defaults, path='defaults'):
    issues = []
    if defaults.naming_style not in schema.VALID_NAMING_STYLES:
        issues.append(schema.Issue(
            path + '.naming_style',
            'Invalid naming_style %r' % (defaults.naming_style,)))
    if defaults.duplicate_policy not in schema.VALID_DUPLICATE_POLICIES:
        issues.append(schema.Issue(
            path + '.duplicate_policy',
            'Invalid duplicate_policy %r' % (defaults.duplicate_policy,)))
    if (defaults.scan_intent is not None and
            defaults.scan_intent not in schema.VALID_SCAN_INTENTS):
        issues.append(schema.Issue(
            path + '.scan_intent',
            'Invalid scan_intent %r' % (defaults.scan_intent,)))
    if defaults.mode is not None and defaults.mode not in schema.VALID_MODES:
        issues.append(schema.Issue(
            path + '.mode', 'Invalid mode %r' % (defaults.mode,)))
    issues.extend(validate_power_preference(
        defaults.power_preference, path + '.power_preference'))
    return issues


def validate_power_preference(pref, path):
    issues = []
    if pref.tier is not None and pref.tier not in schema.VALID_POWER_TIERS:
        issues.append(schema.Issue(
            path + '.tier', 'Invalid power tier %r' % (pref.tier,)))
    if pref.watts is not None and not isinstance(pref.watts, (int, float)):
        issues.append(schema.Issue(
            path + '.watts', 'watts must be numeric, got %r' % (pref.watts,)))
    return issues


def validate_transmit(transmit, path):
    issues = []
    if transmit.mode not in schema.VALID_TRANSMIT_MODES:
        issues.append(schema.Issue(
            path + '.mode', 'Invalid transmit mode %r' % (transmit.mode,)))
    if transmit.duplex not in schema.VALID_DUPLEXES:
        issues.append(schema.Issue(
            path + '.duplex', 'Invalid duplex %r' % (transmit.duplex,)))
    if transmit.duplex == schema.DUPLEX_SPLIT and transmit.tx_freq_hz is None:
        issues.append(schema.Issue(
            path + '.tx_freq_hz',
            'split duplex requires an explicit tx_freq_hz'))
    if (transmit.tx_freq_hz is not None and
            not _valid_freq(transmit.tx_freq_hz)):
        issues.append(schema.Issue(
            path + '.tx_freq_hz',
            'Malformed frequency %r' % (transmit.tx_freq_hz,)))
    if not isinstance(transmit.offset_hz, int) or \
            isinstance(transmit.offset_hz, bool):
        issues.append(schema.Issue(
            path + '.offset_hz',
            'offset_hz must be an integer, got %r' % (transmit.offset_hz,)))
    return issues


def validate_override(override, path, known_group_ids):
    issues = []
    if override.selector.scope not in schema.SELECTOR_PRECEDENCE:
        issues.append(schema.Issue(
            path + '.selector.scope',
            'Invalid selector scope %r' % (override.selector.scope,)))
    if not override.selector.value:
        issues.append(schema.Issue(
            path + '.selector.value', 'Selector value must not be empty'))
    unknown = set(override.fields) - schema.ALLOWED_OVERRIDE_FIELDS
    if unknown:
        issues.append(schema.Issue(
            path + '.fields',
            'Override contains disallowed field(s) %s (transmit '
            'permission cannot be overridden)' % (sorted(unknown),)))
    if 'preferred_group' in override.fields and \
            override.fields['preferred_group'] not in known_group_ids:
        issues.append(schema.Issue(
            path + '.fields.preferred_group',
            'References unknown group %r' %
            (override.fields['preferred_group'],)))
    if 'scan_intent' in override.fields and \
            override.fields['scan_intent'] not in schema.VALID_SCAN_INTENTS:
        issues.append(schema.Issue(
            path + '.fields.scan_intent',
            'Invalid scan_intent %r' % (override.fields['scan_intent'],)))
    return issues


def validate_channel(channel, path, known_group_ids):
    issues = []
    if not schema.is_valid_logical_id(channel.logical_id):
        issues.append(schema.Issue(
            path + '.logical_id',
            'Invalid logical_id %r (must be lowercase slug: letters, '
            'digits, single hyphens)' % (channel.logical_id,)))
    if not _valid_freq(channel.rx_freq_hz):
        issues.append(schema.Issue(
            path + '.rx_freq_hz',
            'Malformed frequency %r (must be a positive integer number '
            'of Hz)' % (channel.rx_freq_hz,)))
    issues.extend(validate_transmit(channel.transmit, path + '.transmit'))
    if channel.tone_mode not in schema.VALID_TONE_MODES:
        issues.append(schema.Issue(
            path + '.tone_mode',
            'Invalid tone_mode %r' % (channel.tone_mode,)))
    if channel.tone_mode == 'Cross' and \
            channel.cross_mode not in schema.VALID_CROSS_MODES:
        issues.append(schema.Issue(
            path + '.cross_mode',
            'Invalid cross_mode %r' % (channel.cross_mode,)))
    if channel.dtcs_polarity not in schema.VALID_DTCS_POLARITIES:
        issues.append(schema.Issue(
            path + '.dtcs_polarity',
            'Invalid dtcs_polarity %r' % (channel.dtcs_polarity,)))
    if channel.dtcs not in schema.VALID_DTCS_CODES:
        issues.append(schema.Issue(
            path + '.dtcs', 'Invalid DTCS code %r' % (channel.dtcs,)))
    if channel.rx_dtcs not in schema.VALID_DTCS_CODES:
        issues.append(schema.Issue(
            path + '.rx_dtcs', 'Invalid DTCS code %r' % (channel.rx_dtcs,)))
    if channel.mode is not None and channel.mode not in schema.VALID_MODES:
        issues.append(schema.Issue(
            path + '.mode', 'Invalid mode %r' % (channel.mode,)))
    if (channel.scan_intent is not None and
            channel.scan_intent not in schema.VALID_SCAN_INTENTS):
        issues.append(schema.Issue(
            path + '.scan_intent',
            'Invalid scan_intent %r' % (channel.scan_intent,)))
    issues.extend(validate_power_preference(
        channel.power_preference, path + '.power_preference'))
    for group_id in channel.groups:
        if group_id not in known_group_ids:
            issues.append(schema.Issue(
                path + '.groups', 'References unknown group %r' %
                (group_id,)))
    for i, override in enumerate(channel.overrides):
        issues.extend(validate_override(
            override, '%s.overrides[%d]' % (path, i), known_group_ids))
    return issues


def validate_profile(profile):
    """Return a list of schema.Issue describing every problem found.

    An empty list means the profile is structurally and semantically
    valid. This never raises for a well-formed Profile object; callers
    that want strict enforcement should use validate_profile_or_raise.
    """
    issues = []

    try:
        major, _minor = parse_schema_version(profile.schema_version)
        if major != schema.SCHEMA_MAJOR:
            issues.append(schema.Issue(
                'schema_version',
                'Unsupported major version %d' % major))
    except errors.ProfileSchemaVersionError as e:
        issues.append(schema.Issue('schema_version', str(e)))

    if not _valid_uuid(profile.profile_id):
        issues.append(schema.Issue(
            'profile_id', 'Invalid UUID %r' % (profile.profile_id,)))
    if not _valid_iso_timestamp(profile.created_at):
        issues.append(schema.Issue(
            'created_at',
            'Invalid ISO-8601 timestamp %r' % (profile.created_at,)))
    if not _valid_iso_timestamp(profile.modified_at):
        issues.append(schema.Issue(
            'modified_at',
            'Invalid ISO-8601 timestamp %r' % (profile.modified_at,)))

    known_group_ids = set(profile.groups)
    for group_id, group in profile.groups.items():
        if group_id != group.id:
            issues.append(schema.Issue(
                'groups[%r]' % (group_id,),
                'Group dict key does not match group.id %r' % (group.id,)))
        if not schema.is_valid_logical_id(group.id):
            issues.append(schema.Issue(
                'groups[%r].id' % (group_id,),
                'Invalid group id %r' % (group.id,)))

    issues.extend(validate_defaults(profile.defaults))

    seen_ids = {}
    for i, channel in enumerate(profile.channels):
        path = 'channels[%d]' % i
        seen_ids.setdefault(channel.logical_id, []).append(i)
        issues.extend(validate_channel(channel, path, known_group_ids))

    for logical_id, indexes in seen_ids.items():
        if len(indexes) > 1:
            issues.append(schema.Issue(
                'channels', 'Duplicate logical_id %r at indexes %s' %
                (logical_id, indexes)))

    return issues


def validate_profile_or_raise(profile):
    issues = validate_profile(profile)
    if issues:
        raise errors.ProfileValidationError(issues)
    return profile
