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

"""Memory-number placement strategies (section 12).

This module only decides numbers for channels that have *no* existing
match -- a channel matched by chirp.profiles.matching always keeps the
matched memory's number (that's "update matching channels" and
"preserve existing memories" from the design doc: they are always-on
behaviors of the whole pipeline, not something a caller opts into here).

Placement never silently claims an already-occupied, unmatched memory.
The one exception is PLACEMENT_REPLACE_RANGE, and only because the
caller explicitly supplied that exact range -- the resulting decision
is still marked `replaces_existing=True` so changeset.py can surface it
plainly rather than silently.
"""

import dataclasses

from chirp.profiles import schema


@dataclasses.dataclass
class PlacementDecision:
    logical_id: str
    memory_number: int | None
    replaces_existing: bool = False
    conflict_reason: str | None = None


def _locked_numbers(existing_memories):
    """Numbers placement must never claim outright: occupied by a real
    memory, or carrying any immutable field (can't safely be
    reassigned to a different channel's content)."""
    return {
        m.number for m in existing_memories
        if not m.empty or m.immutable
    }


def _empty_numbers(existing_memories, bounds):
    occupied_or_locked = _locked_numbers(existing_memories)
    known = {m.number for m in existing_memories}
    empties = {
        m.number for m in existing_memories
        if m.empty and not m.immutable
    }
    if bounds is not None:
        lo, hi = bounds
        for n in range(lo, hi + 1):
            if n not in known:
                empties.add(n)
        empties = {n for n in empties if lo <= n <= hi}
    return sorted(empties - occupied_or_locked)


def plan_placement(logical_ids, existing_memories, capabilities, strategy,
                   explicit_range=None):
    """Assign memory numbers to @logical_ids (channels with no existing
    match), in the given deterministic order, using @strategy.

    :param logical_ids: ordered sequence of profile channel logical_ids
        needing a *new* memory number.
    :param existing_memories: every memory currently in the target
        image.
    :param capabilities: a chirp.profiles.capabilities.TargetCapabilities
        for the target radio.
    :param strategy: one of schema.VALID_PLACEMENT_STRATEGIES.
    :param explicit_range: for PLACEMENT_REPLACE_RANGE, an ordered
        sequence of memory numbers to use, one per logical_id in order.
    :returns: a list of PlacementDecision, one per logical_id, in the
        same order. Deterministic for the same inputs.
    """
    if strategy not in schema.VALID_PLACEMENT_STRATEGIES:
        raise ValueError('Unknown placement strategy %r' % (strategy,))

    bounds = capabilities.memory_bounds
    decisions = []

    if strategy == schema.PLACEMENT_REPLACE_RANGE:
        explicit_range = list(explicit_range or [])
        locked = _locked_numbers(existing_memories)
        occupied = {m.number for m in existing_memories if not m.empty}
        for i, logical_id in enumerate(logical_ids):
            if i >= len(explicit_range):
                decisions.append(PlacementDecision(
                    logical_id, None,
                    conflict_reason=schema.CONFLICT_CAPACITY_EXCEEDED))
                continue
            number = explicit_range[i]
            if bounds is not None and not (bounds[0] <= number <= bounds[1]):
                decisions.append(PlacementDecision(
                    logical_id, None, conflict_reason='out_of_bounds'))
                continue
            if number in locked and number in occupied:
                # Occupied but not itself immutable is fine to replace
                # (that's the whole point of this strategy); truly
                # immutable slots are never reassignable.
                existing = next(m for m in existing_memories
                                if m.number == number)
                if existing.immutable:
                    decisions.append(PlacementDecision(
                        logical_id, None,
                        conflict_reason=schema.CONFLICT_IMMUTABLE_MEMORY))
                    continue
            decisions.append(PlacementDecision(
                logical_id, number, replaces_existing=number in occupied))
        return decisions

    if strategy == schema.PLACEMENT_FILL_EMPTY:
        available = _empty_numbers(existing_memories, bounds)
        for i, logical_id in enumerate(logical_ids):
            if i < len(available):
                decisions.append(PlacementDecision(logical_id, available[i]))
            else:
                decisions.append(PlacementDecision(
                    logical_id, None,
                    conflict_reason=schema.CONFLICT_CAPACITY_EXCEEDED))
        return decisions

    # PLACEMENT_APPEND
    locked = _locked_numbers(existing_memories)
    lo = bounds[0] if bounds is not None else 0
    next_number = max(locked, default=lo - 1) + 1
    next_number = max(next_number, lo)
    for logical_id in logical_ids:
        while next_number in locked:
            next_number += 1
        if bounds is not None and next_number > bounds[1]:
            decisions.append(PlacementDecision(
                logical_id, None,
                conflict_reason=schema.CONFLICT_CAPACITY_EXCEEDED))
            continue
        decisions.append(PlacementDecision(logical_id, next_number))
        locked = locked | {next_number}
        next_number += 1
    return decisions
