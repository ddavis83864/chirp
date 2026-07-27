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

"""Typed, JSON-serializable domain models for the Programming Assistant.

ProgrammingRequest.validate() is the single schema gate used both by the
deterministic wizard (after the user confirms structured fields) and by
providers.py (after an AI provider extracts structured fields from
natural language) -- there is exactly one place that decides whether a
request is well-formed, regardless of where its fields came from.
"""

import dataclasses
import time

# --- enums (plain string constants, not enum.Enum, so they serialize to
# plain JSON without a custom encoder and compare naturally in tests) ---

LICENSE_NONE = 'none'
LICENSE_TECHNICIAN = 'technician'
LICENSE_GENERAL = 'general'
LICENSE_EXTRA = 'extra'
AMATEUR_LICENSES = (LICENSE_NONE, LICENSE_TECHNICIAN, LICENSE_GENERAL,
                    LICENSE_EXTRA)

SERVICE_HAM = 'ham'
SERVICE_GMRS = 'gmrs'
SERVICE_FRS = 'frs'
SERVICE_MURS = 'murs'
SERVICE_WEATHER = 'weather'
SERVICE_AVIATION = 'aviation'
SERVICE_MARINE = 'marine'
SERVICE_PUBLIC_SAFETY = 'public_safety'
SERVICE_BUSINESS = 'business'
SERVICE_RAILROAD = 'railroad'
SERVICE_SATELLITE = 'satellite'
ALL_SERVICES = (
    SERVICE_HAM, SERVICE_GMRS, SERVICE_FRS, SERVICE_MURS, SERVICE_WEATHER,
    SERVICE_AVIATION, SERVICE_MARINE, SERVICE_PUBLIC_SAFETY,
    SERVICE_BUSINESS, SERVICE_RAILROAD, SERVICE_SATELLITE,
)
# Services this release always treats as receive-only regardless of what
# the user requests -- see policies.py for why each one is here.
ALWAYS_RECEIVE_ONLY_SERVICES = (
    SERVICE_WEATHER, SERVICE_AVIATION, SERVICE_MARINE,
    SERVICE_PUBLIC_SAFETY, SERVICE_BUSINESS, SERVICE_RAILROAD,
)

NAMING_SHORT = 'short'
NAMING_DESCRIPTIVE = 'descriptive'
NAMING_STYLES = (NAMING_SHORT, NAMING_DESCRIPTIVE)

STATUS_READY = 'ready'
STATUS_ADJUSTED = 'adjusted'
STATUS_WARNING = 'warning'
STATUS_BLOCKED = 'blocked'
STATUS_RECEIVE_ONLY = 'receive_only'
STATUS_DUPLICATE = 'duplicate'
STATUS_EXISTING_CONFLICT = 'existing_conflict'
STATUS_SOURCE_UNAVAILABLE = 'source_unavailable'
STATUS_UNSUPPORTED_BY_RADIO = 'unsupported_by_radio'

CONFIDENCE_HIGH = 'high'
CONFIDENCE_MEDIUM = 'medium'
CONFIDENCE_LOW = 'low'
CONFIDENCE_LEVELS = (CONFIDENCE_HIGH, CONFIDENCE_MEDIUM, CONFIDENCE_LOW)

MAX_RADIUS_MILES = 500
MAX_CHANNEL_LIMIT = 500
MIN_CHANNEL_LIMIT = 1


class RequestValidationError(ValueError):
    pass


@dataclasses.dataclass
class ProgrammingRequest:
    """The single structured shape both the deterministic wizard and an
    AI provider's extracted output must conform to. Never carries a
    frequency, tone, or any other technical channel fact -- those only
    ever come from chirp.assistant.sources."""

    location_text: str = ''
    latitude: float | None = None
    longitude: float | None = None
    radius_miles: float = 25.0
    amateur_license: str = LICENSE_NONE
    has_gmrs_license: bool = False
    activities: tuple = ()
    requested_services: tuple = ()
    receive_only_services: tuple = ()
    channel_limit: int = 40
    preserve_existing: bool = True
    allow_duplicate_replacement: bool = False
    allow_reordering: bool = False
    naming_style: str = NAMING_SHORT
    protected_memory_ranges: tuple = ()
    requested_start_memory: int | None = None
    requested_end_memory: int | None = None
    # Privacy: sharing precise coordinates (vs. a rounded/approximate
    # location) with any external source/provider requires this to be
    # explicitly True. Default is the privacy-conscious False.
    share_precise_location: bool = False
    notes: str = ''

    def validate(self):
        """Return a list of human-readable error strings; empty means
        the request is well-formed. Never raises -- callers decide
        whether to surface errors or block on them."""
        errors = []

        if self.amateur_license not in AMATEUR_LICENSES:
            errors.append('Unknown amateur license class: %r' %
                          self.amateur_license)

        unknown_services = set(self.requested_services) - set(ALL_SERVICES)
        if unknown_services:
            errors.append('Unknown requested service(s): %s' %
                          ', '.join(sorted(unknown_services)))

        unknown_rx_services = (set(self.receive_only_services) -
                               set(ALL_SERVICES))
        if unknown_rx_services:
            errors.append('Unknown receive-only service(s): %s' %
                          ', '.join(sorted(unknown_rx_services)))

        if not isinstance(self.radius_miles, (int, float)):
            errors.append('radius_miles must be a number')
        elif not (0 < self.radius_miles <= MAX_RADIUS_MILES):
            errors.append('radius_miles must be between 0 and %i' %
                          MAX_RADIUS_MILES)

        if not isinstance(self.channel_limit, int):
            errors.append('channel_limit must be an integer')
        elif not (MIN_CHANNEL_LIMIT <= self.channel_limit <=
                  MAX_CHANNEL_LIMIT):
            errors.append('channel_limit must be between %i and %i' % (
                MIN_CHANNEL_LIMIT, MAX_CHANNEL_LIMIT))

        if self.naming_style not in NAMING_STYLES:
            errors.append('Unknown naming_style: %r' % self.naming_style)

        if self.latitude is not None and not (-90 <= self.latitude <= 90):
            errors.append('latitude out of range')
        if self.longitude is not None and not (-180 <= self.longitude <= 180):
            errors.append('longitude out of range')

        for lo, hi in self.protected_memory_ranges:
            if lo > hi:
                errors.append('Invalid protected range (%r, %r)' % (lo, hi))

        if (self.requested_start_memory is not None and
                self.requested_end_memory is not None and
                self.requested_start_memory > self.requested_end_memory):
            errors.append('requested_start_memory is after '
                          'requested_end_memory')

        return errors

    @property
    def is_valid(self):
        return not self.validate()

    def to_dict(self):
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, data):
        """Build a request from a plain dict, ignoring unknown keys and
        falling back to defaults for anything missing/malformed. Callers
        (especially providers.py, handling untrusted AI output) MUST
        still call validate() on the result before using it."""
        if not isinstance(data, dict):
            return cls()
        known = {f.name for f in dataclasses.fields(cls)}
        kwargs = {}
        for key in known:
            if key not in data:
                continue
            value = data[key]
            if key in ('activities', 'requested_services',
                       'receive_only_services'):
                if isinstance(value, (list, tuple)):
                    kwargs[key] = tuple(str(v) for v in value)
            elif key == 'protected_memory_ranges':
                if isinstance(value, (list, tuple)):
                    try:
                        kwargs[key] = tuple(
                            (int(a), int(b)) for a, b in value)
                    except (TypeError, ValueError):
                        pass
            elif key in ('latitude', 'longitude', 'radius_miles'):
                if isinstance(value, (int, float)):
                    kwargs[key] = float(value)
            elif key in ('channel_limit', 'requested_start_memory',
                         'requested_end_memory'):
                if isinstance(value, int) and not isinstance(value, bool):
                    kwargs[key] = value
            elif key in ('has_gmrs_license', 'preserve_existing',
                         'allow_duplicate_replacement', 'allow_reordering',
                         'share_precise_location'):
                if isinstance(value, bool):
                    kwargs[key] = value
            elif key in ('location_text', 'amateur_license', 'naming_style',
                         'notes'):
                if isinstance(value, str):
                    kwargs[key] = value
        return cls(**kwargs)


@dataclasses.dataclass
class ChannelProvenance:
    """Where each field of a candidate came from, for the "confidence /
    provenance" preview column and the audit trail. Every candidate has
    exactly one of these."""

    source_name: str = ''
    source_record_id: str = ''
    retrieved_at: float | None = None
    source_record_age_days: float | None = None
    fields_from_source: tuple = ()
    fields_from_deterministic_logic: tuple = ()
    fields_from_ai: tuple = ()
    fields_adjusted_by_conversion: tuple = ()

    @classmethod
    def now(cls, source_name, **kwargs):
        return cls(source_name=source_name, retrieved_at=time.time(),
                   **kwargs)

    def to_dict(self):
        return dataclasses.asdict(self)


@dataclasses.dataclass
class ChannelCandidate:
    """One proposed memory, before/after conversion+validation for a
    specific destination radio. Frequencies are integer Hz."""

    source: str
    service: str
    group: str
    label: str
    freq: int
    source_record_id: str = ''
    name: str = ''
    tx_freq: int | None = None
    mode: str = 'FM'
    tmode: str = ''
    rtone: float = 88.5
    ctone: float = 88.5
    dtcs: int = 23
    rx_dtcs: int = 23
    dtcs_polarity: str = 'NN'
    tuning_step: float = 5.0
    power: float | None = None
    receive_only: bool = False
    reason: str = ''
    distance_miles: float | None = None
    confidence: str = CONFIDENCE_HIGH
    provenance: ChannelProvenance = dataclasses.field(
        default_factory=ChannelProvenance)

    # Populated by the planner/converter/validator pipeline, not by a
    # source adapter.
    memory_number: int | None = None
    include: bool = True
    status: str = STATUS_READY
    warnings: tuple = ()
    errors: tuple = ()
    adjustments: tuple = ()

    def dedup_key(self):
        """Fields that make two candidates "the same channel" for
        deduplication -- deliberately more than just the receive
        frequency, since two repeaters can share an output frequency
        without being the same repeater (see planner.py)."""
        return (self.freq, self.tx_freq, self.mode, self.tmode,
                round(self.rtone, 1), round(self.ctone, 1), self.dtcs,
                self.service)


@dataclasses.dataclass
class PlanGroup:
    name: str
    candidates: list = dataclasses.field(default_factory=list)


@dataclasses.dataclass
class PlanWarning:
    severity: str  # 'info' | 'warning' | 'error'
    message: str
    source_record_id: str = ''


@dataclasses.dataclass
class ChannelPlan:
    request: ProgrammingRequest | None = None
    groups: list = dataclasses.field(default_factory=list)
    warnings: list = dataclasses.field(default_factory=list)
    skipped_sources: list = dataclasses.field(default_factory=list)
    capacity_limited: bool = False

    @property
    def all_candidates(self):
        result = []
        for group in self.groups:
            result.extend(group.candidates)
        return result

    def counts(self):
        """Return a dict of status -> count over all candidates,
        restricted to include=True (what would actually be applied)."""
        counts = {}
        for c in self.all_candidates:
            if not c.include:
                continue
            counts[c.status] = counts.get(c.status, 0) + 1
        return counts


@dataclasses.dataclass
class ServiceAuthorization:
    """The result of policies.resolve_transmit_eligibility() for one
    candidate -- kept as a distinct, inspectable object rather than a
    bare bool so the preview can explain *why*."""

    service: str
    radio_can_receive: bool
    radio_can_transmit: bool
    user_declares_authorization: bool
    service_policy_allows_transmit: bool
    destination_supports_rx_only: bool
    reason: str = ''

    @property
    def transmit_enabled(self):
        return (self.radio_can_transmit and
                self.user_declares_authorization and
                self.service_policy_allows_transmit)
