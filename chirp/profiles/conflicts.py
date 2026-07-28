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

"""Structured conflict objects (section 13).

Some conflict-shaped problems listed in the design doc are already
covered by other modules and are deliberately not re-detected here:
unsupported modes/tones and "valid to receive but unsafe to transmit"
are per-channel chirp.profiles.adaptation classifications
(Incompatible/Unsafe), and a target-override that would remove a
safety restriction is structurally impossible (validation.py rejects
any override field that could touch transmit permission at all). This
module covers the remaining, inherently *cross-channel* or
*placement*-level conflicts: two things competing for one memory
location, running out of room, an unresolved existing-memory match, or
two proposed channels landing on the same displayed name.
"""

import collections
import dataclasses

from chirp.profiles import schema


@dataclasses.dataclass
class Conflict:
    conflict_type: str
    message: str
    logical_ids: tuple
    memory_number: int | None = None


def detect_conflicts(placement_by_logical_id, match_by_logical_id,
                     proposed_memory_by_logical_id):
    """Find every cross-channel/placement conflict in one proposed
    apply.

    :param placement_by_logical_id: {logical_id: placement.PlacementDecision}
        for channels that needed a new memory number (i.e. had no
        existing match).
    :param match_by_logical_id: {logical_id: matching.MatchResult} for
        every channel being applied.
    :param proposed_memory_by_logical_id: {logical_id: chirp_common.Memory}
        the proposed target memory for every non-blocked, non-
        incompatible channel.
    :returns: a list of Conflict, deterministic for the same inputs.
    """
    conflicts = []

    by_number = collections.defaultdict(list)
    for logical_id, decision in placement_by_logical_id.items():
        if decision.memory_number is not None:
            by_number[decision.memory_number].append(logical_id)
    for logical_id, match in match_by_logical_id.items():
        if match.match_type in (
                schema.MATCH_EXACT, schema.MATCH_UPDATE_CANDIDATE):
            by_number[match.existing_memory.number].append(logical_id)
    for number, logical_ids in sorted(by_number.items()):
        if len(set(logical_ids)) > 1:
            conflicts.append(Conflict(
                schema.CONFLICT_DUPLICATE_TARGET,
                'Memory %d is claimed by more than one profile channel' %
                number,
                tuple(sorted(set(logical_ids))), memory_number=number))

    for logical_id, decision in sorted(placement_by_logical_id.items()):
        if decision.conflict_reason == schema.CONFLICT_CAPACITY_EXCEEDED:
            conflicts.append(Conflict(
                schema.CONFLICT_CAPACITY_EXCEEDED,
                'No available memory location for this channel',
                (logical_id,)))
        elif decision.conflict_reason == schema.CONFLICT_IMMUTABLE_MEMORY:
            conflicts.append(Conflict(
                schema.CONFLICT_IMMUTABLE_MEMORY,
                'Memory %s cannot be reassigned (locked by the driver)' %
                (decision.memory_number,),
                (logical_id,), memory_number=decision.memory_number))
        elif decision.replaces_existing:
            conflicts.append(Conflict(
                schema.CONFLICT_LOCATION_OCCUPIED,
                'Memory %d is already in use by an unrelated, unmatched '
                'memory; the selected placement range will replace it' %
                decision.memory_number,
                (logical_id,), memory_number=decision.memory_number))

    for logical_id, match in sorted(match_by_logical_id.items()):
        if match.match_type == schema.MATCH_AMBIGUOUS:
            numbers = sorted(m.number for m in match.candidates)
            conflicts.append(Conflict(
                schema.CONFLICT_AMBIGUOUS_MATCH,
                'This channel matches more than one existing memory (%s) '
                'and cannot be resolved automatically' %
                ', '.join(str(n) for n in numbers),
                (logical_id,)))

    names = collections.defaultdict(list)
    for logical_id, mem in proposed_memory_by_logical_id.items():
        if mem is not None and mem.name:
            names[mem.name].append(logical_id)
    for name, logical_ids in sorted(names.items()):
        if len(set(logical_ids)) > 1:
            conflicts.append(Conflict(
                schema.CONFLICT_NAME_COLLISION,
                'More than one channel is proposed with the name %r' %
                (name,),
                tuple(sorted(set(logical_ids)))))

    return conflicts
