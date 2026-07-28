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

"""Small helpers for building consistent chirp.assistant.models.
ChannelProvenance records and human-readable summaries of them for the
preview UI's provenance column.
"""

from chirp.assistant import models

_DAY_SECONDS = 86400


def from_source(source_name, source_record_id='', fetched_at=None,
                record_age_days=None, fields=()):
    """Provenance for a candidate that came directly from a trusted
    source adapter (network or static)."""
    return models.ChannelProvenance(
        source_name=source_name,
        source_record_id=source_record_id,
        retrieved_at=fetched_at,
        source_record_age_days=record_age_days,
        fields_from_source=tuple(fields),
    )


def note_deterministic_field(provenance, field_name):
    """Return a copy of @provenance with @field_name recorded as having
    been set by deterministic planner logic (e.g. an assigned memory
    number, a generated group name)."""
    if field_name in provenance.fields_from_deterministic_logic:
        return provenance
    provenance.fields_from_deterministic_logic = (
        provenance.fields_from_deterministic_logic + (field_name,))
    return provenance


def note_ai_field(provenance, field_name):
    """Return a copy of @provenance with @field_name recorded as
    AI-interpreted. Must never be called for a technical channel fact
    (frequency, tone, offset, mode, etc.) -- only for things like which
    categories of channel the user seemed interested in."""
    if field_name in provenance.fields_from_ai:
        return provenance
    provenance.fields_from_ai = provenance.fields_from_ai + (field_name,)
    return provenance


def note_conversion_adjustment(provenance, field_name):
    if field_name in provenance.fields_adjusted_by_conversion:
        return provenance
    provenance.fields_adjusted_by_conversion = (
        provenance.fields_adjusted_by_conversion + (field_name,))
    return provenance


def summarize(provenance):
    """A short, human-readable provenance string for the preview grid,
    e.g. "RepeaterBook, 12d old" or "Static table (weather)"."""
    parts = [provenance.source_name or 'unknown source']
    if provenance.source_record_age_days is not None:
        parts.append('%.0fd old' % provenance.source_record_age_days)
    if provenance.fields_adjusted_by_conversion:
        parts.append('adjusted: %s' % ', '.join(
            sorted(provenance.fields_adjusted_by_conversion)))
    return ', '.join(parts)
