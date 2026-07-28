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

"""Radio Profiles: portable, radio-neutral operational intent.

A CHIRP *image* is the current device-specific contents of one radio. A
*profile* (this package) is the user's portable intent -- channels,
groups, priorities, scan behavior, safety restrictions, and defaults --
which CHIRP can adapt to different supported radios. The two are
deliberately separate domain objects and separate file formats; nothing
here reads or writes an existing image format, and existing image
load/save/download/upload behavior is unaffected.

This package is pure Python: no wxPython import anywhere below this
line. The wx integration (chirp/wxui/profile*.py) calls into this
package through a service/controller boundary
(chirp.wxui.profilecontroller) and is the only layer that knows about
dialogs, grids, or the undo stack.

Module map:
  errors.py        typed exceptions for every expected failure mode
  schema.py        wire-format constants, enums, versioning, Issue type
  model.py         the canonical dataclasses (Profile, ProfileChannel, ...)
  validation.py    structural + semantic validation, collecting all
                   problems as schema.Issue with a field path
  serialization.py JSON (de)serialization, atomic save/load
  safety.py        preservation of explicit receive-only intent
  capabilities.py  reads a target radio's declared RadioFeatures
  adaptation.py    per-channel classification (Exact/Adapted/Degraded/
                   Incompatible/Unsafe) and value adaptation
  matching.py      matches profile channels against existing memories in
                   an open image (exact/update/ambiguous/none)
  placement.py     memory-number placement strategies
  conflicts.py     structured conflict objects
  changeset.py     ties matching+placement+adaptation+conflicts together
                   into one deterministic, previewable ChangeSet
  composition.py   (reserved) base/overlay profile composition -- the
                   schema/model leave room for it, but full multi-
                   profile composition is out of scope for this release
  extraction.py    builds a Profile from an already-open CHIRP image

See docs/profiles.md for the full architecture writeup.
"""
