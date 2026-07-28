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

"""Normalizes a destination radio's chirp_common.RadioFeatures into a
small, testable snapshot. This is deliberately NOT a second manual
radio-capability database -- every value here is read straight off the
radio's own get_features(), never hardcoded per model.
"""

import dataclasses


@dataclasses.dataclass(frozen=True)
class CapabilitySnapshot:
    valid_bands: tuple
    valid_modes: tuple
    valid_tmodes: tuple
    valid_duplexes: tuple
    valid_tuning_steps: tuple
    valid_power_levels: tuple
    valid_characters: str
    valid_name_length: int
    valid_special_chans: tuple
    memory_bounds: tuple
    has_infinite_number: bool
    has_bank: bool
    has_variable_power: bool
    has_rx_dtcs: bool
    has_ctone: bool
    has_cross: bool
    requires_call_lists: bool
    can_odd_split: bool

    @property
    def supports_receive_only_duplex(self):
        """Whether "off" duplex (this codebase's receive-only
        convention -- see chirp_common.Memory.duplex) is representable
        on this radio at all. If not, a channel that policy requires to
        be receive-only must be BLOCKED, not approximated -- see
        policies.py."""
        return 'off' in self.valid_duplexes

    def supports_frequency(self, freq_hz):
        if not self.valid_bands:
            return True
        return any(lo <= freq_hz < hi for lo, hi in self.valid_bands)

    def supports_mode(self, mode):
        if not self.valid_modes:
            return True
        return mode in self.valid_modes

    def clamp_power(self, power_watts):
        """Return the closest supported power level to @power_watts, or
        None if the radio has no power-level concept at all."""
        if power_watts is None or not self.valid_power_levels:
            return None
        levels = [p for p in self.valid_power_levels if p is not None]
        if not levels:
            return None
        return min(levels, key=lambda p: abs(
            _watts(p) - _watts_value(power_watts)))


def _watts(power_level):
    # chirp_common.PowerLevel objects compare/convert via float(); a
    # plain number is already in watts.
    try:
        return float(power_level)
    except (TypeError, ValueError):
        return 0.0


def _watts_value(power_watts):
    try:
        return float(power_watts)
    except (TypeError, ValueError):
        return 0.0


def snapshot(radio):
    """Build a CapabilitySnapshot from an open chirp_common.Radio."""
    rf = radio.get_features()
    return CapabilitySnapshot(
        valid_bands=tuple(rf.valid_bands),
        valid_modes=tuple(rf.valid_modes),
        valid_tmodes=tuple(rf.valid_tmodes),
        valid_duplexes=tuple(rf.valid_duplexes),
        valid_tuning_steps=tuple(rf.valid_tuning_steps),
        valid_power_levels=tuple(rf.valid_power_levels),
        valid_characters=rf.valid_characters,
        valid_name_length=rf.valid_name_length,
        valid_special_chans=tuple(rf.valid_special_chans),
        memory_bounds=tuple(rf.memory_bounds),
        has_infinite_number=rf.has_infinite_number,
        has_bank=rf.has_bank,
        has_variable_power=rf.has_variable_power,
        has_rx_dtcs=rf.has_rx_dtcs,
        has_ctone=rf.has_ctone,
        has_cross=rf.has_cross,
        requires_call_lists=rf.requires_call_lists,
        can_odd_split=rf.can_odd_split,
    )
