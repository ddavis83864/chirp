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

"""Matches proposed target memories against what's already programmed
in an open image (section 11).

Two signatures are used, both deliberately excluding the memory's name
(section 11: "Do not treat channel names as unique identifiers"):

- The *full* operational-duplicate signature CHIRP itself already uses
  (chirp_common.find_duplicate_memories/DUPE_SIGNATURE_FIELDS) --
  freq, duplex, offset, mode, tones, power, skip, ... -- for "this
  exact channel is already there, nothing to do".
- A *core* freq+duplex+offset-only signature for "this is clearly the
  same channel, but something else about it (tone, name, power,
  comment, skip) changed" -- an update candidate.

Profile-linkage metadata (section 16: a persisted logical_id ->
target-memory mapping from a previous apply) would outrank both of
these if present, but that tracking is deferred past the first release
(see docs/profiles.md); today every match is content-based.
"""

import copy
import dataclasses

from chirp import chirp_common
from chirp.profiles import schema


@dataclasses.dataclass
class MatchResult:
    match_type: str
    existing_memory: object = None
    candidates: tuple = ()


def _core_signature(mem):
    duplex = mem.duplex
    offset = None if duplex in ('', 'off') else mem.offset
    return (mem.freq, duplex, offset)


def _real_memories(existing_memories):
    """Existing memories eligible for matching: not empty, not a
    special/named channel (mirrors find_duplicate_memories' own
    exclusions)."""
    return [m for m in existing_memories if not m.empty and not m.extd_number]


def match_channel(proposed_memory, existing_memories):
    """Match one proposed target chirp_common.Memory against the
    memories already present in an open image.

    :param proposed_memory: a chirp_common.Memory as produced by
        chirp.profiles.adaptation.adapt_channel (never mutated).
    :param existing_memories: every memory currently in the target
        image (empty and special slots are filtered out internally).
    :returns: a MatchResult. Deterministic for the same inputs.
    """
    candidates = _real_memories(existing_memories)
    if not candidates:
        return MatchResult(schema.MATCH_NONE)

    probe = copy.deepcopy(proposed_memory)
    probe.number = -1
    for group in chirp_common.find_duplicate_memories(
            [probe] + candidates, fields=chirp_common.DUPE_SIGNATURE_FIELDS):
        if len(group) > 1 and any(m.number == -1 for m in group):
            others = tuple(m for m in group if m.number != -1)
            # DUPE_SIGNATURE_FIELDS deliberately excludes name (it's not
            # part of what makes two memories operationally different
            # elsewhere in CHIRP) -- but for an apply preview, a name-
            # only difference still means something should change, so
            # it is not a true no-op EXACT match here.
            if others[0].name == proposed_memory.name:
                return MatchResult(schema.MATCH_EXACT,
                                   existing_memory=others[0],
                                   candidates=others)
            return MatchResult(schema.MATCH_UPDATE_CANDIDATE,
                               existing_memory=others[0], candidates=others)

    core = _core_signature(proposed_memory)
    core_matches = tuple(m for m in candidates if _core_signature(m) == core)
    if not core_matches:
        return MatchResult(schema.MATCH_NONE)
    if len(core_matches) == 1:
        return MatchResult(schema.MATCH_UPDATE_CANDIDATE,
                           existing_memory=core_matches[0],
                           candidates=core_matches)
    return MatchResult(schema.MATCH_AMBIGUOUS, candidates=core_matches)
