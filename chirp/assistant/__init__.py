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

"""The AI Programming Assistant: turns a structured (optionally
natural-language-derived) request into a previewed, user-approved batch
of memories applied to the currently open radio image.

This package has no wx dependency and is independently unit-testable.
The wx-facing wizard lives in chirp.wxui.programming_assistant.

Trust boundaries, by design:

  - An optional AI provider (chirp.assistant.providers) is used ONLY to
    extract a structured request from natural language. It never
    supplies frequencies, tones, offsets, or any other technical
    channel fact, and its output is validated against a strict schema
    before use -- see providers.py.
  - All technical channel data comes from chirp.assistant.sources,
    which wraps either an existing trusted chirp.sources.* network
    adapter or a small curated static table. AI output is never used
    as a frequency database.
  - Every candidate memory is converted and validated through CHIRP's
    existing chirp.import_logic / RadioFeatures.validate_memory
    machinery (chirp.assistant.converter / validator) before it can
    ever be shown as "Ready" in the preview, let alone applied.
  - Nothing in this package opens a serial port, talks to radio
    hardware, or initiates an upload. It only ever writes to the
    already-open in-memory radio image, through the same
    ChirpMemEdit.set_memory()/undo_context() mechanism the rest of the
    memory editor uses, as one undoable action.
"""
