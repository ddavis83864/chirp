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

"""Ties matching + placement + adaptation + conflicts together into one
deterministic, previewable ChangeSet (section 14).

build_changeset() never touches an open image -- it only reads the
existing memories it's given and returns a proposal. Nothing here
mutates a radio; that is chirp.wxui.profilecontroller's job (Phase 7),
using the *approved* subset of this change set as its single undoable
transaction.
"""

import dataclasses

from chirp.profiles import adaptation
from chirp.profiles import conflicts as conflicts_mod
from chirp.profiles import errors
from chirp.profiles import matching
from chirp.profiles import placement
from chirp.profiles import schema


@dataclasses.dataclass
class ChangeSetItem:
    logical_id: str
    action: str
    classification: str
    reason_code: str
    message: str
    lost: tuple
    blocked: bool
    approval_state: str
    channel: object
    proposed_memory: object = None
    existing_memory: object = None
    target_memory_number: int | None = None
    conflicts: tuple = ()

    @property
    def profile_channel_summary(self):
        return {
            'logical_id': self.channel.logical_id,
            'name': self.channel.name,
            'rx_freq_hz': self.channel.rx_freq_hz,
            'transmit_mode': self.channel.transmit.mode,
        }

    @property
    def existing_memory_summary(self):
        if self.existing_memory is None:
            return None
        return {
            'number': self.existing_memory.number,
            'name': self.existing_memory.name,
            'freq': self.existing_memory.freq,
            'duplex': self.existing_memory.duplex,
        }


@dataclasses.dataclass
class ChangeSet:
    profile_id: str
    profile_name: str
    items: list

    def get(self, logical_id):
        for item in self.items:
            if item.logical_id == logical_id:
                return item
        return None

    def set_approval(self, logical_id, approval_state):
        if approval_state not in (schema.APPROVAL_APPROVED,
                                  schema.APPROVAL_REJECTED):
            raise ValueError('Invalid approval_state %r' % (approval_state,))
        item = self.get(logical_id)
        if item is None:
            raise KeyError(logical_id)
        if item.blocked:
            raise errors.UnsafeOperationError(
                'Channel %r is blocked and cannot be approved' %
                (logical_id,))
        item.approval_state = approval_state

    def approved_items(self):
        return [
            i for i in self.items
            if i.approval_state == schema.APPROVAL_APPROVED and
            i.action in (schema.ACTION_ADD, schema.ACTION_MODIFY)
        ]

    def summary(self):
        counts = {}
        for item in self.items:
            counts[item.action] = counts.get(item.action, 0) + 1
        return counts


def _default_approval(action):
    if action == schema.ACTION_BLOCKED:
        return schema.APPROVAL_BLOCKED
    if action == schema.ACTION_KEEP:
        return schema.APPROVAL_APPROVED
    return schema.APPROVAL_PENDING


def build_changeset(
        profile, capabilities, existing_memories,
        placement_strategy=schema.PLACEMENT_FILL_EMPTY,
        explicit_range=None):
    """Build the full proposed ChangeSet for applying @profile onto a
    target described by @capabilities, given what's already in
    @existing_memories. Deterministic for the same inputs (section 3.5).
    """
    adapt_results = {}
    match_results = {}
    proposed_by_id = {}
    needing_placement = []

    for channel in profile.channels:
        result = adaptation.adapt_channel(profile, channel, capabilities)
        adapt_results[channel.logical_id] = result
        if result.proposed_memory is None:
            match_results[channel.logical_id] = matching.MatchResult(
                schema.MATCH_NONE)
            continue
        match = matching.match_channel(result.proposed_memory,
                                       existing_memories)
        match_results[channel.logical_id] = match
        proposed_by_id[channel.logical_id] = result.proposed_memory
        if match.match_type == schema.MATCH_NONE:
            needing_placement.append(channel.logical_id)

    placements = placement.plan_placement(
        needing_placement, existing_memories, capabilities,
        placement_strategy, explicit_range=explicit_range)
    placement_by_id = {d.logical_id: d for d in placements}

    conflict_list = conflicts_mod.detect_conflicts(
        placement_by_id, match_results, proposed_by_id)
    conflicts_by_id = {}
    for c in conflict_list:
        for logical_id in c.logical_ids:
            conflicts_by_id.setdefault(logical_id, []).append(c)

    items = []
    for channel in profile.channels:
        result = adapt_results[channel.logical_id]
        match = match_results[channel.logical_id]
        item_conflicts = tuple(conflicts_by_id.get(channel.logical_id, ()))

        target_number = None
        existing_memory = None
        if result.blocked:
            action = schema.ACTION_BLOCKED
        elif result.classification == schema.CLASS_INCOMPATIBLE:
            action = schema.ACTION_SKIP
        elif item_conflicts:
            action = schema.ACTION_CONFLICT
        elif match.match_type == schema.MATCH_EXACT:
            action = schema.ACTION_KEEP
            existing_memory = match.existing_memory
            target_number = existing_memory.number
        elif match.match_type == schema.MATCH_UPDATE_CANDIDATE:
            action = schema.ACTION_MODIFY
            existing_memory = match.existing_memory
            target_number = existing_memory.number
        elif match.match_type == schema.MATCH_NONE:
            decision = placement_by_id.get(channel.logical_id)
            if decision is not None and decision.memory_number is not None:
                action = schema.ACTION_ADD
                target_number = decision.memory_number
            else:
                action = schema.ACTION_CONFLICT
        else:
            # MATCH_AMBIGUOUS without a conflict object -- shouldn't
            # happen; conflicts.detect_conflicts always reports it.
            action = schema.ACTION_CONFLICT

        items.append(ChangeSetItem(
            logical_id=channel.logical_id,
            action=action,
            classification=result.classification,
            reason_code=result.reason_code,
            message=result.message,
            lost=result.lost,
            blocked=result.blocked,
            approval_state=_default_approval(action),
            channel=channel,
            proposed_memory=result.proposed_memory,
            existing_memory=existing_memory,
            target_memory_number=target_number,
            conflicts=item_conflicts,
        ))

    return ChangeSet(profile_id=profile.profile_id, profile_name=profile.name,
                     items=items)
