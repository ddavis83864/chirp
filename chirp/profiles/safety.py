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

"""Safety rules: preservation of the user's explicit receive-only intent.

This module makes no regulatory claims (CHIRP cannot authoritatively
determine what's legal to transmit on in any given jurisdiction). Its
one job is narrower and enforceable: a channel the profile author
explicitly marked receive-only must never come out the other end of
adaptation, overrides, or placement as transmit-capable, and any point
in the pipeline that cannot *positively confirm* a safety-relevant
capability must fail closed (report "unknown", not "assume safe").

See chirp.profiles.schema.TRANSMIT_* and model.TransmitBehavior for the
underlying representation, and adaptation.py for how these violations
feed into a channel's overall classification (Unsafe channels are
blocked, never merely warned about).
"""

import dataclasses

from chirp.profiles import schema

#: Machine-readable reason codes (section 8/9 of the design doc).
REASON_RX_ONLY_WOULD_TRANSMIT = 'rx_only_would_transmit'
REASON_OUT_OF_BAND_TX = 'out_of_band_transmit'
REASON_OVERRIDE_REMOVES_SAFETY = 'override_removes_safety_restriction'
REASON_UNKNOWN_CAPABILITY = 'unknown_capability'
REASON_UNENFORCEABLE_RX_ONLY = 'unenforceable_rx_only'


@dataclasses.dataclass(frozen=True)
class SafetyViolation:
    reason_code: str
    message: str
    logical_id: str | None = None


def is_receive_only(channel):
    return channel.transmit.mode == schema.TRANSMIT_RECEIVE_ONLY


def check_receive_only_preserved(channel, proposed_duplex):
    """Confirm a receive-only channel's proposed target duplex is 'off'.

    :param channel: a model.ProfileChannel
    :param proposed_duplex: the chirp_common.Memory.duplex value ('',
        '+', '-', 'split', 'off') the adaptation engine is about to
        write to the target memory.
    :returns: a SafetyViolation if the channel is receive-only but the
        proposed duplex is not 'off' (i.e. would permit transmit);
        None if there is nothing to block.
    """
    if not is_receive_only(channel):
        return None
    if proposed_duplex == 'off':
        return None
    return SafetyViolation(
        REASON_RX_ONLY_WOULD_TRANSMIT,
        'Channel %r is marked receive-only but the proposed target '
        'configuration (duplex=%r) would permit transmit' %
        (channel.logical_id, proposed_duplex),
        logical_id=channel.logical_id)


def check_override_does_not_remove_safety(override):
    """Overrides can never carry a transmit-permission field at all --
    schema.ALLOWED_OVERRIDE_FIELDS structurally excludes it. This is a
    defense-in-depth re-check for callers that build TargetOverride
    objects without going through validation.validate_override first.
    """
    forbidden = {'transmit', 'transmit_mode', 'receive_only'}
    hit = forbidden & set(override.fields)
    if not hit:
        return None
    return SafetyViolation(
        REASON_OVERRIDE_REMOVES_SAFETY,
        'Override attempts to change transmit permission via %s, which '
        'is never allowed' % sorted(hit))


def check_capability_known(capability_name, value):
    """Fail closed: if a safety-relevant capability could not be
    determined (value is None), report it as unknown rather than
    assuming it is safe.
    """
    if value is not None:
        return None
    return SafetyViolation(
        REASON_UNKNOWN_CAPABILITY,
        'Target radio capability %r could not be determined; refusing '
        'to assume it is safe' % (capability_name,))
