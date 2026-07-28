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

"""The sole UI/domain boundary for Radio Profiles (section 3.4).

Dialogs and menu handlers in chirp.wxui.profileeditor/profileapply/
main.py must call into chirp.profiles.* only through the functions
here -- never construct chirp.profiles domain objects or run
adaptation/matching/placement logic directly in event handlers.

This module *does* import wx-adjacent CHIRP modules (memedit, for the
editor/undo integration) and is therefore not part of the pure-Python
domain layer itself; it is the glue between that layer and the GUI.
"""

import logging

import wx

from chirp import chirp_common
from chirp.profiles import capabilities
from chirp.profiles import changeset as changeset_mod
from chirp.profiles import errors as profile_errors
from chirp.profiles import extraction
from chirp.profiles import schema as profile_schema
from chirp.wxui import memedit

_ = wx.GetTranslation

LOG = logging.getLogger(__name__)


def get_memedit(editorset):
    """Return the ChirpMemEdit for @editorset's primary memory tab.

    Radios with sub-devices may have more than one; the first release
    only operates on one at a time (whichever is currently selected, or
    the first available), matching how e.g. CSV export already works
    per-editor rather than per-editorset.
    """
    editor = editorset.current_editor
    if isinstance(editor, memedit.ChirpMemEdit):
        return editor
    for _title, other in editorset.iter_editors(onlycls=memedit.ChirpMemEdit):
        return other
    return None


def enumerate_memories(radio):
    """Read every memory (including empty slots) off @radio.

    Pure read access -- never called from inside an apply transaction.
    """
    features = radio.get_features()
    if features.has_infinite_number:
        raise profile_errors.CapabilityUnknownError(
            'This radio has no fixed memory count; enumerating all '
            'memories is not supported')
    lo, hi = features.memory_bounds
    memories = []
    for number in range(lo, hi + 1):
        try:
            memories.append(radio.get_memory(number))
        except Exception as e:
            LOG.warning('Failed to read memory %s: %s', number, e)
    return memories


def create_profile_from_editorset(editorset, name='', description='',
                                  region=None):
    """Extract a Profile from @editorset's currently-open image.

    :returns: a chirp.profiles.extraction.ExtractionResult.
    """
    radio = editorset.radio
    memories = enumerate_memories(radio)
    return extraction.extract_profile(
        radio, memories, name=name, description=description, region=region)


def build_changeset_for_editorset(
        profile, editorset,
        placement_strategy=profile_schema.PLACEMENT_FILL_EMPTY,
        explicit_range=None):
    """Build the proposed ChangeSet for applying @profile to
    @editorset's currently-open image. Does not modify the image.
    """
    radio = editorset.radio
    caps = capabilities.for_radio(radio)
    existing = enumerate_memories(radio)
    return changeset_mod.build_changeset(
        profile, caps, existing, placement_strategy=placement_strategy,
        explicit_range=explicit_range)


def apply_changeset(memedit_widget, profile_name, change_set):
    """Apply every approved item in @change_set to @memedit_widget's
    radio as a single undoable transaction (section 15).

    Validates every approved item against the driver's own
    RadioFeatures.validate_memory *again* immediately before touching
    anything (section 15.2) -- if any fails, nothing is applied at all.
    Applies through memedit's existing undo_context, so the whole
    transaction appears as one entry ("Apply <profile_name> profile")
    in the normal Undo menu. If applying any individual item raises
    unexpectedly partway through (should not happen after the
    pre-validation pass), everything already applied in this
    transaction is explicitly reversed and errors.TransactionError is
    raised; the image is left as it was before apply() was called.

    :raises profile_errors.ProfileValidationError: pre-validation caught
        a problem; nothing was applied.
    :raises profile_errors.TransactionError: a mid-apply failure was
        rolled back; nothing remains applied.
    """
    approved = change_set.approved_items()
    if not approved:
        return

    caps = capabilities.for_radio(memedit_widget._radio)
    issues = []
    for item in approved:
        msgs = caps.validate_memory(item.proposed_memory)
        errors_only = [
            m for m in msgs
            if isinstance(m, chirp_common.ValidationError)
        ]
        if errors_only:
            issues.append(profile_schema.Issue(
                'channels[%s]' % item.logical_id,
                '; '.join(str(m) for m in errors_only)))
    if issues:
        raise profile_errors.ProfileValidationError(issues)

    applied = []
    undo_name = _('Apply %s profile') % profile_name
    try:
        with memedit_widget.undo_context(undo_name):
            for item in approved:
                mem = item.proposed_memory.dupe()
                mem.number = item.target_memory_number
                memedit_widget.set_memory(mem, refresh=False)
                applied.append(item)
    except Exception as e:
        LOG.error('Profile apply failed after %d/%d items applied: %s',
                  len(applied), len(approved), e)
        _rollback(memedit_widget, applied)
        raise profile_errors.TransactionError(
            'Applying the profile failed (%s); all changes from this '
            'attempt have been reverted and the image is unchanged.' %
            (e,))
    finally:
        memedit_widget.refresh()


def _rollback(memedit_widget, applied_items):
    """Best-effort manual reversal of a partially-applied transaction.

    Only reachable if a driver raises unexpectedly *after* every
    proposed memory already passed RadioFeatures.validate_memory --
    normal validation failures never reach this path since
    apply_changeset() validates everything before applying anything.
    """
    try:
        with memedit_widget.undo_context(_('Revert failed profile apply')):
            for item in reversed(applied_items):
                existing = item.existing_memory
                if existing is not None:
                    memedit_widget.set_memory(existing.dupe(), refresh=False)
                else:
                    memedit_widget.erase_memory(
                        item.target_memory_number, refresh=False)
    except Exception:
        LOG.exception('Rollback of failed profile apply also failed; '
                      'image may be left partially modified')
    finally:
        memedit_widget.refresh()
