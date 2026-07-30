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
from chirp.wxui import common as wx_common
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

    Thin wrapper over the pure-Python
    chirp.profiles.extraction.enumerate_source_memories() -- kept here
    too since it is this module's established entry point for both
    callers below, and so existing callers/tests referring to
    chirp.wxui.profilecontroller.enumerate_memories keep working.
    """
    return extraction.enumerate_source_memories(radio)


def create_profile_from_editorset(editorset, name='', description='',
                                  region=None):
    """Extract a Profile from @editorset's currently-open image.

    :returns: a chirp.profiles.extraction.ExtractionResult.
    :raises profile_errors.NoPopulatedMemoriesError: the image has no
        populated memories (every enumerable slot is empty or a
        special channel) -- nothing to build a profile from.
    """
    radio = editorset.radio
    memories = enumerate_memories(radio)
    result = extraction.extract_profile(
        radio, memories, name=name, description=description, region=region)
    if result.summary.channels_extracted == 0:
        raise profile_errors.NoPopulatedMemoriesError(
            _('No populated memories are available to create a '
              'profile.'))
    return result


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


def _is_live_radio(memedit_widget):
    """True if @memedit_widget queues radio I/O to a background thread
    (a live, serial-connected radio) rather than executing it
    synchronously in the calling thread (an opened image file).

    This matters because memedit.ChirpMemEdit.set_memory() goes through
    do_radio(), which -- for *both* editor kinds -- catches whatever the
    driver raises and stores it on the job object rather than
    re-raising it to the caller (it only surfaces as a per-row error
    indicator in the grid). For a synchronous, file-backed image, this
    module calls the radio directly instead so a driver failure raises
    here and can actually be rolled back (section 15). That would be
    unsafe for a live radio (the async editor's contract is that only
    its own worker thread touches the radio object), so live-radio
    targets keep going through set_memory()/erase_memory() as normal --
    matching the same semantics every other existing bulk edit in CHIRP
    already has for a live radio (queued jobs, per-row error indication,
    one Undo entry; no synchronous rollback guarantee). See
    docs/profiles.md.
    """
    return isinstance(memedit_widget, wx_common.ChirpAsyncEditor)


def _set_memory(memedit_widget, mem, live):
    if live:
        memedit_widget.set_memory(mem, refresh=False)
    else:
        memedit_widget._undo_ctx.record_current_memory(mem.number)
        memedit_widget._radio.set_memory(mem)


def _erase_memory(memedit_widget, number, live):
    if live:
        memedit_widget.erase_memory(number, refresh=False)
    else:
        memedit_widget._undo_ctx.record_current_memory(number)
        memedit_widget._radio.erase_memory(number)


def apply_changeset(memedit_widget, profile_name, change_set):
    """Apply every approved item in @change_set to @memedit_widget's
    radio as a single undoable transaction (section 15).

    Validates every approved item against the driver's own
    RadioFeatures.validate_memory *again* immediately before touching
    anything (section 15.2) -- if any fails, nothing is applied at all.
    Applies through memedit's existing undo_context, so the whole
    transaction appears as one entry ("Apply <profile_name> profile")
    in the normal Undo menu. For a synchronous (file-backed image)
    target, if applying any individual item raises unexpectedly
    partway through (should not happen after the pre-validation pass),
    everything already applied in this transaction is explicitly
    reversed and errors.TransactionError is raised; the image is left
    as it was before apply() was called. See _is_live_radio() for why
    this guarantee does not extend to a live serial-connected radio.

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

    live = _is_live_radio(memedit_widget)
    applied = []
    undo_name = _('Apply %s profile') % profile_name
    try:
        with memedit_widget.undo_context(undo_name):
            for item in approved:
                mem = item.proposed_memory.dupe()
                mem.number = item.target_memory_number
                _set_memory(memedit_widget, mem, live)
                applied.append(item)
    except Exception as e:
        LOG.error('Profile apply failed after %d/%d items applied: %s',
                  len(applied), len(approved), e)
        _rollback(memedit_widget, applied, live)
        raise profile_errors.TransactionError(
            'Applying the profile failed (%s); all changes from this '
            'attempt have been reverted and the image is unchanged.' %
            (e,))
    finally:
        memedit_widget.refresh()


def _rollback(memedit_widget, applied_items, live):
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
                    _set_memory(memedit_widget, existing.dupe(), live)
                else:
                    _erase_memory(
                        memedit_widget, item.target_memory_number, live)
    except Exception:
        LOG.exception('Rollback of failed profile apply also failed; '
                      'image may be left partially modified')
    finally:
        memedit_widget.refresh()
