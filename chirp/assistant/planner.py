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

"""The deterministic planner: groups, scores, deduplicates, names,
orders, and allocates memory numbers for a set of already
policy-resolved ChannelCandidates. Nothing here talks to a network, an
AI provider, or a radio driver -- it's pure, deterministic, and
independently unit-testable (same input always produces the same plan).

This module does NOT decide transmit eligibility (see policies.py) or
run destination-radio validation (see converter.py/validator.py) -- by
the time a candidate reaches here, candidate.receive_only is already
final.
"""

from chirp.assistant import converter
from chirp.assistant import models
from chirp.assistant import provenance as provenance_mod

_GROUP_NAMES = {
    models.SERVICE_GMRS: 'GMRS',
    models.SERVICE_FRS: 'FRS',
    models.SERVICE_MURS: 'MURS',
    models.SERVICE_WEATHER: 'Weather',
    models.SERVICE_AVIATION: 'Aviation (Receive Only)',
    models.SERVICE_MARINE: 'Marine (Receive Only)',
    models.SERVICE_PUBLIC_SAFETY: 'Public Safety (Receive Only)',
    models.SERVICE_BUSINESS: 'Business (Receive Only)',
    models.SERVICE_RAILROAD: 'Railroad (Receive Only)',
    models.SERVICE_SATELLITE: 'Satellite',
}

_CONFIDENCE_RANK = {
    models.CONFIDENCE_HIGH: 0,
    models.CONFIDENCE_MEDIUM: 1,
    models.CONFIDENCE_LOW: 2,
}

# Lower sorts first / wins ties within a dedup group.
_SERVICE_RANK = {
    models.SERVICE_HAM: 0,
    models.SERVICE_GMRS: 1,
    models.SERVICE_SATELLITE: 2,
    models.SERVICE_FRS: 3,
    models.SERVICE_MURS: 4,
    models.SERVICE_WEATHER: 5,
    models.SERVICE_AVIATION: 6,
    models.SERVICE_MARINE: 7,
    models.SERVICE_PUBLIC_SAFETY: 8,
    models.SERVICE_BUSINESS: 9,
    models.SERVICE_RAILROAD: 10,
}


def group_name(candidate):
    if candidate.service == models.SERVICE_HAM:
        if (candidate.tx_freq is not None and
                candidate.tx_freq != candidate.freq):
            return 'Local Amateur Repeaters'
        return 'Amateur Simplex'
    return _GROUP_NAMES.get(candidate.service, candidate.service.title())


def _score(candidate):
    """Sort key: lower is better/kept-first. Deterministic given the
    same candidate list -- ties break on label so output order never
    depends on input (e.g. source query) ordering."""
    has_distance = candidate.distance_miles is not None
    return (
        0 if has_distance else 1,
        candidate.distance_miles if has_distance else 0.0,
        _CONFIDENCE_RANK.get(candidate.confidence, 9),
        _SERVICE_RANK.get(candidate.service, 99),
        candidate.label,
        candidate.source_record_id,
    )


def deduplicate(candidates):
    """Return (kept, dropped) -- @dropped have status/include already
    set to STATUS_DUPLICATE / False, referencing which kept candidate
    they duplicate."""
    ordered = sorted(candidates, key=_score)
    kept = []
    dropped = []
    seen = {}
    for c in ordered:
        key = c.dedup_key()
        if key in seen:
            c.status = models.STATUS_DUPLICATE
            c.include = False
            c.reason = 'Duplicate of %r' % seen[key].label
            dropped.append(c)
        else:
            seen[key] = c
            kept.append(c)
    return kept, dropped


def _memory_matches_candidate(memory, candidate):
    """Whether an existing occupied memory looks like the "same
    channel" as @candidate, for existing-conflict detection. Uses the
    same notion of identity as dedup_key(), on the existing memory's
    own fields."""
    if memory.empty:
        return False
    if memory.freq != candidate.freq:
        return False
    existing_tx = converter.tx_freq_from_memory(memory)
    return existing_tx == candidate.tx_freq or (
        existing_tx == candidate.freq and candidate.tx_freq is None)


def flag_existing_conflicts(candidates, existing_memories, request):
    """Mark candidates that collide with a populated existing memory.
    Returns the list of candidates that are still eligible to proceed
    (conflicting ones get include=False unless allow_duplicate_replacement
    is set, in which case they're flagged but left include=True with
    their target memory_number pre-assigned to the conflicting slot)."""
    survivors = []
    for c in candidates:
        conflict = None
        for number, memory in existing_memories:
            if _memory_matches_candidate(memory, c):
                conflict = (number, memory)
                break
        if conflict is None:
            survivors.append(c)
            continue
        number, memory = conflict
        if request.allow_duplicate_replacement:
            c.status = models.STATUS_EXISTING_CONFLICT
            c.reason = ('Will replace existing memory %s (%s)' %
                        (number, memory.name or memory.freq))
            c.memory_number = number
            survivors.append(c)
        else:
            c.status = models.STATUS_EXISTING_CONFLICT
            c.include = False
            c.reason = ('Matches existing memory %s (%s); not replaced '
                        '(enable "allow duplicate replacement" to change '
                        'this)' % (number, memory.name or memory.freq))
    return survivors


def _is_protected(number, request):
    for lo, hi in request.protected_memory_ranges:
        if lo <= number <= hi:
            return True
    return False


def allocate_memory_numbers(candidates, capability, existing_memories,
                            request):
    """Assign candidate.memory_number to every candidate that doesn't
    already have one pre-assigned (existing-conflict replacements do).
    Never reuses an occupied, protected, or special-channel number.
    Candidates that can't be placed get include=False and a reason;
    returns True if capacity was exceeded."""
    # A memory can be immutable (some fields can never be changed by
    # set_memory()) while still reading as empty -- e.g. a fixed
    # priority/call channel nobody has programmed content into yet.
    # Treat it as unavailable regardless of its empty flag; otherwise
    # Apply would raise ImmutableValueError for a slot this function
    # itself handed out.
    occupied = {number for number, memory in existing_memories
                if not memory.empty or getattr(memory, 'immutable', ())}
    lo, hi = capability.memory_bounds
    start = request.requested_start_memory
    end = request.requested_end_memory
    if start is not None:
        lo = max(lo, start)
    if end is not None:
        hi = min(hi, end)

    taken = set(occupied)
    for c in candidates:
        if c.memory_number is not None:
            taken.add(c.memory_number)

    capacity_limited = False
    cursor = lo
    for c in candidates:
        if c.memory_number is not None:
            continue
        placed = False
        n = cursor
        while n <= hi:
            if n not in taken and not _is_protected(n, request):
                c.memory_number = n
                taken.add(n)
                cursor = n + 1
                placed = True
                break
            n += 1
        if not placed:
            c.include = False
            if c.status not in (models.STATUS_DUPLICATE,
                                models.STATUS_EXISTING_CONFLICT):
                c.status = models.STATUS_BLOCKED
            c.reason = c.reason or 'No available memory slot for this channel'
            capacity_limited = True
    return capacity_limited


def enforce_channel_limit(candidates, request):
    """Cap the number of included candidates at request.channel_limit,
    keeping the highest-scored ones. Excess candidates are NOT removed
    from the plan -- they're marked include=False with a reason, so the
    preview never silently discards anything."""
    included = [c for c in candidates if c.include]
    if len(included) <= request.channel_limit:
        return False
    ordered = sorted(included, key=_score)
    for c in ordered[request.channel_limit:]:
        c.include = False
        c.reason = c.reason or 'Exceeds requested channel limit (%i)' % (
            request.channel_limit)
    return True


def _sanitize_name(text, capability):
    chars = capability.valid_characters or None
    length = capability.valid_name_length or 16
    if chars:
        # Most radios' valid_characters is upper-case-only; if theirs
        # is, canonicalize to upper case before filtering rather than
        # just checking ch.upper() in chars, which would silently let
        # lowercase letters through even though the destination doesn't
        # actually accept them (import_logic's own filter_name() would
        # then re-case it anyway, so this keeps the preview name
        # consistent with what will actually be applied).
        if not any(ch.islower() for ch in chars):
            text = text.upper()
        text = ''.join(ch for ch in text if ch in chars)
    return text[:length].rstrip()


def assign_names(candidates, capability, naming_style):
    """Deterministic, radio-constrained naming. candidates must already
    be in final display order (see build_plan) so name collisions
    resolve the same way on every run given the same input."""
    used = set()
    for c in candidates:
        base = c.label if naming_style == models.NAMING_DESCRIPTIVE else (
            c.label.split(',')[0].split('(')[0].strip())
        name = _sanitize_name(base, capability)
        if not name:
            name = _sanitize_name(c.service.upper(), capability)
        candidate_name = name
        suffix = 1
        while candidate_name.upper() in used:
            suffix += 1
            trim = capability.valid_name_length - len(str(suffix))
            candidate_name = _sanitize_name(name[:max(trim, 1)], capability) \
                + str(suffix)
        used.add(candidate_name.upper())
        c.name = candidate_name
        c.provenance = provenance_mod.note_deterministic_field(
            c.provenance, 'name')
    return candidates


def build_plan(candidates, request, capability, existing_memories):
    """The full deterministic pipeline: dedup -> existing-conflict check
    -> channel-limit enforcement -> memory-number allocation -> naming
    -> grouping. Returns a models.ChannelPlan. Does not run any
    destination-radio conversion/validation -- see service.py, which
    calls converter/validator on the resulting plan's candidates."""
    kept, dropped = deduplicate(candidates)
    survivors = flag_existing_conflicts(kept, existing_memories, request)

    # survivors + dropped + (kept - survivors) all need to appear in the
    # final plan somewhere so nothing is silently discarded. Compare by
    # identity, not value -- ChannelCandidate is a mutable dataclass
    # with a value-based __eq__, and two distinct candidates could
    # legitimately share identical field values.
    survivor_ids = {id(c) for c in survivors}
    excluded_by_conflict = [c for c in kept if id(c) not in survivor_ids]

    capacity_limited = enforce_channel_limit(survivors, request)
    capacity_limited = allocate_memory_numbers(
        [c for c in survivors if c.include], capability, existing_memories,
        request) or capacity_limited

    ordered = sorted(survivors, key=_score)
    assign_names([c for c in ordered if c.include], capability,
                 request.naming_style)

    all_candidates = ordered + dropped + excluded_by_conflict
    groups_by_name = {}
    for c in all_candidates:
        groups_by_name.setdefault(group_name(c), []).append(c)

    groups = [models.PlanGroup(name=name, candidates=members)
              for name, members in sorted(groups_by_name.items())]

    warnings = []
    if capacity_limited:
        warnings.append(models.PlanWarning(
            severity='warning',
            message='Some channels could not be included due to the '
                    'channel limit or available memory slots.'))
    if dropped:
        warnings.append(models.PlanWarning(
            severity='info',
            message='%i duplicate channel(s) were consolidated.' %
                    len(dropped)))
    if excluded_by_conflict:
        warnings.append(models.PlanWarning(
            severity='info',
            message='%i channel(s) matched an existing memory and were '
                    'not replaced.' % len(excluded_by_conflict)))

    return models.ChannelPlan(
        request=request, groups=groups, warnings=warnings,
        capacity_limited=capacity_limited)
