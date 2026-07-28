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

"""Final validation gate: chirp_common.RadioFeatures.validate_memory()
is authoritative here, exactly as it is for a normal hand-edit or a
pasted memory -- this module classifies its output into a preview
status, it never second-guesses or overrides it.

Status precedence (highest first): BLOCKED > RECEIVE_ONLY > ADJUSTED >
WARNING > READY. Candidates the planner already excluded (duplicate,
existing conflict, over capacity) are not touched here -- see
planner.py and service.py for that stage.
"""

from chirp import chirp_common
from chirp.assistant import models


def validate_and_classify(candidate, memory, radio):
    """Run @radio's authoritative validate_memory() against @memory
    (the already-converted destination-specific chirp_common.Memory for
    @candidate) and set candidate.status/.warnings/.errors accordingly.

    Must be called AFTER converter.convert_candidate() succeeds, and
    again immediately before apply (see service.py) since user edits in
    the review stage can change what's valid.
    """
    msgs = radio.validate_memory(chirp_common.FrozenMemory(memory))
    warnings, errors = chirp_common.split_validation_msgs(msgs)

    candidate.warnings = tuple(str(w) for w in warnings)
    candidate.errors = tuple(str(e) for e in errors)

    if candidate.errors:
        candidate.status = models.STATUS_BLOCKED
        candidate.include = False
    elif candidate.receive_only:
        candidate.status = models.STATUS_RECEIVE_ONLY
    elif candidate.adjustments:
        candidate.status = models.STATUS_ADJUSTED
    elif candidate.warnings:
        candidate.status = models.STATUS_WARNING
    else:
        candidate.status = models.STATUS_READY

    return candidate
