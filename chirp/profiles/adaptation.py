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

"""Per-channel compatibility classification and value adaptation.

adapt_channel() is the heart of the compatibility engine (section 8):
given a profile channel and a target's declared capabilities, it is a
pure function that returns one AdaptationResult with a classification
(Exact/Adapted/Degraded/Incompatible/Unsafe), a proposed
chirp_common.Memory (unless blocked), and a full accounting of what was
adapted or lost. It never mutates the profile, the channel, or an open
image -- callers (changeset.py) decide when/whether to actually apply
the proposed memory.

Determinism: the same (profile, channel, capabilities) always produces
the same result. There is no hidden state, randomness, or ordering
dependency.
"""

import dataclasses

from chirp import chirp_common
from chirp.profiles import model
from chirp.profiles import safety
from chirp.profiles import schema

SEVERITY = {
    schema.CLASS_EXACT: 0,
    schema.CLASS_ADAPTED: 1,
    schema.CLASS_DEGRADED: 2,
    schema.CLASS_INCOMPATIBLE: 3,
    schema.CLASS_UNSAFE: 4,
}

_VOWELS = frozenset('AEIOU')


def _drop_vowels(word):
    if len(word) <= 1:
        return word
    return word[0] + ''.join(c for c in word[1:] if c not in _VOWELS)


def adapt_name(name, max_length, valid_characters=None):
    """Deterministically adapt @name to fit a target's naming
    constraints, without ever silently truncating unreported.

    Strategy (applied only as far as needed to fit, in this fixed
    order, so the same input always abbreviates the same way):
      1. Upper-case and drop characters outside @valid_characters.
      2. If still too long, drop vowels (keeping each word's first
         letter) from the longest remaining word first.
      3. If still too long, hard-truncate to @max_length.

    :returns: (adapted_name, changed, notes) -- `changed` is False only
        if @name already satisfied every constraint verbatim; `notes`
        is an ordered list of human-readable descriptions of each
        transformation actually applied (empty if unchanged).
    """
    notes = []
    working = name

    if valid_characters is not None:
        filtered = ''.join(c for c in working.upper() if c in valid_characters)
        if filtered != working:
            notes.append(
                'adjusted case/characters to match target charset')
        working = filtered

    if max_length is not None and len(working) > max_length:
        words = working.split()
        if not words:
            words = [working]
        while (sum(len(w) for w in words) > max_length and
               any(any(c in _VOWELS for c in w[1:]) for w in words)):
            candidates = [
                i for i, w in enumerate(words)
                if any(c in _VOWELS for c in w[1:])
            ]
            longest = max(candidates, key=lambda i: len(words[i]))
            words[longest] = _drop_vowels(words[longest])
        if valid_characters is None or ' ' in valid_characters:
            joined = ' '.join(words)
        else:
            joined = ''.join(words)
        if joined != working:
            notes.append(
                'abbreviated to fit %d-character limit' % max_length)
        working = joined
        if len(working) > max_length:
            working = working[:max_length]
            notes.append('truncated to fit %d-character limit' % max_length)

    if not working and name:
        notes.append('name could not be represented on this target and '
                     'was dropped')

    return working, (working != name), notes


@dataclasses.dataclass
class AdaptationResult:
    logical_id: str
    classification: str
    reason_code: str
    message: str
    requested: dict
    proposed: dict
    lost: tuple
    requires_user_action: bool
    blocked: bool
    proposed_memory: object = None


class _Finding:
    def __init__(self, classification, reason_code, message, lost=()):
        self.classification = classification
        self.reason_code = reason_code
        self.message = message
        self.lost = tuple(lost)


def _resolve_transmit(channel, capabilities, findings):
    """Return the proposed (duplex, offset) tuple for the target, after
    recording any findings about how/whether transmit could be honored.
    Never returns a transmit-capable duplex for a receive-only channel.
    """
    transmit = channel.transmit

    if transmit.mode == schema.TRANSMIT_RECEIVE_ONLY:
        if not capabilities.can_enforce_receive_only():
            findings.append(_Finding(
                schema.CLASS_UNSAFE, safety.REASON_UNENFORCEABLE_RX_ONLY,
                'Channel is receive-only but this target has no way to '
                'represent "no transmit" (no off duplex); refusing to '
                'risk enabling transmit'))
            return None, 0
        return 'off', 0

    if transmit.mode == schema.TRANSMIT_UNSPECIFIED:
        findings.append(_Finding(
            schema.CLASS_DEGRADED, 'transmit_intent_unspecified',
            'Profile did not specify transmit permission for this '
            'channel; defaulting to receive-only rather than assuming '
            'transmit is permitted', lost=('transmit permission',)))
        return 'off', 0

    # TRANSMIT_ENABLED from here on.
    duplex = transmit.duplex
    if not capabilities.supports_duplex(duplex):
        findings.append(_Finding(
            schema.CLASS_INCOMPATIBLE, 'duplex_unsupported',
            'Target does not support duplex %r' % (duplex,)))
        return None, 0

    if duplex == schema.DUPLEX_NONE:
        return schema.DUPLEX_NONE, 0

    if duplex == schema.DUPLEX_SPLIT:
        tx_freq = transmit.tx_freq_hz
        if not capabilities.frequency_in_band(tx_freq):
            return _fallback_to_receive_only(capabilities, findings, tx_freq)
        return schema.DUPLEX_SPLIT, tx_freq

    # '+' or '-'
    tx_freq = channel.rx_freq_hz + (
        transmit.offset_hz if duplex == schema.DUPLEX_POSITIVE
        else -transmit.offset_hz)
    if not capabilities.frequency_in_band(tx_freq):
        return _fallback_to_receive_only(capabilities, findings, tx_freq)
    return duplex, transmit.offset_hz


def _fallback_to_receive_only(capabilities, findings, tx_freq):
    """A requested transmit frequency is out of the target's supported
    range. Per section 9.2, this is represented safely as receive-only
    rather than silently programming an out-of-band transmit -- but
    only if the target can actually enforce "off"; otherwise there is
    no safe representation at all.
    """
    if capabilities.can_enforce_receive_only():
        findings.append(_Finding(
            schema.CLASS_DEGRADED, 'tx_out_of_band_forced_receive_only',
            'Requested transmit frequency is outside this target\'s '
            'supported range; the channel was made receive-only rather '
            'than programming an out-of-band transmit',
            lost=('transmit capability',)))
        return 'off', 0
    findings.append(_Finding(
        schema.CLASS_UNSAFE, safety.REASON_OUT_OF_BAND_TX,
        'Requested transmit frequency %s is outside this target\'s '
        'supported range and it cannot be forced receive-only' %
        chirp_common.format_freq(tx_freq)))
    return None, 0


def _adapt_power(resolved_pref, capabilities, findings):
    levels = capabilities.valid_power_levels
    if levels is None or resolved_pref.tier is None:
        return None
    tiers = list(schema.VALID_POWER_TIERS)  # highest .. lowest
    tier_index = tiers.index(resolved_pref.tier)
    # Map the tier's rank (0=highest) onto the target's own sorted (low
    # to high dBm) level list, highest tier -> highest level.
    frac = tier_index / (len(tiers) - 1)
    level_index = round((1 - frac) * (len(levels) - 1))
    chosen = levels[level_index]
    exact = (len(levels) == len(tiers) and
             level_index == len(levels) - 1 - tier_index)
    if not exact:
        findings.append(_Finding(
            schema.CLASS_ADAPTED, 'power_tier_mapped',
            'Power preference %r mapped to nearest available level %s' %
            (resolved_pref.tier, chosen)))
    return chosen


def _adapt_name_for_channel(channel, capabilities, findings):
    if not capabilities.supports_names():
        if channel.name:
            findings.append(_Finding(
                schema.CLASS_DEGRADED, 'names_unsupported',
                'Target does not support memory names',
                lost=('name',)))
        return ''
    adapted, changed, notes = adapt_name(
        channel.name, capabilities.name_length, capabilities.valid_characters)
    if changed:
        classification = (schema.CLASS_DEGRADED if not adapted and
                          channel.name else schema.CLASS_ADAPTED)
        lost = ('name',) if not adapted and channel.name else ()
        findings.append(_Finding(
            classification, 'name_adapted', '; '.join(notes), lost=lost))
    return adapted


def adapt_channel(profile, channel, capabilities):
    """Classify and adapt one profile channel against one target's
    capabilities. Pure function: same inputs -> same AdaptationResult.
    """
    findings = []
    resolved = model.resolve_channel(profile, channel)

    if not capabilities.frequency_in_band(channel.rx_freq_hz):
        findings.append(_Finding(
            schema.CLASS_INCOMPATIBLE, 'frequency_out_of_range',
            'Receive frequency %s is outside this target\'s supported '
            'range' % chirp_common.format_freq(channel.rx_freq_hz)))

    duplex, offset = _resolve_transmit(channel, capabilities, findings)

    if channel.tone_mode and not capabilities.supports_tone_mode(
            channel.tone_mode):
        findings.append(_Finding(
            schema.CLASS_INCOMPATIBLE, 'tone_mode_unsupported',
            'Tone mode %r is not supported by this target' %
            (channel.tone_mode,)))
    if channel.tone_mode in ('DTCS', 'DTCS-R') and \
            not capabilities.supports_dtcs():
        findings.append(_Finding(
            schema.CLASS_INCOMPATIBLE, 'dtcs_unsupported',
            'This target does not support DTCS'))

    if resolved.mode and not capabilities.supports_mode(resolved.mode):
        findings.append(_Finding(
            schema.CLASS_INCOMPATIBLE, 'mode_unsupported',
            'Emission mode %r is not supported by this target' %
            (resolved.mode,)))

    if channel.comment and not capabilities.supports_comment():
        findings.append(_Finding(
            schema.CLASS_DEGRADED, 'comment_unsupported',
            'Target does not support memory comments',
            lost=('comment',)))

    if channel.groups and not capabilities.supports_banks():
        findings.append(_Finding(
            schema.CLASS_DEGRADED, 'groups_unsupported',
            'Target has no bank/group support; group membership is '
            'preserved in the profile but not on the radio',
            lost=('group membership',)))

    skip = schema.SCAN_INTENT_TO_SKIP.get(resolved.scan_intent, '')
    if resolved.scan_intent and not capabilities.supports_skip(skip):
        findings.append(_Finding(
            schema.CLASS_DEGRADED, 'scan_intent_unsupported',
            'Target does not support scan/skip state %r' %
            (resolved.scan_intent,), lost=('scan intent',)))

    adapted_name = _adapt_name_for_channel(channel, capabilities, findings)
    adapted_power = _adapt_power(resolved.power_preference, capabilities,
                                 findings)

    overall = schema.CLASS_EXACT
    for f in findings:
        if SEVERITY[f.classification] > SEVERITY[overall]:
            overall = f.classification
    blocked = overall == schema.CLASS_UNSAFE
    # An Incompatible channel cannot be meaningfully represented at all
    # (section 8): there is nothing to add/modify, so -- like a blocked
    # Unsafe channel -- it gets no proposed memory. Unlike Unsafe, it
    # isn't "blocked" in the safety sense; changeset.py is free to
    # offer Skip without treating it as a safety override.
    unrepresentable = overall in (schema.CLASS_INCOMPATIBLE,
                                  schema.CLASS_UNSAFE)

    proposed_memory = None
    if not unrepresentable and duplex is not None:
        mem = chirp_common.Memory()
        mem.freq = channel.rx_freq_hz
        mem.duplex = duplex
        mem.offset = offset
        mem.name = adapted_name
        mem.comment = channel.comment if capabilities.supports_comment() \
            else ''
        mem.tmode = channel.tone_mode
        mem.cross_mode = channel.cross_mode
        mem.rtone = channel.rtone
        mem.ctone = channel.ctone
        mem.dtcs = channel.dtcs
        mem.rx_dtcs = channel.rx_dtcs
        mem.dtcs_polarity = channel.dtcs_polarity
        if resolved.mode:
            mem.mode = resolved.mode
        if adapted_power is not None:
            mem.power = adapted_power
        mem.skip = skip
        proposed_memory = mem
    elif duplex is None and overall == schema.CLASS_EXACT:
        # _resolve_transmit found something unrepresentable but somehow
        # logged nothing severe -- should not happen, but never silently
        # produce a memory in this case.
        overall = schema.CLASS_INCOMPATIBLE

    reason_code = 'exact_match'
    message_parts = []
    lost = []
    for f in findings:
        if f.classification == overall:
            reason_code = f.reason_code
        if f.message:
            message_parts.append(f.message)
        lost.extend(f.lost)

    return AdaptationResult(
        logical_id=channel.logical_id,
        classification=overall,
        reason_code=reason_code,
        message='; '.join(message_parts) or 'No changes needed',
        requested={
            'name': channel.name,
            'rx_freq_hz': channel.rx_freq_hz,
            'transmit_mode': channel.transmit.mode,
        },
        proposed=({} if proposed_memory is None else {
            'name': proposed_memory.name,
            'freq': proposed_memory.freq,
            'duplex': proposed_memory.duplex,
        }),
        lost=tuple(lost),
        requires_user_action=(overall != schema.CLASS_EXACT),
        blocked=blocked,
        proposed_memory=proposed_memory,
    )
