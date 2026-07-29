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

"""A read-only view of what a target radio driver can represent.

This wraps chirp_common.RadioFeatures -- CHIRP's own, already-existing
capability declaration mechanism -- instead of checking vendor/model
name strings (section 7 of the design doc explicitly requires this).

A note on "unknown" vs "not restricted": RadioFeatures' own convention
(see RadioFeatures.validate_memory) is that an empty valid_* list means
the driver author did not declare a restriction on that axis, i.e. it
is *not checked* -- treated the same as "anything goes" everywhere
else in CHIRP. This module follows that same convention rather than
inventing a stricter meaning for it, since a driver's own validate_memory
(delegated to via .validate_memory() below, and always re-run before
any mutation per section 9.9) remains the final, authoritative check
regardless of what this module concludes. "Unknown" here is reserved
for the small number of things RadioFeatures does not model at all
(scan lists as a distinct concept, empty-memory behavior); those
methods always return None, and callers must fail closed on None
rather than assume support (see chirp.profiles.safety.
check_capability_known).
"""


class TargetCapabilities:
    """Adapts one open chirp_common.Radio's declared features."""

    def __init__(self, radio):
        self.radio = radio
        self.features = radio.get_features()

    # --- memory layout ---------------------------------------------------

    @property
    def memory_bounds(self):
        """(lo, hi) inclusive memory numbers, or None if unbounded."""
        if self.features.has_infinite_number:
            return None
        return self.features.memory_bounds

    @property
    def num_memories(self):
        """Total addressable regular memory slots, or None if unbounded."""
        bounds = self.memory_bounds
        if bounds is None:
            return None
        lo, hi = bounds
        return hi - lo + 1

    @property
    def valid_special_channels(self):
        return list(self.features.valid_special_chans)

    # --- frequency / duplex ------------------------------------------------

    @property
    def valid_bands(self):
        """List of (lo_hz, hi_hz) receive bands, or None if not
        restricted (see module docstring)."""
        return list(self.features.valid_bands) or None

    def frequency_in_band(self, freq_hz):
        bands = self.valid_bands
        if bands is None:
            return True
        return any(lo <= freq_hz < hi for lo, hi in bands)

    @property
    def valid_duplexes(self):
        return list(self.features.valid_duplexes)

    def supports_duplex(self, duplex):
        return duplex in self.valid_duplexes

    def can_enforce_receive_only(self):
        """True if this target has a way to represent "no transmit" at
        all. If False, a receive-only profile channel cannot be safely
        placed on this radio (see safety.py: this is Unsafe, blocked,
        not a dismissable warning)."""
        return 'off' in self.valid_duplexes

    # --- modes / tones -----------------------------------------------------

    @property
    def valid_modes(self):
        return list(self.features.valid_modes) or None

    def supports_mode(self, mode):
        valid = self.valid_modes
        return valid is None or mode in valid

    @property
    def valid_tone_modes(self):
        return list(self.features.valid_tmodes) or None

    def supports_tone_mode(self, tmode):
        if not tmode:
            return True
        valid = self.valid_tone_modes
        return valid is None or tmode in valid

    def supports_dtcs(self):
        return bool(self.features.has_dtcs)

    def supports_rx_dtcs(self):
        return bool(self.features.has_rx_dtcs)

    @property
    def valid_dtcs_codes(self):
        return list(self.features.valid_dtcs_codes) or None

    # --- power ---------------------------------------------------------

    @property
    def valid_power_levels(self):
        """Sorted list of chirp_common.PowerLevel, or None if this
        target has no selectable power levels (nothing to lose)."""
        levels = list(self.features.valid_power_levels)
        if not levels:
            return None
        return sorted(levels, key=float)

    # --- naming ---------------------------------------------------------

    def supports_names(self):
        return bool(self.features.has_name)

    @property
    def name_length(self):
        return self.features.valid_name_length if self.supports_names() else 0

    @property
    def valid_characters(self):
        return self.features.valid_characters if self.supports_names() else ''

    def supports_comment(self):
        return bool(self.features.has_comment)

    # --- organization -----------------------------------------------------

    def supports_banks(self):
        return bool(self.features.has_bank)

    def supports_named_banks(self):
        return bool(self.features.has_bank_names)

    @property
    def valid_skips(self):
        return list(self.features.valid_skips) or None

    def supports_skip(self, skip):
        if not skip:
            return True
        valid = self.valid_skips
        return valid is None or skip in valid

    def can_delete(self):
        return bool(self.features.can_delete)

    # --- explicitly not modeled by RadioFeatures ---------------------------

    def scan_list_support(self):
        """RadioFeatures has no concept of a scan list distinct from
        per-memory skip/priority; always unknown."""
        return None

    def empty_memory_behavior(self):
        """RadioFeatures does not declare what an empty memory slot
        looks like on read-back; always unknown."""
        return None

    # --- validation delegation -----------------------------------------

    def validate_memory(self, memory):
        """Delegates to the driver's own RadioFeatures.validate_memory
        -- the authoritative safety net that must be re-run immediately
        before any mutation (section 9.9), independent of whatever this
        module's own classification concluded.
        """
        return self.features.validate_memory(memory)


def immutable_fields(memory):
    """Fields the driver has marked as not settable on this specific,
    already-existing memory instance (e.g. a fixed/special channel).
    This is per-memory, not a general radio-class capability, so it is
    a plain function rather than a TargetCapabilities method.
    """
    return list(memory.immutable)


def for_radio(radio):
    return TargetCapabilities(radio)
