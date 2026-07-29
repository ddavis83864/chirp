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

"""The apply-profile preview dialog (sections 14/15).

Shows a chirp.profiles.changeset.ChangeSet already built by
chirp.wxui.profilecontroller and lets the user filter, inspect,
approve, or reject individual items. This dialog never mutates the
open image itself -- closing it with Cancel (or the window's close
box) leaves the image completely untouched; the caller only applies
anything after ShowModal() returns wx.ID_OK, via
profilecontroller.apply_changeset().
"""

import logging

import wx

from chirp.profiles import schema

_ = wx.GetTranslation

LOG = logging.getLogger(__name__)

_ACTION_LABELS = {
    schema.ACTION_ADD: _('Add'),
    schema.ACTION_MODIFY: _('Modify'),
    schema.ACTION_KEEP: _('Keep'),
    schema.ACTION_SKIP: _('Skip'),
    schema.ACTION_MOVE: _('Move'),
    schema.ACTION_CONFLICT: _('Conflict'),
    schema.ACTION_BLOCKED: _('Blocked'),
}
_CLASS_LABELS = {
    schema.CLASS_EXACT: _('Exact'),
    schema.CLASS_ADAPTED: _('Adapted'),
    schema.CLASS_DEGRADED: _('Degraded'),
    schema.CLASS_INCOMPATIBLE: _('Incompatible'),
    schema.CLASS_UNSAFE: _('Unsafe'),
}
_APPROVAL_LABELS = {
    schema.APPROVAL_PENDING: _('Pending'),
    schema.APPROVAL_APPROVED: _('Approved'),
    schema.APPROVAL_REJECTED: _('Rejected'),
    schema.APPROVAL_BLOCKED: _('Blocked'),
}

_FILTER_ALL = _('All')


class ProfileApplyPreviewDialog(wx.Dialog):
    def __init__(self, parent, change_set):
        super().__init__(
            parent,
            title=_('Apply Profile: %s') % change_set.profile_name,
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.change_set = change_set

        self.filter_choice = wx.Choice(
            self, choices=[_FILTER_ALL] + [
                _ACTION_LABELS[a] for a in (
                    schema.ACTION_ADD, schema.ACTION_MODIFY,
                    schema.ACTION_KEEP, schema.ACTION_SKIP,
                    schema.ACTION_CONFLICT, schema.ACTION_BLOCKED)])
        self.filter_choice.SetSelection(0)
        self.filter_choice.Bind(wx.EVT_CHOICE, self._on_filter_changed)

        self.item_list = wx.ListCtrl(self, style=wx.LC_REPORT)
        for col in (
                _('Logical ID'), _('Action'), _('Result'), _('Approval'),
                _('Message')):
            self.item_list.AppendColumn(col)
        self.item_list.Bind(wx.EVT_LIST_ITEM_SELECTED, self._on_item_selected)

        self.detail_text = wx.TextCtrl(
            self, style=wx.TE_MULTILINE | wx.TE_READONLY, size=(-1, 100))

        self.approve_btn = wx.Button(self, label=_('Approve'))
        self.reject_btn = wx.Button(self, label=_('Reject'))
        self.approve_btn.Bind(wx.EVT_BUTTON, self._on_approve)
        self.reject_btn.Bind(wx.EVT_BUTTON, self._on_reject)

        self.summary_text = wx.StaticText(self, label='')

        action_sizer = wx.BoxSizer(wx.HORIZONTAL)
        action_sizer.Add(wx.StaticText(self, label=_('Filter:')),
                         0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        action_sizer.Add(self.filter_choice, 0)
        action_sizer.AddStretchSpacer()
        action_sizer.Add(self.approve_btn, 0, wx.RIGHT, 4)
        action_sizer.Add(self.reject_btn, 0)

        ok_cancel = self.CreateButtonSizer(wx.OK | wx.CANCEL)
        self._ok_button = self.FindWindowById(wx.ID_OK)
        if self._ok_button:
            self._ok_button.SetLabel(_('Apply'))

        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(action_sizer, 0, wx.EXPAND | wx.ALL, 8)
        outer.Add(self.item_list, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)
        outer.Add(wx.StaticText(self, label=_('Details:')),
                  0, wx.LEFT | wx.RIGHT | wx.TOP, 8)
        outer.Add(self.detail_text, 0, wx.EXPAND | wx.ALL, 8)
        outer.Add(self.summary_text, 0, wx.LEFT | wx.RIGHT, 8)
        outer.Add(ok_cancel, 0, wx.EXPAND | wx.ALL, 8)
        self.SetSizerAndFit(outer)
        self.SetSize((760, 620))

        self.Bind(wx.EVT_BUTTON, self._on_apply, id=wx.ID_OK)
        self._refresh()

    # --- filtering / listing ----------------------------------------------

    def _visible_items(self):
        selection = self.filter_choice.GetSelection()
        if selection <= 0:
            return list(self.change_set.items)
        label = self.filter_choice.GetString(selection)
        action = next(a for a, lbl in _ACTION_LABELS.items() if lbl == label)
        return [i for i in self.change_set.items if i.action == action]

    def _on_filter_changed(self, event):
        self._refresh()

    def _refresh(self):
        self.item_list.DeleteAllItems()
        for item in self._visible_items():
            index = self.item_list.InsertItem(
                self.item_list.GetItemCount(), item.logical_id)
            self.item_list.SetItem(
                index, 1, _ACTION_LABELS.get(item.action, item.action))
            self.item_list.SetItem(
                index, 2, _CLASS_LABELS.get(item.classification,
                                            item.classification))
            self.item_list.SetItem(
                index, 3, _APPROVAL_LABELS.get(item.approval_state,
                                               item.approval_state))
            self.item_list.SetItem(index, 4, item.message)
        self._update_summary()

    def _update_summary(self):
        counts = self.change_set.summary()
        parts = ['%s: %d' % (_ACTION_LABELS.get(a, a), n)
                 for a, n in sorted(counts.items())]
        approved = len(self.change_set.approved_items())
        self.summary_text.SetLabel(
            _('%(counts)s -- %(approved)d item(s) approved for apply') % {
                'counts': ', '.join(parts), 'approved': approved})

    def _selected_item(self):
        index = self.item_list.GetFirstSelected()
        if index == wx.NOT_FOUND:
            return None
        visible = self._visible_items()
        if index >= len(visible):
            return None
        return visible[index]

    def _on_item_selected(self, event):
        item = self._selected_item()
        if item is None:
            self.detail_text.SetValue('')
            return
        lines = [
            _('Logical ID: %s') % item.logical_id,
            _('Action: %s') % _ACTION_LABELS.get(item.action, item.action),
            _('Classification: %s') % _CLASS_LABELS.get(
                item.classification, item.classification),
            _('Reason: %s') % item.reason_code,
            item.message,
        ]
        if item.lost:
            lines.append(_('Lost information: %s') % ', '.join(item.lost))
        if item.conflicts:
            lines.append(_('Conflicts:'))
            for c in item.conflicts:
                lines.append('  - %s' % c.message)
        if item.blocked:
            lines.append(
                _('This change is BLOCKED for safety and cannot be '
                  'approved.'))
        self.detail_text.SetValue('\n'.join(lines))

    # --- approve / reject --------------------------------------------

    def _on_approve(self, event):
        self._set_selected_approval(schema.APPROVAL_APPROVED)

    def _on_reject(self, event):
        self._set_selected_approval(schema.APPROVAL_REJECTED)

    def _set_selected_approval(self, state):
        indices = []
        index = self.item_list.GetFirstSelected()
        while index != wx.NOT_FOUND:
            indices.append(index)
            index = self.item_list.GetNextSelected(index)
        visible = self._visible_items()
        for i in indices:
            if i >= len(visible):
                continue
            item = visible[i]
            if item.blocked:
                continue
            self.change_set.set_approval(item.logical_id, state)
        self._refresh()

    # --- apply ---------------------------------------------------------

    def _on_apply(self, event):
        if not self.change_set.approved_items():
            answer = wx.MessageBox(
                _('No changes are approved. Close without applying '
                  'anything?'),
                _('Nothing to Apply'), wx.YES_NO | wx.ICON_QUESTION, self)
            if answer != wx.YES:
                return
        event.Skip()
