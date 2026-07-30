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

"""The Radio Profile editor dialog (section 18).

All domain logic (validation, model construction) lives in
chirp.profiles.*; this module only renders it and translates widget
events into calls against that layer -- no compatibility/adaptation/
placement logic belongs here (section 3.4).
"""

import logging
import os

import wx
import wx.lib.scrolledpanel

from chirp import chirp_common
from chirp.profiles import errors as profile_errors
from chirp.profiles import model
from chirp.profiles import schema
from chirp.profiles import validation

_ = wx.GetTranslation

LOG = logging.getLogger(__name__)

_TRANSMIT_MODE_LABELS = {
    schema.TRANSMIT_ENABLED: _('Transmit enabled'),
    schema.TRANSMIT_RECEIVE_ONLY: _('Receive-only'),
    schema.TRANSMIT_UNSPECIFIED: _('Unspecified'),
}
_DUPLEX_LABELS = {
    schema.DUPLEX_NONE: _('Simplex'),
    schema.DUPLEX_POSITIVE: _('+ offset'),
    schema.DUPLEX_NEGATIVE: _('- offset'),
    schema.DUPLEX_SPLIT: _('Split'),
}
_UNSET = _('(inherit default)')


def _choice(parent, options, labels=None, selected=None):
    display = [labels.get(o, o) if labels else o for o in options]
    ctrl = wx.Choice(parent, choices=display)
    if selected in options:
        ctrl.SetSelection(options.index(selected))
    elif display:
        ctrl.SetSelection(0)
    ctrl._profile_options = options
    return ctrl


def _choice_value(ctrl):
    i = ctrl.GetSelection()
    if i == wx.NOT_FOUND:
        return None
    return ctrl._profile_options[i]


def _freq_ctrl(panel, freq_hz):
    text = chirp_common.format_freq(freq_hz) if freq_hz else ''
    return wx.TextCtrl(panel, value=text)


class ChannelEditDialog(wx.Dialog):
    """Add/edit one chirp.profiles.model.ProfileChannel."""

    def __init__(self, parent, profile, channel=None):
        super().__init__(parent, title=_('Profile Channel'),
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self._profile = profile
        self._orig_channel = channel
        channel = channel or model.ProfileChannel(logical_id='')

        panel = wx.lib.scrolledpanel.ScrolledPanel(self)
        grid = wx.FlexGridSizer(2, gap=(8, 4))
        grid.AddGrowableCol(1)

        def row(label, ctrl):
            grid.Add(wx.StaticText(panel, label=label),
                     0, wx.ALIGN_CENTER_VERTICAL)
            grid.Add(ctrl, 1, wx.EXPAND)

        self.logical_id = wx.TextCtrl(panel, value=channel.logical_id)
        row(_('Logical ID'), self.logical_id)

        self.name = wx.TextCtrl(panel, value=channel.name)
        row(_('Name'), self.name)

        self.comment = wx.TextCtrl(panel, value=channel.comment)
        row(_('Comment'), self.comment)

        self.freq = _freq_ctrl(panel, channel.rx_freq_hz)
        row(_('Receive Frequency (MHz)'), self.freq)

        self.transmit_mode = _choice(
            panel, list(schema.VALID_TRANSMIT_MODES),
            labels=_TRANSMIT_MODE_LABELS, selected=channel.transmit.mode)
        row(_('Transmit'), self.transmit_mode)

        self.duplex = _choice(
            panel, list(schema.VALID_DUPLEXES), labels=_DUPLEX_LABELS,
            selected=channel.transmit.duplex)
        row(_('Duplex'), self.duplex)

        self.offset = _freq_ctrl(panel, channel.transmit.offset_hz)
        row(_('Offset (MHz)'), self.offset)

        self.tx_freq = _freq_ctrl(panel, channel.transmit.tx_freq_hz)
        row(_('Split Transmit Frequency (MHz)'), self.tx_freq)

        self.tone_mode = _choice(
            panel, list(schema.VALID_TONE_MODES),
            labels={'': _('(none)')}, selected=channel.tone_mode)
        row(_('Tone Mode'), self.tone_mode)

        self.rtone = wx.TextCtrl(panel, value=str(channel.rtone))
        row(_('Transmit Tone (Hz)'), self.rtone)

        self.ctone = wx.TextCtrl(panel, value=str(channel.ctone))
        row(_('Receive Tone (Hz)'), self.ctone)

        self.dtcs = wx.TextCtrl(panel, value=str(channel.dtcs))
        row(_('DTCS Code'), self.dtcs)

        self.mode = _choice(
            panel, [_UNSET] + list(schema.VALID_MODES),
            selected=channel.mode or _UNSET)
        row(_('Mode'), self.mode)

        self.power_tier = _choice(
            panel, [_UNSET] + list(schema.VALID_POWER_TIERS),
            selected=channel.power_preference.tier or _UNSET)
        row(_('Power Preference'), self.power_tier)

        self.scan_intent = _choice(
            panel, [_UNSET] + list(schema.VALID_SCAN_INTENTS),
            selected=channel.scan_intent or _UNSET)
        row(_('Scan Intent'), self.scan_intent)

        self.category = wx.TextCtrl(panel, value=channel.category or '')
        row(_('Category'), self.category)

        group_choices = sorted(profile.groups)
        self.groups = wx.CheckListBox(panel, choices=group_choices)
        for i, gid in enumerate(group_choices):
            self.groups.Check(i, gid in channel.groups)
        row(_('Groups'), self.groups)

        panel.SetSizer(grid)
        panel.SetupScrolling()

        buttons = self.CreateButtonSizer(wx.OK | wx.CANCEL)
        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(panel, 1, wx.EXPAND | wx.ALL, 8)
        outer.Add(buttons, 0, wx.EXPAND | wx.ALL, 8)
        self.SetSizerAndFit(outer)
        self.SetSize((480, 640))

        self.Bind(wx.EVT_BUTTON, self._on_ok, id=wx.ID_OK)

    def _on_ok(self, event):
        try:
            self.result_channel = self.build_channel()
        except (ValueError, profile_errors.ProfileError) as e:
            wx.MessageBox(str(e), _('Invalid Channel'),
                          wx.OK | wx.ICON_ERROR, self)
            return
        event.Skip()

    def build_channel(self):
        logical_id = self.logical_id.GetValue().strip()
        if not schema.is_valid_logical_id(logical_id):
            raise ValueError(
                _('Logical ID must be a lowercase slug (letters, digits, '
                  'single hyphens), e.g. "local-2m-repeater-01"'))
        try:
            rx_freq_hz = chirp_common.parse_freq(self.freq.GetValue())
        except ValueError:
            raise ValueError(_('Invalid receive frequency'))

        duplex = _choice_value(self.duplex)
        offset_hz = 0
        tx_freq_hz = None
        if duplex in (schema.DUPLEX_POSITIVE, schema.DUPLEX_NEGATIVE):
            offset_hz = chirp_common.parse_freq(
                self.offset.GetValue() or '0')
        elif duplex == schema.DUPLEX_SPLIT:
            tx_freq_hz = chirp_common.parse_freq(self.tx_freq.GetValue())

        mode = _choice_value(self.mode)
        power_tier = _choice_value(self.power_tier)
        scan_intent = _choice_value(self.scan_intent)
        selected_groups = tuple(
            gid for i, gid in enumerate(sorted(self._profile.groups))
            if self.groups.IsChecked(i))

        return model.ProfileChannel(
            logical_id=logical_id,
            name=self.name.GetValue(),
            comment=self.comment.GetValue(),
            rx_freq_hz=rx_freq_hz,
            transmit=model.TransmitBehavior(
                mode=_choice_value(self.transmit_mode), duplex=duplex,
                offset_hz=offset_hz, tx_freq_hz=tx_freq_hz),
            tone_mode=_choice_value(self.tone_mode),
            rtone=float(self.rtone.GetValue() or 88.5),
            ctone=float(self.ctone.GetValue() or 88.5),
            dtcs=int(self.dtcs.GetValue() or 23),
            mode=None if mode == _UNSET else mode,
            power_preference=model.PowerPreference(
                tier=None if power_tier == _UNSET else power_tier),
            scan_intent=None if scan_intent == _UNSET else scan_intent,
            category=self.category.GetValue() or None,
            groups=selected_groups,
            source=(
                self._orig_channel.source if self._orig_channel else {}),
            overrides=(
                self._orig_channel.overrides if self._orig_channel
                else ()),
        )


class ProfileEditorDialog(wx.Dialog):
    """Edit profile identity, defaults, groups, and channels."""

    def __init__(self, parent, profile, path=None):
        title = _('Edit Radio Profile')
        if path:
            title = '%s - %s' % (title, os.path.basename(path))
        super().__init__(
            parent, title=title,
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.profile = profile
        self.path = path

        notebook = wx.Notebook(self)
        notebook.AddPage(self._build_identity_page(notebook), _('Identity'))
        notebook.AddPage(self._build_defaults_page(notebook), _('Defaults'))
        notebook.AddPage(self._build_groups_page(notebook), _('Groups'))
        notebook.AddPage(self._build_channels_page(notebook), _('Channels'))

        self.validation_text = wx.TextCtrl(
            self, style=wx.TE_MULTILINE | wx.TE_READONLY, size=(-1, 80))

        buttons = self.CreateButtonSizer(wx.OK | wx.CANCEL)
        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(notebook, 1, wx.EXPAND | wx.ALL, 8)
        outer.Add(wx.StaticText(self, label=_('Validation:')),
                  0, wx.LEFT | wx.RIGHT, 8)
        outer.Add(self.validation_text, 0, wx.EXPAND | wx.ALL, 8)
        outer.Add(buttons, 0, wx.EXPAND | wx.ALL, 8)
        self.SetSizerAndFit(outer)
        self.SetSize((640, 720))

        self.Bind(wx.EVT_BUTTON, self._on_ok, id=wx.ID_OK)
        self._refresh_channel_list()
        self._refresh_group_list()
        self._show_validation()

    # --- identity --------------------------------------------------------

    def _build_identity_page(self, parent):
        panel = wx.Panel(parent)
        grid = wx.FlexGridSizer(2, gap=(8, 4))
        grid.AddGrowableCol(1)

        self.name_ctrl = wx.TextCtrl(panel, value=self.profile.name)
        grid.Add(wx.StaticText(panel, label=_('Name')),
                 0, wx.ALIGN_CENTER_VERTICAL)
        grid.Add(self.name_ctrl, 1, wx.EXPAND)

        self.description_ctrl = wx.TextCtrl(
            panel, value=self.profile.description,
            style=wx.TE_MULTILINE, size=(-1, 80))
        grid.Add(wx.StaticText(panel, label=_('Description')), 0)
        grid.Add(self.description_ctrl, 1, wx.EXPAND)

        self.region_ctrl = wx.TextCtrl(panel, value=self.profile.region or '')
        grid.Add(wx.StaticText(panel, label=_('Region')),
                 0, wx.ALIGN_CENTER_VERTICAL)
        grid.Add(self.region_ctrl, 1, wx.EXPAND)

        panel.SetSizer(grid)
        return panel

    # --- defaults --------------------------------------------------------

    def _build_defaults_page(self, parent):
        panel = wx.Panel(parent)
        grid = wx.FlexGridSizer(2, gap=(8, 4))
        grid.AddGrowableCol(1)
        defaults = self.profile.defaults

        def row(label, ctrl):
            grid.Add(wx.StaticText(panel, label=label),
                     0, wx.ALIGN_CENTER_VERTICAL)
            grid.Add(ctrl, 1, wx.EXPAND)

        self.default_mode = _choice(
            panel, [_UNSET] + list(schema.VALID_MODES),
            selected=defaults.mode or _UNSET)
        row(_('Default Mode'), self.default_mode)

        self.default_power = _choice(
            panel, [_UNSET] + list(schema.VALID_POWER_TIERS),
            selected=defaults.power_preference.tier or _UNSET)
        row(_('Default Power Preference'), self.default_power)

        self.default_scan = _choice(
            panel, [_UNSET] + list(schema.VALID_SCAN_INTENTS),
            selected=defaults.scan_intent or _UNSET)
        row(_('Default Scan Intent'), self.default_scan)

        self.default_naming = _choice(
            panel, list(schema.VALID_NAMING_STYLES),
            selected=defaults.naming_style)
        row(_('Naming Style'), self.default_naming)

        self.default_dupe_policy = _choice(
            panel, list(schema.VALID_DUPLICATE_POLICIES),
            selected=defaults.duplicate_policy)
        row(_('Duplicate-Handling Policy'), self.default_dupe_policy)

        panel.SetSizer(grid)
        return panel

    # --- groups ----------------------------------------------------------

    def _build_groups_page(self, parent):
        panel = wx.Panel(parent)
        self.group_list = wx.ListCtrl(
            panel, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        self.group_list.AppendColumn(_('ID'))
        self.group_list.AppendColumn(_('Name'))

        add_btn = wx.Button(panel, label=_('Add Group'))
        remove_btn = wx.Button(panel, label=_('Remove Group'))
        add_btn.Bind(wx.EVT_BUTTON, self._on_add_group)
        remove_btn.Bind(wx.EVT_BUTTON, self._on_remove_group)

        btn_sizer = wx.BoxSizer(wx.HORIZONTAL)
        btn_sizer.Add(add_btn, 0, wx.RIGHT, 4)
        btn_sizer.Add(remove_btn, 0)

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(self.group_list, 1, wx.EXPAND | wx.ALL, 4)
        sizer.Add(btn_sizer, 0, wx.ALL, 4)
        panel.SetSizer(sizer)
        return panel

    def _refresh_group_list(self):
        self.group_list.DeleteAllItems()
        for gid, group in sorted(self.profile.groups.items()):
            index = self.group_list.InsertItem(
                self.group_list.GetItemCount(), gid)
            self.group_list.SetItem(index, 1, group.name)

    def _on_add_group(self, event):
        gid_dlg = wx.TextEntryDialog(
            self, _('Group ID (slug):'), _('Add Group'))
        if gid_dlg.ShowModal() != wx.ID_OK:
            return
        gid = gid_dlg.GetValue().strip()
        if not schema.is_valid_logical_id(gid):
            wx.MessageBox(_('Invalid group ID'), _('Add Group'),
                          wx.OK | wx.ICON_ERROR, self)
            return
        name_dlg = wx.TextEntryDialog(self, _('Group Name:'), _('Add Group'))
        if name_dlg.ShowModal() != wx.ID_OK:
            return
        self.profile.groups[gid] = model.LogicalGroup(
            id=gid, name=name_dlg.GetValue().strip() or gid)
        self._refresh_group_list()
        self._show_validation()

    def _on_remove_group(self, event):
        selected = self.group_list.GetFirstSelected()
        if selected == wx.NOT_FOUND:
            return
        gid = self.group_list.GetItemText(selected)
        self.profile.groups.pop(gid, None)
        self._refresh_group_list()
        self._show_validation()

    # --- channels ----------------------------------------------------

    def _build_channels_page(self, parent):
        panel = wx.Panel(parent)
        self.channel_list = wx.ListCtrl(
            panel, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        for col in (
                _('Logical ID'), _('Name'), _('Frequency'), _('Transmit'),
                _('Groups')):
            self.channel_list.AppendColumn(col)

        add_btn = wx.Button(panel, label=_('Add'))
        edit_btn = wx.Button(panel, label=_('Edit'))
        delete_btn = wx.Button(panel, label=_('Delete'))
        add_btn.Bind(wx.EVT_BUTTON, self._on_add_channel)
        edit_btn.Bind(wx.EVT_BUTTON, self._on_edit_channel)
        delete_btn.Bind(wx.EVT_BUTTON, self._on_delete_channel)
        self.channel_list.Bind(
            wx.EVT_LIST_ITEM_ACTIVATED, self._on_edit_channel)

        btn_sizer = wx.BoxSizer(wx.HORIZONTAL)
        for b in (add_btn, edit_btn, delete_btn):
            btn_sizer.Add(b, 0, wx.RIGHT, 4)

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(self.channel_list, 1, wx.EXPAND | wx.ALL, 4)
        sizer.Add(btn_sizer, 0, wx.ALL, 4)
        panel.SetSizer(sizer)
        return panel

    def _refresh_channel_list(self):
        self.channel_list.DeleteAllItems()
        for channel in self.profile.channels:
            index = self.channel_list.InsertItem(
                self.channel_list.GetItemCount(), channel.logical_id)
            self.channel_list.SetItem(index, 1, channel.name)
            self.channel_list.SetItem(
                index, 2,
                chirp_common.format_freq(channel.rx_freq_hz)
                if channel.rx_freq_hz else '')
            self.channel_list.SetItem(
                index, 3, _TRANSMIT_MODE_LABELS.get(
                    channel.transmit.mode, channel.transmit.mode))
            self.channel_list.SetItem(index, 4, ', '.join(channel.groups))

    def _selected_channel_index(self):
        return self.channel_list.GetFirstSelected()

    def _on_add_channel(self, event):
        dlg = ChannelEditDialog(self, self.profile)
        if dlg.ShowModal() == wx.ID_OK:
            if self.profile.get_channel(dlg.result_channel.logical_id):
                wx.MessageBox(
                    _('A channel with this logical ID already exists'),
                    _('Add Channel'), wx.OK | wx.ICON_ERROR, self)
            else:
                self.profile.add_channel(dlg.result_channel)
                self._refresh_channel_list()
                self._show_validation()
        dlg.Destroy()

    def _on_edit_channel(self, event):
        index = self._selected_channel_index()
        if index == wx.NOT_FOUND:
            return
        channel = self.profile.channels[index]
        dlg = ChannelEditDialog(self, self.profile, channel=channel)
        if dlg.ShowModal() == wx.ID_OK:
            self.profile.channels[index] = dlg.result_channel
            self._refresh_channel_list()
            self._show_validation()
        dlg.Destroy()

    def _on_delete_channel(self, event):
        index = self._selected_channel_index()
        if index == wx.NOT_FOUND:
            return
        del self.profile.channels[index]
        self._refresh_channel_list()
        self._show_validation()

    # --- validation / OK ---------------------------------------------

    def _apply_identity_and_defaults(self):
        self.profile.name = self.name_ctrl.GetValue()
        self.profile.description = self.description_ctrl.GetValue()
        self.profile.region = self.region_ctrl.GetValue() or None
        defaults = self.profile.defaults
        default_mode = _choice_value(self.default_mode)
        defaults.mode = None if default_mode == _UNSET else default_mode
        default_power = _choice_value(self.default_power)
        defaults.power_preference = model.PowerPreference(
            tier=None if default_power == _UNSET else default_power)
        default_scan = _choice_value(self.default_scan)
        defaults.scan_intent = (
            None if default_scan == _UNSET else default_scan)
        defaults.naming_style = _choice_value(self.default_naming)
        defaults.duplicate_policy = _choice_value(self.default_dupe_policy)

    def _show_validation(self):
        self._apply_identity_and_defaults()
        issues = validation.validate_profile(self.profile)
        if issues:
            self.validation_text.SetValue(
                '\n'.join(str(i) for i in issues))
        else:
            self.validation_text.SetValue(_('No validation issues.'))
        return issues

    def _on_ok(self, event):
        issues = self._show_validation()
        if issues:
            wx.MessageBox(
                _('This profile has validation problems and cannot be '
                  'saved until they are fixed:\n\n') +
                '\n'.join(str(i) for i in issues),
                _('Validation Failed'), wx.OK | wx.ICON_ERROR, self)
            return
        self.profile.touch()
        event.Skip()
