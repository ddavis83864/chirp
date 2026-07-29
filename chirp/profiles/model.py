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

"""The radio-neutral canonical profile domain model.

None of this module depends on wxPython or a physical/simulated radio --
it is plain dataclasses plus pure functions, so it can be unit tested in
isolation (see tests/unit/test_profiles_model.py).

A profile channel's identity is its `logical_id`, never a memory number.
Memory numbers are radio-specific placement details decided later by
chirp.profiles.placement, not stored as identity here.
"""

import dataclasses
import datetime
import uuid

from chirp.profiles import schema


def _now_iso():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def new_profile_id():
    return str(uuid.uuid4())


@dataclasses.dataclass
class TransmitBehavior:
    """How (and whether) a channel may transmit.

    `mode` is the safety-critical field: TRANSMIT_RECEIVE_ONLY must never
    be silently changed to TRANSMIT_ENABLED by adaptation, overrides, or
    placement (see chirp.profiles.safety). `duplex`/`offset_hz`/
    `tx_freq_hz` describe the *shape* of a transmit-capable channel and
    are meaningless when mode != TRANSMIT_ENABLED.
    """
    mode: str = schema.TRANSMIT_UNSPECIFIED
    duplex: str = schema.DUPLEX_NONE
    offset_hz: int = 0
    tx_freq_hz: int | None = None

    @property
    def receive_only(self):
        return self.mode == schema.TRANSMIT_RECEIVE_ONLY

    def to_dict(self):
        d = {'mode': self.mode, 'duplex': self.duplex,
             'offset_hz': self.offset_hz}
        if self.tx_freq_hz is not None:
            d['tx_freq_hz'] = self.tx_freq_hz
        return d

    @classmethod
    def from_dict(cls, data):
        return cls(mode=data.get('mode', schema.TRANSMIT_UNSPECIFIED),
                   duplex=data.get('duplex', schema.DUPLEX_NONE),
                   offset_hz=data.get('offset_hz', 0),
                   tx_freq_hz=data.get('tx_freq_hz'))


@dataclasses.dataclass
class PowerPreference:
    """A portable power preference.

    `tier` is the primary portable representation (ordinal, radio
    families rarely share absolute levels). `watts` is an optional hint
    the adaptation engine may use to pick between two levels within a
    tier if the target exposes wattage-labeled levels.
    """
    tier: str | None = None
    watts: float | None = None

    def to_dict(self):
        d = {}
        if self.tier is not None:
            d['tier'] = self.tier
        if self.watts is not None:
            d['watts'] = self.watts
        return d

    @classmethod
    def from_dict(cls, data):
        if not data:
            return cls()
        return cls(tier=data.get('tier'), watts=data.get('watts'))


@dataclasses.dataclass
class TargetSelector:
    scope: str
    value: str

    def to_dict(self):
        return {'scope': self.scope, 'value': self.value}

    @classmethod
    def from_dict(cls, data):
        return cls(scope=data.get('scope', ''), value=data.get('value', ''))


@dataclasses.dataclass
class TargetOverride:
    """A radio-specific adaptation, kept separate from the canonical
    channel definition (section 4.6). `fields` may only contain keys in
    schema.ALLOWED_OVERRIDE_FIELDS -- notably, transmit permission is not
    a legal override key, so an override can never re-enable transmit on
    a receive-only channel.
    """
    selector: TargetSelector
    fields: dict = dataclasses.field(default_factory=dict)

    def to_dict(self):
        return {'selector': self.selector.to_dict(),
                'fields': dict(self.fields)}

    @classmethod
    def from_dict(cls, data):
        return cls(
            selector=TargetSelector.from_dict(data.get('selector') or {}),
            fields=dict(data.get('fields') or {}))


@dataclasses.dataclass
class LogicalGroup:
    id: str
    name: str
    description: str = ''

    def to_dict(self):
        return {'id': self.id, 'name': self.name,
                'description': self.description}

    @classmethod
    def from_dict(cls, data):
        return cls(id=data.get('id', ''), name=data.get('name', ''),
                   description=data.get('description', ''))


@dataclasses.dataclass
class ProfileDefaults:
    power_preference: PowerPreference = dataclasses.field(
        default_factory=PowerPreference)
    scan_intent: str | None = None
    mode: str | None = None
    region: str | None = None
    naming_style: str = schema.NAMING_STYLE_ABBREVIATE
    duplicate_policy: str = schema.DUPLICATE_POLICY_PROMPT

    def to_dict(self):
        return {
            'power_preference': self.power_preference.to_dict(),
            'scan_intent': self.scan_intent,
            'mode': self.mode,
            'region': self.region,
            'naming_style': self.naming_style,
            'duplicate_policy': self.duplicate_policy,
        }

    @classmethod
    def from_dict(cls, data):
        data = data or {}
        return cls(
            power_preference=PowerPreference.from_dict(
                data.get('power_preference')),
            scan_intent=data.get('scan_intent'),
            mode=data.get('mode'),
            region=data.get('region'),
            naming_style=data.get('naming_style',
                                  schema.NAMING_STYLE_ABBREVIATE),
            duplicate_policy=data.get('duplicate_policy',
                                      schema.DUPLICATE_POLICY_PROMPT),
        )


@dataclasses.dataclass
class ProfileChannel:
    logical_id: str
    name: str = ''
    comment: str = ''
    rx_freq_hz: int = 0
    transmit: TransmitBehavior = dataclasses.field(
        default_factory=TransmitBehavior)
    tone_mode: str = ''
    rtone: float = 88.5
    ctone: float = 88.5
    dtcs: int = 23
    rx_dtcs: int = 23
    dtcs_polarity: str = 'NN'
    cross_mode: str = 'Tone->Tone'
    mode: str | None = None
    power_preference: PowerPreference = dataclasses.field(
        default_factory=PowerPreference)
    scan_intent: str | None = None
    priority: int | None = None
    category: str | None = None
    groups: tuple = ()
    tags: tuple = ()
    source: dict = dataclasses.field(default_factory=dict)
    overrides: tuple = ()

    @property
    def receive_only(self):
        return self.transmit.receive_only

    def to_dict(self):
        return {
            'logical_id': self.logical_id,
            'name': self.name,
            'comment': self.comment,
            'rx_freq_hz': self.rx_freq_hz,
            'transmit': self.transmit.to_dict(),
            'tone_mode': self.tone_mode,
            'rtone': self.rtone,
            'ctone': self.ctone,
            'dtcs': self.dtcs,
            'rx_dtcs': self.rx_dtcs,
            'dtcs_polarity': self.dtcs_polarity,
            'cross_mode': self.cross_mode,
            'mode': self.mode,
            'power_preference': self.power_preference.to_dict(),
            'scan_intent': self.scan_intent,
            'priority': self.priority,
            'category': self.category,
            'groups': list(self.groups),
            'tags': list(self.tags),
            'source': dict(self.source),
            'overrides': [o.to_dict() for o in self.overrides],
        }

    @classmethod
    def from_dict(cls, data):
        return cls(
            logical_id=data.get('logical_id', ''),
            name=data.get('name', ''),
            comment=data.get('comment', ''),
            rx_freq_hz=data.get('rx_freq_hz', 0),
            transmit=TransmitBehavior.from_dict(data.get('transmit') or {}),
            tone_mode=data.get('tone_mode', ''),
            rtone=data.get('rtone', 88.5),
            ctone=data.get('ctone', 88.5),
            dtcs=data.get('dtcs', 23),
            rx_dtcs=data.get('rx_dtcs', 23),
            dtcs_polarity=data.get('dtcs_polarity', 'NN'),
            cross_mode=data.get('cross_mode', 'Tone->Tone'),
            mode=data.get('mode'),
            power_preference=PowerPreference.from_dict(
                data.get('power_preference')),
            scan_intent=data.get('scan_intent'),
            priority=data.get('priority'),
            category=data.get('category'),
            groups=tuple(data.get('groups') or ()),
            tags=tuple(data.get('tags') or ()),
            source=dict(data.get('source') or {}),
            overrides=tuple(TargetOverride.from_dict(o)
                            for o in (data.get('overrides') or ())),
        )


@dataclasses.dataclass
class Profile:
    profile_id: str = dataclasses.field(default_factory=new_profile_id)
    name: str = ''
    description: str = ''
    region: str | None = None
    schema_version: str = schema.SCHEMA_VERSION
    created_at: str = dataclasses.field(default_factory=_now_iso)
    modified_at: str = dataclasses.field(default_factory=_now_iso)
    defaults: ProfileDefaults = dataclasses.field(
        default_factory=ProfileDefaults)
    groups: dict = dataclasses.field(default_factory=dict)
    channels: list = dataclasses.field(default_factory=list)

    def touch(self):
        """Update modified_at. Does not change profile_id."""
        self.modified_at = _now_iso()

    def rename(self, new_name):
        """Rename the profile. profile_id is stable across renames."""
        self.name = new_name
        self.touch()

    def get_channel(self, logical_id):
        for ch in self.channels:
            if ch.logical_id == logical_id:
                return ch
        return None

    def add_channel(self, channel):
        self.channels.append(channel)
        self.touch()

    def remove_channel(self, logical_id):
        before = len(self.channels)
        self.channels = [c for c in self.channels
                         if c.logical_id != logical_id]
        if len(self.channels) != before:
            self.touch()

    def to_dict(self):
        return {
            'schema_version': self.schema_version,
            'profile_id': self.profile_id,
            'name': self.name,
            'description': self.description,
            'region': self.region,
            'created_at': self.created_at,
            'modified_at': self.modified_at,
            'defaults': self.defaults.to_dict(),
            'groups': [g.to_dict() for g in self.groups.values()],
            'channels': [c.to_dict() for c in self.channels],
        }

    @classmethod
    def from_dict(cls, data):
        groups = {}
        for gdata in (data.get('groups') or ()):
            g = LogicalGroup.from_dict(gdata)
            groups[g.id] = g
        return cls(
            schema_version=data.get('schema_version', schema.SCHEMA_VERSION),
            profile_id=data.get('profile_id') or new_profile_id(),
            name=data.get('name', ''),
            description=data.get('description', ''),
            region=data.get('region'),
            created_at=data.get('created_at') or _now_iso(),
            modified_at=data.get('modified_at') or _now_iso(),
            defaults=ProfileDefaults.from_dict(data.get('defaults')),
            groups=groups,
            channels=[
                ProfileChannel.from_dict(c)
                for c in (data.get('channels') or [])
            ],
        )


class ResolvedChannel:
    """Read-only view of a channel with profile defaults merged in.

    Pure function of (profile, channel) -- no hidden state, so the same
    inputs always resolve the same way (required for deterministic
    change-set generation).
    """

    def __init__(
            self, channel, mode, scan_intent, power_preference, region):
        self.channel = channel
        self.mode = mode
        self.scan_intent = scan_intent
        self.power_preference = power_preference
        self.region = region


def resolve_channel(profile, channel):
    """Merge @channel's explicit values with @profile.defaults for any
    field the channel leaves unset (None)."""
    defaults = profile.defaults
    power_preference = channel.power_preference
    if power_preference.tier is None and power_preference.watts is None:
        power_preference = defaults.power_preference
    if channel.scan_intent is not None:
        scan_intent = channel.scan_intent
    else:
        scan_intent = defaults.scan_intent
    return ResolvedChannel(
        channel=channel,
        mode=channel.mode if channel.mode is not None else defaults.mode,
        scan_intent=scan_intent,
        power_preference=power_preference,
        region=defaults.region,
    )
