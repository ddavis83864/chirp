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

"""The Programming Assistant wizard: Describe -> Confirm -> Review ->
Result, following the same wx.adv.Wizard pattern as
chirp.wxui.bugreport. This module is a thin UI layer -- all
classification/policy/planning/conversion logic lives in
chirp.assistant.*, which has no wx dependency and is independently
tested.

Nothing here opens a serial port, clones from a radio, or uploads to
one -- Apply only ever calls the same ChirpMemEdit.set_memory() that a
normal hand-edit uses, wrapped in one undo_context() so the whole
result is a single undoable action on the already-open image. The user
must still use CHIRP's normal Radio > Upload afterward.
"""

import logging
import threading

import wx
import wx.adv
import wx.lib.newevent

from chirp.assistant import audit
from chirp.assistant import models
from chirp.assistant import providers
from chirp.assistant import service as service_mod
from chirp.wxui import common
from chirp.wxui import config
from chirp.wxui import memedit

_ = wx.GetTranslation
LOG = logging.getLogger(__name__)
CONF = config.get('assistant')

BuildThreadEvent, EVT_BUILD_THREAD = wx.lib.newevent.NewCommandEvent()
InterpretThreadEvent, EVT_INTERPRET_THREAD = wx.lib.newevent.NewCommandEvent()

_ACTIVITY_CHOICES = (
    'camping', 'aviation', 'marine', 'off-road', 'travel', 'emergency prep',
)
_SERVICE_LABELS = (
    (models.SERVICE_HAM, _('Amateur (Ham) Radio')),
    (models.SERVICE_GMRS, _('GMRS')),
    (models.SERVICE_FRS, _('FRS')),
    (models.SERVICE_MURS, _('MURS')),
    (models.SERVICE_WEATHER, _('NOAA Weather')),
    (models.SERVICE_AVIATION, _('Aviation (receive-only)')),
    (models.SERVICE_MARINE, _('Marine (receive-only)')),
    (models.SERVICE_PUBLIC_SAFETY, _('Public Safety (receive-only)')),
    (models.SERVICE_BUSINESS, _('Business/Industrial (receive-only)')),
    (models.SERVICE_RAILROAD, _('Railroad (receive-only)')),
    (models.SERVICE_SATELLITE, _('Amateur Satellite')),
)
_LICENSE_LABELS = (
    (models.LICENSE_NONE, _('None')),
    (models.LICENSE_TECHNICIAN, _('Technician')),
    (models.LICENSE_GENERAL, _('General')),
    (models.LICENSE_EXTRA, _('Extra')),
)
_NAMING_LABELS = (
    (models.NAMING_SHORT, _('Short (radio-constrained)')),
    (models.NAMING_DESCRIPTIVE, _('Descriptive')),
)

_DISCLAIMER = _(
    'The Programming Assistant organizes publicly available and '
    'curated frequency information into a proposed set of radio '
    'memories. It does not verify your license or authorization to '
    'transmit, and a radio\'s technical ability to transmit on a '
    'frequency does not establish legal authorization or equipment '
    'certification for that service. You remain responsible for '
    'operating lawfully. Aviation, weather, marine, public safety, '
    'business, and railroad channels are always programmed as '
    'receive-only in this release.'
)


def _find_memedit(editorset):
    """The Programming Assistant always targets the memory editor, even
    if the user currently has a Banks/Settings tab selected. @editorset
    is None when no radio image is open at all (e.g. launched fresh,
    nothing loaded/created yet) -- treat that the same as "no memory
    editor available" rather than crashing."""
    if editorset is None:
        return None
    current = editorset.current_editor
    if isinstance(current, memedit.ChirpMemEdit):
        return current
    for editor in editorset._editor_index.values():
        if isinstance(editor, memedit.ChirpMemEdit):
            return editor
    return None


def assistant_enabled():
    return CONF.get_bool('enabled', default=False)


def set_assistant_enabled(enabled):
    CONF.set_bool('enabled', enabled)


class AssistantContext:
    def __init__(self, wizard, chirpmain):
        self.wizard = wizard
        self.chirpmain = chirpmain
        self.editorset = chirpmain.current_editorset
        self.memedit = _find_memedit(self.editorset)
        # self.editorset is None when no radio image is open at all;
        # do_programming_assistant() checks self.memedit before this
        # context is used any further, so radio/service just need to
        # not crash the constructor in that case.
        self.radio = self.editorset.radio if self.editorset else None
        self.service = (service_mod.AssistantService(self.radio)
                        if self.radio else None)
        self.request = models.ProgrammingRequest()
        self.plan = None
        self.apply_result = None
        self._pages = {}

    def get_page(self, name, cls):
        if name not in self._pages:
            self._pages[name] = cls(self)
        return self._pages[name]

    def provider(self):
        kind = CONF.get('provider_kind') or providers.PROVIDER_DISABLED
        if kind == providers.PROVIDER_DISABLED:
            return providers.DisabledProvider()
        endpoint = CONF.get('endpoint')
        model = CONF.get('model')
        api_key = _get_api_key()
        try:
            return providers.create_provider(kind, endpoint=endpoint,
                                             model=model, api_key=api_key)
        except providers.ProviderError:
            return providers.DisabledProvider()


def _get_api_key():
    """Env var takes precedence (the more secure of the available
    options, since it's never written to disk by us); otherwise fall
    back to CHIRP's existing (explicitly non-secure) obfuscated config
    storage, which the preferences dialog warns about before use. No
    OS keyring dependency exists in this project (see
    chirp.wxui.config.ChirpConfigProxy.set_password's own docstring)."""
    import os
    env_key = os.environ.get('CHIRP_ASSISTANT_API_KEY')
    if env_key:
        return env_key
    if CONF.get_bool('persist_api_key', default=False):
        return CONF.get_password('api_key', 'assistant')
    return None


class AssistantPage(wx.adv.WizardPage):
    TITLE = ''
    INST = ''

    def __init__(self, context):
        super().__init__(context.wizard)
        self.context = context
        vbox = wx.BoxSizer(wx.VERTICAL)
        self.SetSizer(vbox)
        if self.TITLE:
            title = wx.StaticText(self, label=self.TITLE)
            font = title.GetFont()
            font.MakeBold()
            title.SetFont(font)
            vbox.Add(title, 0, wx.ALL, 10)
        if self.INST:
            inst = wx.StaticText(self, label=self.INST)
            inst.Wrap(560)
            vbox.Add(inst, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        self._build(vbox)

    def _validate_next(self):
        return True

    def validate_next(self, *a):
        forward = self.FindWindowById(wx.ID_FORWARD)
        if forward:
            forward.Enable(self._validate_next())

    def validate_success(self, event):
        pass

    def GetNext(self):
        return None

    def GetPrev(self):
        return None


class DescribePage(AssistantPage):
    TITLE = _('Describe what you want programmed')
    INST = _(
        'Describe your request in plain language, or just fill in the '
        'fields below directly -- AI is entirely optional and nothing '
        'here requires it.'
    )

    def _build(self, vbox):
        self.Bind(EVT_INTERPRET_THREAD, self._interpret_done)
        self._interpret_thread = None

        self.text = wx.TextCtrl(self, style=wx.TE_MULTILINE, size=(-1, 60))
        vbox.Add(self.text, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)

        btn_row = wx.BoxSizer(wx.HORIZONTAL)
        self.interpret_btn = wx.Button(self, label=_('Interpret with AI'))
        self.interpret_btn.Bind(wx.EVT_BUTTON, self._on_interpret)
        btn_row.Add(self.interpret_btn, 0, wx.RIGHT, 10)
        provider_btn = wx.Button(self, label=_('Configure AI Provider...'))
        provider_btn.Bind(wx.EVT_BUTTON, self._on_configure_provider)
        btn_row.Add(provider_btn, 0)
        vbox.Add(btn_row, 0, wx.ALL, 10)

        self.interpret_status = wx.StaticText(self, label='')
        vbox.Add(self.interpret_status, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        grid = wx.FlexGridSizer(cols=2, gap=(8, 6))
        grid.AddGrowableCol(1)

        self.location = wx.TextCtrl(self)
        grid.Add(wx.StaticText(self, label=_('Location:')), 0,
                 wx.ALIGN_CENTER_VERTICAL)
        grid.Add(self.location, 1, wx.EXPAND)

        self.radius = wx.SpinCtrl(self, min=1, max=models.MAX_RADIUS_MILES,
                                  initial=25)
        grid.Add(wx.StaticText(self, label=_('Radius (miles):')), 0,
                 wx.ALIGN_CENTER_VERTICAL)
        grid.Add(self.radius, 0)

        self.license_choice = wx.Choice(
            self, choices=[label for _id, label in _LICENSE_LABELS])
        self.license_choice.SetSelection(0)
        grid.Add(wx.StaticText(self, label=_('Amateur license class:')), 0,
                 wx.ALIGN_CENTER_VERTICAL)
        grid.Add(self.license_choice, 0)

        self.gmrs_chk = wx.CheckBox(
            self, label=_('I have a GMRS license'))
        grid.Add(wx.StaticText(self), 0)
        grid.Add(self.gmrs_chk, 0)

        self.activities = wx.TextCtrl(
            self, value='', style=wx.TE_PROCESS_ENTER)
        grid.Add(wx.StaticText(self, label=_('Activities (comma-separated):')),
                 0, wx.ALIGN_CENTER_VERTICAL)
        grid.Add(self.activities, 1, wx.EXPAND)

        self.services = wx.CheckListBox(
            self, choices=[label for _id, label in _SERVICE_LABELS])
        grid.Add(wx.StaticText(self, label=_('Requested services:')), 0,
                 wx.TOP)
        grid.Add(self.services, 1, wx.EXPAND)

        self.channel_limit = wx.SpinCtrl(
            self, min=models.MIN_CHANNEL_LIMIT,
            max=models.MAX_CHANNEL_LIMIT, initial=40)
        grid.Add(wx.StaticText(self, label=_('Maximum channels:')), 0,
                 wx.ALIGN_CENTER_VERTICAL)
        grid.Add(self.channel_limit, 0)

        self.naming_choice = wx.Choice(
            self, choices=[label for _id, label in _NAMING_LABELS])
        self.naming_choice.SetSelection(0)
        grid.Add(wx.StaticText(self, label=_('Naming style:')), 0,
                 wx.ALIGN_CENTER_VERTICAL)
        grid.Add(self.naming_choice, 0)

        self.preserve_existing = wx.CheckBox(
            self, label=_('Preserve existing memories (recommended)'))
        self.preserve_existing.SetValue(True)
        grid.Add(wx.StaticText(self), 0)
        grid.Add(self.preserve_existing, 0)

        self.allow_replace = wx.CheckBox(
            self, label=_('Allow replacing conflicting existing memories'))
        grid.Add(wx.StaticText(self), 0)
        grid.Add(self.allow_replace, 0)

        self.start_mem = wx.SpinCtrl(self, min=0, max=99999, initial=0)
        self.end_mem = wx.SpinCtrl(self, min=0, max=99999, initial=0)
        range_row = wx.BoxSizer(wx.HORIZONTAL)
        range_row.Add(self.start_mem, 0, wx.RIGHT, 5)
        range_row.Add(wx.StaticText(self, label=_('to')), 0,
                      wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        range_row.Add(self.end_mem, 0)
        self.use_range = wx.CheckBox(self, label=_('Limit to memory range:'))
        grid.Add(self.use_range, 0, wx.ALIGN_CENTER_VERTICAL)
        grid.Add(range_row, 0)

        self.protected = wx.TextCtrl(self, value='')
        grid.Add(wx.StaticText(
            self, label=_('Protected ranges (e.g. 0-9, 90-99):')), 0,
            wx.ALIGN_CENTER_VERTICAL)
        grid.Add(self.protected, 1, wx.EXPAND)

        vbox.Add(grid, 1, wx.EXPAND | wx.ALL, 10)
        self._update_interpret_enabled()

    def _update_interpret_enabled(self):
        enabled = self.context.provider().kind != providers.PROVIDER_DISABLED
        self.interpret_btn.Enable(enabled)
        if not enabled:
            self.interpret_status.SetLabel(
                _('No AI provider configured -- fill in the fields '
                  'below directly, or configure a provider above.'))

    def _on_configure_provider(self, event):
        dlg = AssistantProviderDialog(self)
        dlg.ShowModal()
        dlg.Destroy()
        self._update_interpret_enabled()

    def _on_interpret(self, event):
        if self._interpret_thread:
            return
        text = self.text.GetValue().strip()
        if not text:
            self.interpret_status.SetLabel(_('Enter a description first.'))
            return
        provider = self.context.provider()
        audit.provider_selected(provider.kind)
        self.interpret_status.SetLabel(_('Interpreting...'))
        self.interpret_btn.Enable(False)
        self._interpret_thread = threading.Thread(
            target=self._interpret_worker, args=(provider, text))
        self._interpret_thread.start()

    def _interpret_worker(self, provider, text):
        try:
            request = provider.extract_intent(text)
            wx.PostEvent(self, InterpretThreadEvent(
                self.GetId(), request=request, error=None))
        except providers.ProviderError as e:
            wx.PostEvent(self, InterpretThreadEvent(
                self.GetId(), request=None, error=str(e)))

    def _interpret_done(self, event):
        self._interpret_thread = None
        self.interpret_btn.Enable(True)
        audit.intent_extraction_result(
            self.context.provider().kind, event.error is None, event.error)
        if event.error:
            self.interpret_status.SetLabel(_('Error: %s') % event.error)
            return
        self.interpret_status.SetLabel(
            _('Interpreted -- review the fields below before continuing.'))
        self._apply_request_to_fields(event.request)

    def _apply_request_to_fields(self, request):
        if request.location_text:
            self.location.SetValue(request.location_text)
        self.radius.SetValue(int(request.radius_miles))
        for i, (value, _label) in enumerate(_LICENSE_LABELS):
            if value == request.amateur_license:
                self.license_choice.SetSelection(i)
        self.gmrs_chk.SetValue(request.has_gmrs_license)
        self.activities.SetValue(', '.join(request.activities))
        for i, (value, _label) in enumerate(_SERVICE_LABELS):
            self.services.Check(i, value in request.requested_services)
        self.channel_limit.SetValue(request.channel_limit)
        for i, (value, _label) in enumerate(_NAMING_LABELS):
            if value == request.naming_style:
                self.naming_choice.SetSelection(i)

    def _validate_next(self):
        return bool(self.services.GetCheckedItems())

    def validate_success(self, event):
        req = self.context.request
        req.location_text = self.location.GetValue().strip()
        req.radius_miles = float(self.radius.GetValue())
        req.amateur_license = _LICENSE_LABELS[
            self.license_choice.GetSelection()][0]
        req.has_gmrs_license = self.gmrs_chk.GetValue()
        req.activities = tuple(
            a.strip() for a in self.activities.GetValue().split(',')
            if a.strip())
        req.requested_services = tuple(
            _SERVICE_LABELS[i][0] for i in self.services.GetCheckedItems())
        req.channel_limit = self.channel_limit.GetValue()
        req.naming_style = _NAMING_LABELS[
            self.naming_choice.GetSelection()][0]
        req.preserve_existing = self.preserve_existing.GetValue()
        req.allow_duplicate_replacement = self.allow_replace.GetValue()
        if self.use_range.GetValue():
            req.requested_start_memory = self.start_mem.GetValue()
            req.requested_end_memory = self.end_mem.GetValue()
        else:
            req.requested_start_memory = None
            req.requested_end_memory = None
        req.protected_memory_ranges = _parse_ranges(
            self.protected.GetValue())

        errors = req.validate()
        if errors:
            wx.MessageDialog(
                self, '\n'.join(errors), _('Invalid request'),
                style=wx.OK | wx.ICON_ERROR).ShowModal()
            event.Veto()

    def GetNext(self):
        return self.context.get_page('confirm', ConfirmPage)


def _parse_ranges(text):
    ranges = []
    for part in text.split(','):
        part = part.strip()
        if not part:
            continue
        if '-' in part:
            lo, _sep, hi = part.partition('-')
        else:
            lo = hi = part
        try:
            ranges.append((int(lo.strip()), int(hi.strip())))
        except ValueError:
            continue
    return tuple(ranges)


class AssistantProviderDialog(wx.Dialog):
    def __init__(self, parent):
        super().__init__(parent, title=_('AI Provider Configuration'),
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        vbox = wx.BoxSizer(wx.VERTICAL)
        self.SetSizer(vbox)

        note = wx.StaticText(self, label=_(
            'AI is used ONLY to turn your typed description into the '
            'structured fields above -- it never supplies frequencies, '
            'tones, or any other technical channel data, and no call is '
            'made until you click "Interpret with AI".'))
        note.Wrap(420)
        vbox.Add(note, 0, wx.ALL, 10)

        grid = wx.FlexGridSizer(cols=2, gap=(8, 6))
        grid.AddGrowableCol(1)

        kinds = [_('Disabled'), _('OpenAI-compatible'), _('Ollama (local)')]
        self.kind_choice = wx.Choice(self, choices=kinds)
        current_kind = CONF.get('provider_kind') or providers.PROVIDER_DISABLED
        self.kind_choice.SetSelection(
            providers.ALL_PROVIDER_KINDS.index(current_kind)
            if current_kind in providers.ALL_PROVIDER_KINDS else 0)
        grid.Add(wx.StaticText(self, label=_('Provider:')), 0,
                 wx.ALIGN_CENTER_VERTICAL)
        grid.Add(self.kind_choice, 0)

        self.endpoint = wx.TextCtrl(self, value=CONF.get('endpoint') or '')
        grid.Add(wx.StaticText(self, label=_('Endpoint URL:')), 0,
                 wx.ALIGN_CENTER_VERTICAL)
        grid.Add(self.endpoint, 1, wx.EXPAND)

        self.model = wx.TextCtrl(self, value=CONF.get('model') or '')
        grid.Add(wx.StaticText(self, label=_('Model name:')), 0,
                 wx.ALIGN_CENTER_VERTICAL)
        grid.Add(self.model, 1, wx.EXPAND)

        self.api_key = wx.TextCtrl(self, style=wx.TE_PASSWORD)
        import os
        if os.environ.get('CHIRP_ASSISTANT_API_KEY'):
            self.api_key.SetHint(_('Using CHIRP_ASSISTANT_API_KEY '
                                   'environment variable'))
            self.api_key.Enable(False)
        else:
            self.api_key.SetValue(CONF.get_password('api_key', 'assistant')
                                  or '')
        grid.Add(wx.StaticText(self, label=_('API key (session/optional):')),
                 0, wx.ALIGN_CENTER_VERTICAL)
        grid.Add(self.api_key, 1, wx.EXPAND)

        self.persist_key = wx.CheckBox(self, label=_(
            'Remember API key on this computer (obfuscated, NOT '
            'securely encrypted -- no OS keyring is available)'))
        self.persist_key.SetValue(
            CONF.get_bool('persist_api_key', default=False))
        grid.Add(wx.StaticText(self), 0)
        grid.Add(self.persist_key, 0)

        vbox.Add(grid, 0, wx.EXPAND | wx.ALL, 10)
        vbox.Add(self.CreateButtonSizer(wx.OK | wx.CANCEL), 0,
                 wx.EXPAND | wx.ALL, 10)
        self.Bind(wx.EVT_BUTTON, self._on_ok, id=wx.ID_OK)
        self.CenterOnParent()

    def _on_ok(self, event):
        kind = providers.ALL_PROVIDER_KINDS[self.kind_choice.GetSelection()]
        CONF.set('provider_kind', kind)
        CONF.set('endpoint', self.endpoint.GetValue().strip())
        CONF.set('model', self.model.GetValue().strip())
        CONF.set_bool('persist_api_key', self.persist_key.GetValue())
        if self.persist_key.GetValue() and self.api_key.IsEnabled():
            CONF.set_password('api_key', self.api_key.GetValue(),
                              'assistant')
        elif not self.persist_key.GetValue():
            if CONF.is_defined('api_key_encoded', 'assistant'):
                CONF.remove_option('api_key_encoded', 'assistant')
        event.Skip()


class ConfirmPage(AssistantPage):
    TITLE = _('Confirm your request')
    INST = _(
        'Review the interpreted request below. Nothing is queried or '
        'built until you continue -- go back to correct anything.'
    )

    def _build(self, vbox):
        self.Bind(EVT_BUILD_THREAD, self._build_done)
        self._build_thread = None
        self._built = False

        self.summary = wx.TextCtrl(
            self, style=wx.TE_MULTILINE | wx.TE_READONLY)
        vbox.Add(self.summary, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)

        self.share_precise = wx.CheckBox(self, label=_(
            'Share precise coordinates with network sources (off = '
            'distance sorting is skipped; only your entered state/'
            'location text is used)'))
        vbox.Add(self.share_precise, 0, wx.ALL, 10)

        self.network_allowed = wx.CheckBox(
            self, label=_('Allow network source queries (RepeaterBook, '
                          'satellites)'))
        self.network_allowed.SetValue(True)
        vbox.Add(self.network_allowed, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        self.status = wx.StaticText(self, label='')
        vbox.Add(self.status, 0, wx.ALL, 10)

    def _refresh_summary(self):
        req = self.context.request
        lines = [
            _('Location: %s') % (req.location_text or '(none)'),
            _('Radius: %s miles') % req.radius_miles,
            _('Amateur license: %s') % req.amateur_license,
            _('GMRS license declared: %s') % req.has_gmrs_license,
            _('Activities: %s') % (', '.join(req.activities) or '(none)'),
            _('Requested services: %s') % ', '.join(req.requested_services),
            _('Channel limit: %i') % req.channel_limit,
            _('Naming style: %s') % req.naming_style,
            _('Preserve existing memories: %s') % req.preserve_existing,
            _('Allow duplicate replacement: %s') %
            req.allow_duplicate_replacement,
        ]
        self.summary.SetValue('\n'.join(lines))

    def validate_success(self, event):
        if not self._built:
            self._refresh_summary()

    def _validate_next(self):
        if not self._built:
            if not self._build_thread:
                self._start_build()
            return False
        return self.context.plan is not None

    def _start_build(self):
        self.status.SetLabel(_('Building plan...'))
        req = self.context.request
        req.share_precise_location = self.share_precise.GetValue()
        network_allowed = self.network_allowed.GetValue()
        self._build_thread = threading.Thread(
            target=self._build_worker, args=(network_allowed,))
        self._build_thread.start()

    def _build_worker(self, network_allowed):
        try:
            plan = self.context.service.build_plan(
                self.context.request, network_allowed=network_allowed)
            self.context.service.convert_and_validate(plan)
            wx.PostEvent(self, BuildThreadEvent(
                self.GetId(), plan=plan, error=None))
        except Exception as e:
            LOG.exception('Failed to build assistant plan: %s', e)
            wx.PostEvent(self, BuildThreadEvent(
                self.GetId(), plan=None, error=str(e)))

    def _build_done(self, event):
        self._build_thread = None
        self._built = True
        if event.error:
            self.status.SetLabel(_('Error: %s') % event.error)
            self.context.plan = None
        else:
            self.context.plan = event.plan
            counts = event.plan.counts()
            self.status.SetLabel(
                _('Plan built: %i candidate(s) ready to review.') %
                len(event.plan.all_candidates))
            audit.plan_built(
                len(event.plan.all_candidates),
                sum(v for k, v in counts.items()
                    if k not in (models.STATUS_BLOCKED,)),
                counts.get(models.STATUS_BLOCKED, 0))
        self.validate_next()

    def GetPrev(self):
        return self.context.get_page('describe', DescribePage)

    def GetNext(self):
        return self.context.get_page('review', ReviewPage)


_COLUMNS = (
    ('num', _('Loc')), ('group', _('Group')), ('name', _('Name')),
    ('rx', _('RX Freq')), ('tx', _('TX Freq / RX-only')),
    ('mode', _('Mode')), ('tone', _('Tone')), ('status', _('Status')),
    ('source', _('Source')), ('details', _('Details')),
)


class ReviewPage(AssistantPage):
    TITLE = _('Review the proposed plan')

    def _build(self, vbox):
        self.summary_label = wx.StaticText(self, label='')
        vbox.Add(self.summary_label, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        self.list = wx.ListCtrl(
            self, style=wx.LC_REPORT)
        self.list.EnableCheckBoxes(True)
        for i, (_key, label) in enumerate(_COLUMNS):
            self.list.InsertColumn(i, label)
        vbox.Add(self.list, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
        self.list.Bind(wx.EVT_LIST_ITEM_CHECKED, self._on_check)
        self.list.Bind(wx.EVT_LIST_ITEM_UNCHECKED, self._on_check)

        btn_row = wx.BoxSizer(wx.HORIZONTAL)
        details_btn = wx.Button(
            self, label=_('Regulatory && Privacy Details...'))
        details_btn.Bind(wx.EVT_BUTTON, self._on_details)
        btn_row.Add(details_btn, 0)
        vbox.Add(btn_row, 0, wx.ALL, 10)

        self._row_candidates = []

    def _on_details(self, event):
        wx.MessageDialog(self, _DISCLAIMER, _('Regulatory & Privacy Details'),
                         style=wx.OK | wx.ICON_INFORMATION).ShowModal()

    def validate_success(self, event):
        self._populate()

    def _populate(self):
        self.list.DeleteAllItems()
        self._row_candidates = []
        plan = self.context.plan
        if not plan:
            return
        row = 0
        for group in plan.groups:
            for c in sorted(group.candidates, key=lambda c: not c.include):
                self._add_row(row, group, c)
                row += 1
        for i in range(len(_COLUMNS)):
            self.list.SetColumnWidth(i, wx.LIST_AUTOSIZE_USEHEADER)
        counts = plan.counts()
        self.summary_label.SetLabel(
            _('%i total, %i included: ') % (
                len(plan.all_candidates), sum(counts.values())) +
            ', '.join('%s=%i' % (k, v) for k, v in sorted(counts.items())))

    def _add_row(self, row, group, candidate):
        idx = self.list.InsertItem(row, str(candidate.memory_number
                                            if candidate.memory_number
                                            is not None else ''))
        self.list.SetItem(idx, 1, group.name)
        self.list.SetItem(idx, 2, candidate.name or candidate.label)
        self.list.SetItem(
            idx, 3, _freq_str(candidate.freq))
        if candidate.receive_only:
            self.list.SetItem(idx, 4, _('Receive-only'))
        elif candidate.tx_freq is not None:
            self.list.SetItem(idx, 4, _freq_str(candidate.tx_freq))
        else:
            self.list.SetItem(idx, 4, _('Simplex'))
        self.list.SetItem(idx, 5, candidate.mode)
        self.list.SetItem(idx, 6, candidate.tmode or '')
        self.list.SetItem(idx, 7, candidate.status)
        self.list.SetItem(idx, 8, candidate.source)
        details = '; '.join(
            list(candidate.warnings) + list(candidate.errors) +
            ([candidate.reason] if candidate.reason else []))
        self.list.SetItem(idx, 9, details)
        self.list.CheckItem(idx, candidate.include)
        if not candidate.include:
            self.list.SetItemTextColour(idx, wx.Colour('#888888'))
        self._row_candidates.append(candidate)

    def _on_check(self, event):
        idx = event.GetIndex()
        if idx >= len(self._row_candidates):
            return
        candidate = self._row_candidates[idx]
        candidate.include = self.list.IsItemChecked(idx)

    def _validate_next(self):
        return any(c.include for c in self._row_candidates)

    def GetPrev(self):
        return self.context.get_page('confirm', ConfirmPage)

    def GetNext(self):
        return self.context.get_page('result', ResultPage)


def _freq_str(freq_hz):
    if freq_hz is None:
        return ''
    return '%.4f' % (freq_hz / 1000000.0)


class ResultPage(AssistantPage):
    TITLE = _('Result')

    def _build(self, vbox):
        self.result = wx.TextCtrl(
            self, style=wx.TE_MULTILINE | wx.TE_READONLY)
        vbox.Add(self.result, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
        self._applied = False

    def validate_success(self, event):
        if self._applied:
            return
        self._applied = True
        self._apply()

    def _apply(self):
        context = self.context
        memedit_editor = context.memedit
        if memedit_editor is None:
            self.result.SetValue(_(
                'No memory editor tab is available for this radio; '
                'nothing was applied.'))
            return

        finalized = context.service.finalize_for_apply(context.plan)
        applied = []
        failed = []
        with memedit_editor.undo_context(_('Programming Assistant plan')):
            for candidate, memory in finalized:
                try:
                    memedit_editor.set_memory(memory)
                    applied.append(candidate)
                except Exception as e:
                    LOG.exception(
                        'Failed to apply candidate %s: %s',
                        candidate.name, e)
                    failed.append((candidate, str(e)))

        counts = context.plan.counts()
        blocked = sum(v for k, v in counts.items()
                      if k in (models.STATUS_BLOCKED,
                               models.STATUS_UNSUPPORTED_BY_RADIO))
        adjusted = counts.get(models.STATUS_ADJUSTED, 0)
        replaced = sum(1 for c, _m in finalized
                       if c.status == models.STATUS_EXISTING_CONFLICT)
        skipped = len(context.plan.all_candidates) - len(finalized)

        audit.apply_result(len(applied), skipped, blocked, adjusted,
                           replaced)
        if failed:
            audit.apply_failed('%i candidate(s) failed to apply' %
                               len(failed))

        lines = [
            _('Applied: %i') % len(applied),
            _('Skipped (not included or invalid): %i') % skipped,
            _('Blocked by validation: %i') % blocked,
            _('Adjusted for this radio: %i') % adjusted,
            _('Existing memories replaced: %i') % replaced,
        ]
        if failed:
            lines.append(_('Failed to apply: %i') % len(failed))
            for c, err in failed:
                lines.append('  %s: %s' % (c.name, err))
        if context.plan.skipped_sources:
            lines.append(_('Sources with no data: %s') %
                         ', '.join(context.plan.skipped_sources))
        lines.append('')
        lines.append(_(
            'The open image has been updated. Nothing has been '
            'uploaded to a radio -- use Radio > Upload to Radio when '
            'you are ready.'))
        self.result.SetValue('\n'.join(lines))
        memedit_editor.refresh()

    def _validate_next(self):
        return False

    def GetPrev(self):
        return None


@common.error_proof()
def do_programming_assistant(parent, event):
    context_holder = {}
    wizard = wx.adv.Wizard(parent)
    wizard.SetPageSize((620, 520))

    context = AssistantContext(wizard, parent)
    context_holder['context'] = context

    if context.memedit is None:
        wx.MessageDialog(
            parent, _('No memory editor is available for the current '
                      'tab.'), _('Programming Assistant'),
            style=wx.OK | wx.ICON_WARNING).ShowModal()
        wizard.Destroy()
        return

    audit.dialog_opened()

    wizard.Bind(wx.adv.EVT_WIZARD_PAGE_CHANGED,
                lambda e: e.GetPage().validate_next())
    wizard.Bind(wx.adv.EVT_WIZARD_PAGE_CHANGING,
                lambda e: (e.GetPage().validate_success(e)
                           if e.GetDirection() else None))

    start = context.get_page('describe', DescribePage)
    wizard.GetPageAreaSizer().Add(start)
    wizard.RunWizard(start)
    wizard.Destroy()
