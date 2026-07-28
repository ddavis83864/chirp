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

"""Coordinates intent extraction, source queries, planning, capability
filtering, conversion, and validation into a previewable plan. No wx
dependency -- chirp.wxui.programming_assistant is a thin UI layer over
this; everything here is independently unit-testable, and the actual
"write to the open image" step deliberately happens one layer up (in
the wx module) since that's where CHIRP's undo_context() lives.
"""

import logging

from chirp.assistant import capability as capability_mod
from chirp.assistant import converter
from chirp.assistant import models
from chirp.assistant import planner
from chirp.assistant import policies
from chirp.assistant import sources
from chirp.assistant import validator

LOG = logging.getLogger(__name__)


def read_existing_memories(radio):
    """Read every memory currently in @radio's numeric range into a
    [(number, chirp_common.Memory), ...] list, for the planner's
    existing-image awareness. Special/extended-number channels are not
    included (they're never auto-allocation targets anyway)."""
    rf = radio.get_features()
    lo, hi = rf.memory_bounds
    result = []
    for number in range(lo, hi + 1):
        try:
            memory = radio.get_memory(number)
        except Exception:
            LOG.debug('Could not read memory %s while scanning existing '
                      'image', number, exc_info=True)
            continue
        result.append((number, memory))
    return result


class AssistantService:
    def __init__(self, radio, existing_memories=None):
        self.radio = radio
        self.capability = capability_mod.snapshot(radio)
        self.existing_memories = (
            existing_memories if existing_memories is not None
            else read_existing_memories(radio))

    def apply_policies(self, candidates, request):
        """Resolve final transmit/receive-only state for every
        candidate via policies.py. Mutates and returns @candidates."""
        for c in candidates:
            auth = policies.resolve_transmit_eligibility(
                c.service, c.freq, c.tx_freq, request, self.capability)
            forced_rx_only = (
                c.service in models.ALWAYS_RECEIVE_ONLY_SERVICES or
                c.service in request.receive_only_services)
            c.receive_only = forced_rx_only or not auth.transmit_enabled
            if c.receive_only and not c.reason:
                c.reason = auth.reason
        return candidates

    def build_plan(self, request, network_allowed=True):
        """Query sources, apply policy, and run the deterministic
        planner. Does NOT convert/validate against the destination
        radio yet -- see convert_and_validate(), which is a separate
        (still network-free) step so a UI can show "building plan..."
        then "validating..." as distinct progress phases."""
        errors = request.validate()
        if errors:
            raise ValueError('Invalid request: %s' % '; '.join(errors))

        candidates, source_warnings, skipped = sources.build_candidates(
            request, network_allowed=network_allowed)
        candidates = self.apply_policies(candidates, request)
        plan = planner.build_plan(
            candidates, request, self.capability, self.existing_memories)
        plan.warnings = source_warnings + plan.warnings
        plan.skipped_sources = skipped
        return plan

    def convert_and_validate(self, plan):
        """Run converter+validator on every currently-included
        candidate in @plan, mutating their status/warnings/errors in
        place. Returns {id(candidate): chirp_common.Memory} for the
        ones that converted successfully (validator may still have
        marked some of those STATUS_BLOCKED/include=False on hard
        validation errors -- callers wanting only apply-ready entries
        should filter on candidate.include)."""
        memories = {}
        for c in plan.all_candidates:
            if not c.include:
                continue
            memory = converter.convert_candidate(
                c, self.radio, self.capability)
            if memory is None:
                continue
            validator.validate_and_classify(c, memory, self.radio)
            memories[id(c)] = memory
        return memories

    def finalize_for_apply(self, plan):
        """Final, authoritative re-validation pass immediately before
        apply -- user edits made during review (renames, re-inclusion,
        etc.) can change what's valid, so this re-runs conversion and
        validation from scratch rather than trusting an earlier pass.

        Also re-checks each target memory's CURRENT occupancy on the
        radio against the baseline snapshot this service was
        constructed with (self.existing_memories): if the slot is
        occupied now but WASN'T (or held different content) in that
        baseline, something changed since the plan was built --
        a manual edit elsewhere, or re-finalizing an already-applied
        plan -- and the candidate is blocked here rather than
        silently overwriting whatever is there now. A slot that's
        occupied but UNCHANGED from the baseline is fine, including
        the case the planner already explicitly approved: an existing-
        conflict replacement (allow_duplicate_replacement) targets a
        slot that was already occupied in that same baseline, by
        definition unchanged from it at this point. (Checking the
        baseline directly, rather than candidate.status, is
        deliberate: convert_and_validate() above unconditionally
        reclassifies status from validation results and would
        otherwise clobber the planner's STATUS_EXISTING_CONFLICT
        marking before this method ever saw it.)

        Returns a list of (candidate, chirp_common.Memory) for exactly
        the candidates that are include=True and pass validation with
        no errors -- this is what chirp.wxui.programming_assistant
        should actually apply.
        """
        memories = self.convert_and_validate(plan)
        baseline_by_number = dict(self.existing_memories)
        result = []
        for c in plan.all_candidates:
            if not c.include or c.errors:
                continue
            memory = memories.get(id(c))
            if memory is None:
                continue
            current = self.radio.get_memory(memory.number)
            if not current.empty:
                baseline = baseline_by_number.get(memory.number)
                unchanged = (
                    baseline is not None and not baseline.empty and
                    baseline.freq == current.freq and
                    baseline.name == current.name)
                if not unchanged:
                    c.status = models.STATUS_BLOCKED
                    c.include = False
                    c.errors = c.errors + (
                        'Memory %s is now occupied and was not approved '
                        'for replacement -- skipped rather than '
                        'overwritten. Rebuild the plan to include it.' %
                        memory.number,)
                    continue
            result.append((c, memory))
        return result
