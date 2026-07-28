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

"""Converts a models.ChannelCandidate into a chirp_common.Memory for a
specific destination radio, using CHIRP's own chirp.import_logic as the
sole conversion authority -- this module does not reimplement any
duplex/tone/mode/power conversion logic of its own.

IMPORTANT: a candidate whose policy requires it to be receive-only, but
whose destination radio can't represent that (no "off" duplex support),
is BLOCKED here rather than converted -- import_logic._import_duplex
silently downgrades an unsupported "off" duplex to plain simplex ("")
for ordinary imports, which is exactly correct for a normal paste/import
but would be actively unsafe here: it would turn a channel policy says
must never transmit into an ordinary transmit-capable simplex channel.
See capability.CapabilitySnapshot.supports_receive_only_duplex.
"""

from chirp import chirp_common
from chirp import import_logic
from chirp.assistant import models
from chirp.assistant import provenance as provenance_mod


def tx_freq_from_memory(memory):
    """Return @memory's effective transmit frequency in Hz, or None if
    it has none (duplex 'off') -- the inverse of
    chirp_common.split_to_offset(). Shared by planner.py (existing-image
    conflict detection) and sources.py (converting a fetched Memory
    back into a ChannelCandidate)."""
    if memory.duplex == '+':
        return memory.freq + memory.offset
    if memory.duplex == '-':
        return memory.freq - memory.offset
    if memory.duplex == 'split':
        return memory.offset
    if memory.duplex == 'off':
        return None
    return memory.freq


def candidate_to_source_memory(candidate):
    """Build a plain, not-yet-destination-specific chirp_common.Memory
    from @candidate. This is the "source" memory import_logic.import_mem
    then converts for the actual destination radio."""
    mem = chirp_common.Memory()
    mem.number = (candidate.memory_number
                  if candidate.memory_number is not None else 0)
    mem.name = candidate.name or candidate.label
    mem.mode = candidate.mode
    mem.tuning_step = candidate.tuning_step
    mem.comment = candidate.label
    mem.power = candidate.power

    if candidate.receive_only:
        mem.freq = candidate.freq
        mem.duplex = 'off'
        mem.offset = 0
    elif candidate.tx_freq is not None and candidate.tx_freq != candidate.freq:
        chirp_common.split_to_offset(mem, candidate.freq, candidate.tx_freq)
    else:
        mem.freq = candidate.freq
        mem.duplex = ''
        mem.offset = 0

    mem.tmode = candidate.tmode
    mem.rtone = candidate.rtone
    mem.ctone = candidate.ctone
    mem.dtcs = candidate.dtcs
    mem.rx_dtcs = candidate.rx_dtcs
    mem.dtcs_polarity = candidate.dtcs_polarity
    return mem


def _permissive_source_features():
    """A RadioFeatures describing an idealized, maximally-capable
    "source" -- used only to tell import_logic's helpers "this data is
    already as good as it gets," so they don't spuriously downgrade
    fields assuming some hypothetical source radio's limitations. The
    REAL capability gate is always the destination radio's own
    validate_memory(), applied afterward."""
    rf = chirp_common.RadioFeatures()
    rf.valid_modes = list(chirp_common.MODES)
    rf.valid_tmodes = list(chirp_common.TONE_MODES)
    rf.valid_duplexes = ["", "-", "+", "off", "split"]
    rf.valid_tones = list(chirp_common.TONES)
    rf.valid_dtcs_codes = list(chirp_common.DTCS_CODES)
    rf.valid_power_levels = []
    rf.has_ctone = True
    rf.has_rx_dtcs = True
    rf.has_cross = True
    rf.valid_bands = []
    return rf


def convert_candidate(candidate, radio, cap_snapshot):
    """Attempt to convert @candidate for @radio (whose capability
    snapshot is @cap_snapshot, from capability.snapshot(radio)).

    Mutates and returns @candidate: sets .status, .warnings, .errors,
    .adjustments, and (on success) leaves a converted chirp_common.Memory
    accessible by re-deriving it -- callers needing the Memory object
    itself should call this then chirp.assistant.validator.validate() to
    get both in one pass; see service.py.
    """
    if (candidate.receive_only and
            not cap_snapshot.supports_receive_only_duplex):
        candidate.status = models.STATUS_UNSUPPORTED_BY_RADIO
        candidate.include = False
        candidate.errors = candidate.errors + (
            'This radio cannot represent a receive-only channel '
            '(no "off" duplex support); blocked rather than risk making '
            'it transmit-capable.',)
        return None

    src_mem = candidate_to_source_memory(candidate)
    src_features = _permissive_source_features()

    try:
        dst_mem = import_logic.import_mem(
            radio, src_features, src_mem, strict=False)
    except (import_logic.ImportError, chirp_common.ImmutableValueError) as e:
        candidate.status = models.STATUS_BLOCKED
        candidate.include = False
        candidate.errors = candidate.errors + (str(e),)
        return None

    adjustments = []
    if dst_mem.name != src_mem.name:
        adjustments.append('name')
    if dst_mem.mode != src_mem.mode:
        adjustments.append('mode')
    if dst_mem.power != src_mem.power:
        adjustments.append('power')
    if dst_mem.duplex != src_mem.duplex or dst_mem.offset != src_mem.offset:
        adjustments.append('duplex/offset')
    if (dst_mem.rtone, dst_mem.ctone) != (src_mem.rtone, src_mem.ctone):
        adjustments.append('tone')
    if (dst_mem.dtcs, dst_mem.rx_dtcs) != (src_mem.dtcs, src_mem.rx_dtcs):
        adjustments.append('dtcs')

    # import_mem's own downgrade of an unsupported "off" duplex to
    # simplex is exactly the unsafe case described in this module's
    # docstring -- the pre-check above should have already blocked this
    # candidate, so treat it reaching here as an invariant violation
    # rather than silently accepting a now-transmit-capable channel.
    if candidate.receive_only and dst_mem.duplex != 'off':
        candidate.status = models.STATUS_UNSUPPORTED_BY_RADIO
        candidate.include = False
        candidate.errors = candidate.errors + (
            'Receive-only representation was not preserved by '
            'conversion; blocked for safety.',)
        return None

    if adjustments:
        candidate.adjustments = tuple(adjustments)
        for field in adjustments:
            candidate.provenance = provenance_mod.note_conversion_adjustment(
                candidate.provenance, field)

    return dst_mem
