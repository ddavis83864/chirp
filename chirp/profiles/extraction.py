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

"""Builds a portable Profile from an already-open CHIRP image (section 6).

extract_profile() takes memories that are already loaded (the caller --
the wx controller in the first release -- is responsible for reading
them off the open Radio; this module never talks to a serial port or
blocks on I/O) and separates portable information (frequency, duplex,
tones, mode, name, scan/skip intent, power preference, receive-only
state, bank/group membership where determinable) from radio-specific
information (memory number, special-channel identifiers, driver-
specific settings/extra fields, immutable flags) -- the latter is kept
only as optional provenance in ProfileChannel.source, never as
canonical identity.
"""

import dataclasses
import re

from chirp import directory
from chirp.profiles import model
from chirp.profiles import schema

_SLUG_RE = re.compile(r'[^a-z0-9]+')

#: Memory.skip -> portable scan intent (inverse of
#: schema.SCAN_INTENT_TO_SKIP).
_SKIP_TO_SCAN_INTENT = {v: k for k, v in schema.SCAN_INTENT_TO_SKIP.items()}


def _slugify(text):
    return _SLUG_RE.sub('-', text.strip().lower()).strip('-')


def make_logical_id(memory, used_ids):
    """Generate a stable, unique, slug-format logical id for @memory.

    Deterministic given the same memory name/number and the same set of
    ids already used so far in this extraction: the memory's name is
    the basis (falling back to its memory number if unnamed or the name
    slugifies to nothing), disambiguated with a numeric suffix on
    collision. The *source* memory number is never used as identity
    beyond this one-time seed -- see module docstring.
    """
    base = _slugify(memory.name) if memory.name else ''
    if not base:
        base = 'channel-%s' % memory.number
    candidate = base
    suffix = 2
    while candidate in used_ids:
        candidate = '%s-%d' % (base, suffix)
        suffix += 1
    used_ids.add(candidate)
    return candidate


def _extract_transmit(memory):
    if memory.duplex == 'off':
        return model.TransmitBehavior(mode=schema.TRANSMIT_RECEIVE_ONLY)
    if memory.duplex in ('+', '-'):
        return model.TransmitBehavior(
            mode=schema.TRANSMIT_ENABLED, duplex=memory.duplex,
            offset_hz=memory.offset)
    if memory.duplex == 'split':
        return model.TransmitBehavior(
            mode=schema.TRANSMIT_ENABLED, duplex=schema.DUPLEX_SPLIT,
            tx_freq_hz=memory.offset)
    return model.TransmitBehavior(
        mode=schema.TRANSMIT_ENABLED, duplex=schema.DUPLEX_NONE)


def _extract_power(power, features):
    """Best-effort inverse of adaptation._adapt_power: map an existing
    memory's absolute power level back to a portable ordinal tier.
    Returns an unset PowerPreference if there's nothing to compare
    against or the level isn't one of the target's declared levels.
    """
    if power is None or not features.valid_power_levels:
        return model.PowerPreference()
    levels = sorted(features.valid_power_levels, key=float)
    if power not in levels:
        return model.PowerPreference()
    rank = levels.index(power)
    tiers = list(schema.VALID_POWER_TIERS)
    frac = 1 - (rank / (len(levels) - 1)) if len(levels) > 1 else 0
    tier_index = round(frac * (len(tiers) - 1))
    return model.PowerPreference(tier=tiers[tier_index])


def _extract_groups(radio, memory, profile):
    """Best-effort extraction of existing bank/group membership.

    :returns: (group_ids, known) -- `known` is False if this radio's
        mapping/bank support could not be determined at all (as
        opposed to determined-and-empty), so callers can report it as
        an unknown/lost field rather than silently show no groups.
    """
    group_ids = []
    try:
        mapping_models = radio.get_mapping_models()
    except (AttributeError, NotImplementedError):
        return group_ids, False
    for mapping_model in mapping_models:
        try:
            mappings = mapping_model.get_memory_mappings(memory)
        except NotImplementedError:
            return group_ids, False
        for mapping in mappings:
            group_name = mapping.get_name()
            group_id = _slugify(group_name) or (
                'group-%s' % mapping.get_index())
            if group_id not in profile.groups:
                profile.groups[group_id] = model.LogicalGroup(
                    id=group_id, name=group_name)
            group_ids.append(group_id)
    return group_ids, True


@dataclasses.dataclass
class ExtractionSummary:
    channels_extracted: int
    channels_omitted: int
    omitted: tuple
    fields_preserved: tuple
    fields_converted: tuple
    fields_lost: tuple
    receive_only_detected: tuple


@dataclasses.dataclass
class ExtractionResult:
    profile: object
    summary: ExtractionSummary


def extract_profile(radio, memories, name='', description='', region=None):
    """Build a Profile from @memories already read off an open @radio.

    :param radio: the open chirp_common.Radio (used only for
        get_features(), get_name(), and best-effort mapping/bank
        lookups -- never for I/O).
    :param memories: every chirp_common.Memory already read from the
        radio (including empty slots, which are omitted).
    """
    features = radio.get_features()
    try:
        driver_id = directory.radio_class_id(type(radio))
    except Exception:
        driver_id = None
    try:
        model_name = radio.get_name()
    except Exception:
        model_name = ''

    profile = model.Profile(name=name, description=description,
                            region=region)

    used_ids = set()
    omitted = []
    fields_converted = set()
    fields_lost = set()
    receive_only_ids = []
    groups_known = True

    for memory in memories:
        if memory.empty:
            omitted.append((memory.number, 'empty'))
            continue
        if memory.extd_number:
            omitted.append((memory.number, 'special_channel'))
            continue

        logical_id = make_logical_id(memory, used_ids)
        transmit = _extract_transmit(memory)
        if transmit.mode == schema.TRANSMIT_RECEIVE_ONLY:
            receive_only_ids.append(logical_id)

        scan_intent = _SKIP_TO_SCAN_INTENT.get(memory.skip)
        if memory.skip and scan_intent is None:
            fields_lost.add('skip (unrecognized value %r)' % memory.skip)
        elif memory.skip:
            fields_converted.add('scan/skip state')

        if memory.comment and not features.has_comment:
            fields_lost.add('comment')
        if memory.immutable:
            fields_lost.add('driver-enforced immutability of this memory')

        group_ids, known = _extract_groups(radio, memory, profile)
        if not known:
            groups_known = False

        power_pref = _extract_power(memory.power, features)
        if memory.power is not None and power_pref.tier is None:
            fields_lost.add('exact power level (kept as nearest tier only)')

        channel = model.ProfileChannel(
            logical_id=logical_id,
            name=memory.name,
            comment=memory.comment if features.has_comment else '',
            rx_freq_hz=memory.freq,
            transmit=transmit,
            tone_mode=memory.tmode,
            rtone=memory.rtone,
            ctone=memory.ctone,
            dtcs=memory.dtcs,
            rx_dtcs=memory.rx_dtcs,
            dtcs_polarity=memory.dtcs_polarity,
            cross_mode=memory.cross_mode,
            mode=memory.mode,
            power_preference=power_pref,
            scan_intent=scan_intent,
            groups=tuple(group_ids),
            source={
                'source_memory_number': memory.number,
                'source_model': model_name,
                'source_driver': driver_id,
            },
        )
        profile.add_channel(channel)

    if features.has_bank and not groups_known:
        fields_lost.add('bank/group membership (could not be determined)')

    summary = ExtractionSummary(
        channels_extracted=len(profile.channels),
        channels_omitted=len(omitted),
        omitted=tuple(omitted),
        fields_preserved=(
            'rx_freq_hz', 'transmit permission', 'duplex/offset',
            'tone mode', 'DTCS', 'mode', 'name', 'receive-only state',
        ),
        fields_converted=tuple(sorted(fields_converted)),
        fields_lost=tuple(sorted(fields_lost)),
        receive_only_detected=tuple(receive_only_ids),
    )
    return ExtractionResult(profile=profile, summary=summary)
