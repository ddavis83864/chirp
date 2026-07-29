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

import dataclasses
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
ValidateThreadEvent, EVT_VALIDATE_THREAD = wx.lib.newevent.NewCommandEvent()

# A fixed, deterministic prompt used ONLY to exercise a configured
# provider's real extract_intent() path end to end (HTTP request ->
# response parsing -> schema validation) from the "Validate AI Config"
# button -- see AssistantProviderDialog._on_validate(). Never shown to
# the user, never localized (it is model input, not UI text, the same
# reasoning as providers._SYSTEM_PROMPT), never affects any
# ProgrammingRequest field the user has actually entered, and the
# result is discarded after checking whether it succeeded.
_VALIDATION_PROMPT = 'Find amateur radio repeaters near Boise, Idaho.'

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

# Keys match DescribePage._describe_field_snapshot()'s dict; labels are
# what a changed-fields list in the AI-interpretation-complete dialog
# shows -- see DescribePage._show_interpretation_complete().
_INTERPRET_FIELD_LABELS = (
    ('location', _('Location')),
    ('radius', _('Radius')),
    ('license', _('Amateur license class')),
    ('gmrs', _('GMRS license')),
    ('activities', _('Activities')),
    ('services', _('Requested services')),
    ('channel_limit', _('Maximum channels')),
    ('naming', _('Naming style')),
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


def _safe_post_event(window, event):
    """wx.PostEvent(window, event) from a background worker thread,
    tolerant of the target page/wizard having already been destroyed
    (the user cancelled or closed the wizard while
    _interpret_worker()/_build_worker() was still in flight). wx's
    SWIG-wrapped C++ objects raise RuntimeError once deleted -- rely
    on that directly (confirmed empirically) rather than a truthiness
    pre-check on @window, which isn't a reliable liveness test for
    every wx object in every embedding context."""
    try:
        wx.PostEvent(window, event)
    except RuntimeError:
        LOG.debug('Dropping event for %s: window already destroyed',
                  event.__class__.__name__)


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

    def _validate_prev(self):
        return self.GetPrev() is not None

    def validate_next(self, *a):
        forward = self.FindWindowById(wx.ID_FORWARD)
        if forward:
            forward.Enable(self._validate_next())
        # wx.adv.Wizard does not automatically disable the Back button
        # just because GetPrev() returns None -- confirmed empirically
        # (it stays enabled, clickable, with undefined-in-this-app
        # results) -- so pages with no previous page (Describe,
        # Result) must disable it explicitly, the same way _validate_
        # next() explicitly manages the forward button. _validate_prev()
        # is the override point for that (and for anything else, like
        # ConfirmPage's in-flight build, that should also block
        # navigating away from a page).
        backward = self.FindWindowById(wx.ID_BACKWARD)
        if backward:
            backward.Enable(self._validate_prev())

    def validate_success(self, event):
        pass

    def page_shown(self):
        """Called once, right after this page becomes the wizard's
        current page -- both on forward and backward navigation, and
        (unlike validate_success()) for the LAST page in the wizard
        too. validate_success() only fires on the page being LEFT
        during a forward transition, so it can never fire for a page
        with no next page to leave towards; anything that needs to
        run as soon as a page is actually shown (not as a gate on
        leaving some other page) belongs here instead."""
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
        btn_row.Add(provider_btn, 0, wx.RIGHT, 10)
        # A vertical separator, not just spacing, so this reads as its
        # own distinct action -- clearing everything -- rather than a
        # third AI-related button alongside Interpret/Configure.
        btn_row.Add(wx.StaticLine(self, style=wx.LI_VERTICAL), 0,
                    wx.EXPAND | wx.RIGHT, 10)
        self.clear_btn = wx.Button(self, label=_('Clear All Entries'))
        self.clear_btn.Bind(wx.EVT_BUTTON, self._on_clear_all)
        btn_row.Add(self.clear_btn, 0)
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
        # _validate_next() depends entirely on this control, but
        # nothing re-evaluates the wizard's Next button just because
        # the page is sitting there being interacted with -- only
        # page_shown()/validate_next(), called once when the page
        # becomes current, does that. Without this binding, Next stays
        # stuck at whatever it was when the page was first shown (no
        # services checked yet, so disabled) no matter what the user
        # subsequently checks.
        self.services.Bind(wx.EVT_CHECKLISTBOX, self._on_services_changed)
        grid.Add(wx.StaticText(self, label=_('Requested services:')), 0,
                 wx.TOP)
        grid.Add(self.services, 1, wx.EXPAND)

        self.services_status = wx.StaticText(
            self, label=_('Check at least one requested service to '
                          'continue.'))
        grid.Add(wx.StaticText(self), 0)
        grid.Add(self.services_status, 0)

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

    def _has_any_data(self):
        """True if anything on this page differs from how it looked
        when the Programming Assistant was first opened -- used to
        skip the confirmation dialog entirely when there is nothing to
        clear (Phase 5), and independent of _describe_field_snapshot()
        above, which only covers the fields an AI interpretation can
        touch, not every clearable control (free-form text,
        preserve_existing, allow_replace, use_range/start_mem/end_mem,
        protected)."""
        return bool(
            self.text.GetValue().strip() or
            self.location.GetValue().strip() or
            self.radius.GetValue() != 25 or
            self.license_choice.GetSelection() != 0 or
            self.gmrs_chk.GetValue() or
            self.activities.GetValue().strip() or
            self.services.GetCheckedItems() or
            self.channel_limit.GetValue() != 40 or
            self.naming_choice.GetSelection() != 0 or
            not self.preserve_existing.GetValue() or
            self.allow_replace.GetValue() or
            self.use_range.GetValue() or
            self.start_mem.GetValue() != 0 or
            self.end_mem.GetValue() != 0 or
            self.protected.GetValue().strip())

    def _on_clear_all(self, event):
        if not self._has_any_data():
            # Nothing entered -- a safe no-op, no confirmation needed.
            return
        dlg = wx.MessageDialog(
            self, _(
                'This will remove all information entered on the '
                'Describe page.\n\n'
                'Your AI provider configuration, radio image, and '
                'application settings will not be changed.'),
            _('Clear All Entries?'),
            style=wx.OK | wx.CANCEL | wx.ICON_QUESTION)
        dlg.SetOKCancelLabels(_('Clear'), _('Cancel'))
        result = dlg.ShowModal()
        dlg.Destroy()
        if result != wx.ID_OK:
            return
        self._clear_all_fields()

    def _clear_all_fields(self):
        """Restores every Describe-page control to exactly the value
        it had when the page was first built (see _build() above),
        including anything an AI interpretation populated -- there is
        no separate "AI state" to clear beyond these same widgets, see
        _apply_request_to_fields(), which only ever writes into them.
        Strictly scoped to this page: context.plan (Confirm/Review/
        Result state), radio data, and application configuration are
        never touched here.
        """
        self.text.SetValue('')
        self.location.SetValue('')
        self.radius.SetValue(25)
        self.license_choice.SetSelection(0)
        self.gmrs_chk.SetValue(False)
        self.activities.SetValue('')
        for i in range(len(_SERVICE_LABELS)):
            self.services.Check(i, False)
        self.channel_limit.SetValue(40)
        self.naming_choice.SetSelection(0)
        self.preserve_existing.SetValue(True)
        self.allow_replace.SetValue(False)
        self.use_range.SetValue(False)
        self.start_mem.SetValue(0)
        self.end_mem.SetValue(0)
        self.protected.SetValue('')
        self.interpret_status.SetLabel('')
        self._update_interpret_enabled()
        # The one piece of state this page can leave behind outside
        # its own widgets: replace it with a fresh instance rather
        # than resetting fields on the existing one, so there is no
        # way for a stale value to survive under a field this method
        # forgot to reset.
        self.context.request = models.ProgrammingRequest()
        # Re-evaluates the wizard's Next button and the "check at
        # least one service" status text immediately -- same call
        # _on_services_changed() makes for a real user click; without
        # it, Next would stay enabled (or disabled) at whatever it was
        # before Clear was pressed until the user interacted with the
        # page again.
        self._refresh_services_status()

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
            _safe_post_event(self, InterpretThreadEvent(
                self.GetId(), request=request, error=None))
        except providers.ProviderError as e:
            _safe_post_event(self, InterpretThreadEvent(
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
        # Snapshotted before AND after applying the interpreted request
        # (rather than comparing the request to some notion of "prior
        # field values" computed a different way) so "what changed" is
        # always exactly what a user re-reading the fields would see --
        # see _show_interpretation_complete()'s docstring for why this
        # matters: a successful interpretation that happens to match
        # what was already entered is otherwise indistinguishable from
        # one that silently did nothing.
        before = self._describe_field_snapshot()
        self._apply_request_to_fields(event.request)
        after = self._describe_field_snapshot()
        changed_labels = [label for key, label in _INTERPRET_FIELD_LABELS
                          if before[key] != after[key]]
        self._show_interpretation_complete(changed_labels)

    def _describe_field_snapshot(self):
        """A plain-value snapshot of every field _apply_request_to_
        fields() can touch, for before/after comparison in
        _interpret_done() -- deliberately independent of
        models.ProgrammingRequest (which self.context.request is, and
        which is not updated until DescribePage.validate_success()),
        since what matters here is what the WIDGETS show, not what has
        been committed to the request yet."""
        return {
            'location': self.location.GetValue().strip(),
            'radius': self.radius.GetValue(),
            'license': self.license_choice.GetSelection(),
            'gmrs': self.gmrs_chk.GetValue(),
            'activities': self.activities.GetValue().strip(),
            'services': tuple(sorted(self.services.GetCheckedItems())),
            'channel_limit': self.channel_limit.GetValue(),
            'naming': self.naming_choice.GetSelection(),
        }

    def _show_interpretation_complete(self, changed_labels):
        """Always shown after a successful interpretation (Issue 3):
        without this, a successful call that happens to produce fields
        identical to what was already entered looks exactly like the
        button silently doing nothing, which is indistinguishable from
        a failure a user can't otherwise detect."""
        if changed_labels:
            bullets = '\n'.join(
                '• %s' % label for label in changed_labels)
            msg = _(
                'Your description was successfully interpreted.\n\n'
                'Updated fields:\n\n%s\n\n'
                'Review the interpreted values before continuing.') % (
                bullets)
        else:
            msg = _(
                'The AI interpretation completed successfully.\n\n'
                'The interpreted values already matched the current '
                'selections.\n\n'
                'No changes were required.')
        wx.MessageDialog(self, msg, _('AI Interpretation Complete'),
                         style=wx.OK | wx.ICON_INFORMATION).ShowModal()

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
        # Checking services programmatically here (as opposed to a
        # real user click) does not fire EVT_CHECKLISTBOX, so the
        # Next button/status message need an explicit refresh too.
        self._refresh_services_status()

    def _refresh_services_status(self):
        self.validate_next()
        if self._validate_next():
            self.services_status.SetLabel('')
        else:
            self.services_status.SetLabel(
                _('Check at least one requested service to continue.'))

    def _validate_next(self):
        return bool(self.services.GetCheckedItems())

    def _on_services_changed(self, event):
        self._refresh_services_status()
        event.Skip()

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
        self.endpoint.SetHint('http://localhost:11434/api/chat')
        grid.Add(wx.StaticText(self, label=_('Endpoint URL:')), 0,
                 wx.ALIGN_CENTER_VERTICAL)
        grid.Add(self.endpoint, 1, wx.EXPAND)

        endpoint_hint = wx.StaticText(self, label=_(
            'The provider posts directly to this exact URL. For '
            'Ollama, include the path: http://localhost:11434/api/'
            'chat -- entering only http://localhost:11434 will fail '
            'with an HTTP 405 error. Use "Validate AI Config" below '
            'to check this before use.'))
        endpoint_hint.Wrap(420)
        grid.Add(wx.StaticText(self), 0)
        grid.Add(endpoint_hint, 0, wx.EXPAND)

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

        validate_row = wx.BoxSizer(wx.HORIZONTAL)
        self.validate_btn = wx.Button(self, label=_('Validate AI Config'))
        self.validate_btn.Bind(wx.EVT_BUTTON, self._on_validate)
        validate_row.Add(self.validate_btn, 0, wx.RIGHT, 10)
        self.validate_gauge = wx.Gauge(
            self, range=100, size=(120, -1), style=wx.GA_HORIZONTAL)
        self.validate_gauge.Hide()
        validate_row.Add(self.validate_gauge, 0,
                         wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 10)
        self.validate_status = wx.StaticText(self, label='')
        validate_row.Add(self.validate_status, 1, wx.ALIGN_CENTER_VERTICAL)
        vbox.Add(validate_row, 0,
                 wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        vbox.Add(self.CreateButtonSizer(wx.OK | wx.CANCEL), 0,
                 wx.EXPAND | wx.ALL, 10)
        self.Bind(wx.EVT_BUTTON, self._on_ok, id=wx.ID_OK)
        self.Bind(wx.EVT_BUTTON, self._on_cancel, id=wx.ID_CANCEL)
        self.Bind(wx.EVT_CLOSE, self._on_close)
        self.Bind(EVT_VALIDATE_THREAD, self._on_validate_done)

        self._validate_thread = None
        self._validate_cancel_event = None
        self._pulse_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self._on_pulse_timer, self._pulse_timer)

        # Ensure every control (including the buttons added just above)
        # is accounted for in the dialog's initial size -- without
        # this, the dialog can open smaller than its own contents need,
        # with OK/Cancel not visible until manually resized (Windows
        # validation finding). wx.RESIZE_BORDER above still lets the
        # user resize it further; this only fixes the *initial* size.
        vbox.Fit(self)
        self.SetMinSize(self.GetSize())
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

    def _set_ok_enabled(self, enabled):
        ok_btn = self.FindWindowById(wx.ID_OK)
        if ok_btn:
            ok_btn.Enable(enabled)

    def _current_api_key(self):
        # Matches _get_api_key()'s own precedence: when the field is
        # disabled (CHIRP_ASSISTANT_API_KEY is set), that's what a real
        # extract_intent() call would actually use, not the (empty,
        # disabled) text control -- validation must exercise the same
        # value the real "Interpret with AI" call would.
        if self.api_key.IsEnabled():
            return self.api_key.GetValue()
        return _get_api_key()

    def _on_validate(self, event):
        if self._validate_thread:
            return
        kind = providers.ALL_PROVIDER_KINDS[self.kind_choice.GetSelection()]
        if kind == providers.PROVIDER_DISABLED:
            self.validate_status.SetLabel(
                _('Select a provider (not Disabled) to validate.'))
            return
        try:
            # Built from the CONTROLS' current values, not CONF -- this
            # must validate unsaved edits, since the whole point is
            # letting the user check a configuration before committing
            # it with OK.
            provider = providers.create_provider(
                kind, endpoint=self.endpoint.GetValue().strip(),
                model=self.model.GetValue().strip(),
                api_key=self._current_api_key())
        except providers.ProviderError as e:
            self.validate_status.SetLabel(_('Error: %s') % e)
            return

        self._validate_cancel_event = threading.Event()
        self.validate_btn.Enable(False)
        self._set_ok_enabled(False)
        self.validate_status.SetLabel(_('Validating...'))
        self.validate_gauge.Show()
        self._pulse_timer.Start(100)
        self.Layout()

        self._validate_thread = threading.Thread(
            target=self._validate_worker,
            args=(provider, self._validate_cancel_event))
        self._validate_thread.start()

    def _on_pulse_timer(self, event):
        self.validate_gauge.Pulse()

    def _validate_worker(self, provider, cancel_event):
        # Exercises the exact same extract_intent() path "Interpret
        # with AI" uses -- create_provider() -> HTTP request ->
        # response parsing -> schema validation -- never a separate
        # connectivity-only check (e.g. GET /api/tags), so a
        # successful validation means the configuration will actually
        # work for a real request, not just that the endpoint answers.
        try:
            provider.extract_intent(
                _VALIDATION_PROMPT, cancel_event=cancel_event)
            _safe_post_event(self, ValidateThreadEvent(
                self.GetId(), ok=True, error=None,
                cancelled=cancel_event.is_set()))
        except providers.ProviderCancelled:
            _safe_post_event(self, ValidateThreadEvent(
                self.GetId(), ok=False, error=None, cancelled=True))
        except providers.ProviderError as e:
            # str(e) is guaranteed safe to show directly -- see
            # providers.ProviderError's own docstring: never an API
            # key, an Authorization header, a stack trace, or a raw
            # provider response body.
            _safe_post_event(self, ValidateThreadEvent(
                self.GetId(), ok=False, error=str(e),
                cancelled=cancel_event.is_set()))

    def _on_validate_done(self, event):
        self._validate_thread = None
        self._validate_cancel_event = None
        self._pulse_timer.Stop()
        self.validate_gauge.Hide()
        self.validate_btn.Enable(True)
        self._set_ok_enabled(True)
        self.Layout()

        if event.cancelled:
            self.validate_status.SetLabel(_('Validation cancelled.'))
            return
        if event.ok:
            self.validate_status.SetLabel(_('Configuration is valid.'))
            provider_label = self.kind_choice.GetString(
                self.kind_choice.GetSelection())
            msg = _(
                'Successfully connected.\n\n'
                'Provider: %(provider)s\n'
                'Model: %(model)s\n'
                'Endpoint: %(endpoint)s\n\n'
                'The provider successfully interpreted the validation '
                'request.') % {
                'provider': provider_label,
                'model': self.model.GetValue().strip(),
                'endpoint': self.endpoint.GetValue().strip(),
            }
            wx.MessageDialog(self, msg, _('AI Configuration Valid'),
                             style=wx.OK | wx.ICON_INFORMATION).ShowModal()
        else:
            self.validate_status.SetLabel(_('Validation failed.'))
            wx.MessageDialog(self, event.error,
                             _('AI Configuration Error'),
                             style=wx.OK | wx.ICON_ERROR).ShowModal()

    def _on_cancel(self, event):
        if self._validate_thread:
            # Cancel, while a validation is in flight, cancels the
            # validation (checked by the provider before/after its one
            # network call -- see providers.AIProvider.extract_intent's
            # own docstring on why true mid-request interruption isn't
            # attempted) rather than closing the dialog out from under
            # the still-running background thread.
            self._validate_cancel_event.set()
            self.validate_status.SetLabel(_('Cancelling...'))
            return
        event.Skip()

    def _on_close(self, event):
        # The dialog's title-bar close button/Escape reach EVT_CLOSE
        # directly, bypassing the wx.ID_CANCEL button-click handling
        # above -- same guard, so a validation in flight can't have its
        # target window destroyed out from under it (the background
        # thread's _safe_post_event() call would then just silently
        # drop the result, but stopping that from happening at all is
        # simpler and avoids a validation nobody ever sees the outcome
        # of).
        if self._validate_thread and event.CanVeto():
            event.Veto()
            self._validate_cancel_event.set()
            self.validate_status.SetLabel(_('Cancelling...'))
            return
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
        self._built_signature = None

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

    def page_shown(self):
        # Populate immediately, not only when the user first attempts
        # to leave -- see validate_success() below, which _also_ calls
        # this (harmlessly redundant on a fresh arrival, but necessary
        # to reflect an edit made after Back) since it's the point
        # that decides whether to veto/rebuild. Calling it here too is
        # what makes the summary visible the instant Confirm is shown,
        # rather than only after a first (silently absorbed) Next
        # click -- the request is already fully populated by
        # DescribePage.validate_success() by the time this page
        # becomes current, so there's nothing to wait for.
        self._refresh_summary()

    def _current_signature(self):
        """A snapshot of everything that affects what build_plan()
        would produce: the request as of right now (a value-equal
        copy, since self.context.request is mutated in place -- a
        stored reference would always compare equal to itself) plus
        this page's own two checkboxes, which build_plan() also
        depends on but which live here, not on the request."""
        return (dataclasses.replace(self.context.request),
                self.network_allowed.GetValue(),
                self.share_precise.GetValue())

    def _is_stale(self):
        return (not self._built or
                self._current_signature() != self._built_signature)

    def validate_success(self, event):
        self._refresh_summary()
        if self._build_thread:
            event.Veto()
            return
        if self._is_stale():
            event.Veto()
            self._start_build()

    def _validate_next(self):
        # Gating/rebuilding happens in validate_success() (fired on an
        # actual Next click), not here (fired whenever this page merely
        # becomes current) -- this only needs to keep the button
        # disabled while a background build is in flight.
        return self._build_thread is None

    def _validate_prev(self):
        # Also block Back while a build is in flight: if the user
        # left for Describe mid-build, _build_done()'s auto-advance
        # (below) would otherwise try to move a page the user is no
        # longer looking at forward to Review out from under them.
        return super()._validate_prev() and self._build_thread is None

    def _start_build(self):
        self.status.SetLabel(_('Building plan...'))
        req = self.context.request
        req.share_precise_location = self.share_precise.GetValue()
        network_allowed = self.network_allowed.GetValue()
        self._built_signature = self._current_signature()
        self._build_thread = threading.Thread(
            target=self._build_worker, args=(network_allowed,))
        self._build_thread.start()
        self.validate_next()

    def _build_worker(self, network_allowed):
        try:
            plan = self.context.service.build_plan(
                self.context.request, network_allowed=network_allowed)
            self.context.service.convert_and_validate(plan)
            _safe_post_event(self, BuildThreadEvent(
                self.GetId(), plan=plan, error=None))
        except Exception as e:
            LOG.exception('Failed to build assistant plan: %s', e)
            _safe_post_event(self, BuildThreadEvent(
                self.GetId(), plan=None, error=str(e)))

    def _build_done(self, event):
        self._build_thread = None
        if event.error:
            # Deliberately NOT setting self._built here: context.plan
            # stays None, and leaving _built False means the next
            # click retries the build (using whatever the user may
            # have changed in the meantime) instead of being
            # permanently stuck, or -- worse -- treating this failed
            # attempt as "fresh" and letting the wizard proceed to
            # Review with no plan at all.
            self.status.SetLabel(_('Error: %s') % event.error)
            self.context.plan = None
        else:
            self._built = True
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
        if not event.error and self.context.wizard.GetCurrentPage() is self:
            # A single Next click starts the build; once it succeeds,
            # advance automatically instead of leaving the user to
            # notice the status text changed and click Next again --
            # a second click that does nothing new-looking otherwise
            # reads as broken. Only do this if we're still the page
            # being shown: the user could have clicked Back while the
            # build was running (now prevented by _validate_prev()
            # above, but guard anyway in case that ever changes).
            self.context.wizard.ShowPage(self.GetNext(), True)

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
        btn_row.Add(details_btn, 0, wx.RIGHT, 10)
        self.source_details_btn = wx.Button(
            self, label=_('Source Details...'))
        self.source_details_btn.Bind(wx.EVT_BUTTON, self._on_source_details)
        self.source_details_btn.Hide()
        btn_row.Add(self.source_details_btn, 0)
        vbox.Add(btn_row, 0, wx.ALL, 10)

        self.source_status = wx.StaticText(self, label='')
        vbox.Add(self.source_status, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        self._row_candidates = []

    def _on_details(self, event):
        wx.MessageDialog(self, _DISCLAIMER, _('Regulatory & Privacy Details'),
                         style=wx.OK | wx.ICON_INFORMATION).ShowModal()

    def _on_source_details(self, event):
        plan = self.context.plan
        messages = [w.message for w in plan.warnings] if plan else []
        wx.MessageDialog(
            self, '\n\n'.join(messages), _('Source Details'),
            style=wx.OK | wx.ICON_INFORMATION).ShowModal()

    def page_shown(self):
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

        # plan.warnings (source-unavailable, location-not-resolved,
        # zero-matching-records, unsupported-service, etc. -- see
        # chirp.assistant.sources.build_candidates) previously only
        # ever reached the user on the post-Apply Result page, via
        # plan.skipped_sources' bare source names with no explanation.
        # Surfacing them here means a request that fell back to
        # simplex-only results (e.g. because a repeater source
        # returned nothing) says so before the user reviews/approves
        # the list, instead of the list silently looking like a fully
        # satisfied repeater request.
        if plan.warnings:
            self.source_status.SetLabel(
                _('%i source note(s) -- some requested data may be '
                  'incomplete.') % len(plan.warnings))
            self.source_details_btn.Show()
        else:
            self.source_status.SetLabel('')
            self.source_details_btn.Hide()
        self.Layout()

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
        checked = self.list.IsItemChecked(idx)
        if checked and candidate.errors:
            # A candidate with validation errors is blocked and can
            # never be included -- finalize_for_apply() re-checks and
            # would silently skip it at apply time regardless, but
            # reverting the checkbox here instead gives immediate
            # feedback that this row can't be selected, rather than
            # letting Next look enabled for a selection that would
            # silently do nothing.
            self.list.CheckItem(idx, False)
            candidate.include = False
        else:
            candidate.include = checked
        # Nothing else re-evaluates the wizard's Next button just
        # because the page is sitting there being interacted with --
        # see AssistantPage.validate_next()'s own docstring, and
        # DescribePage._on_services_changed() for the identical fix
        # applied there. Without this call, Next stayed stuck at
        # whatever it was when the page first became current until
        # the user navigated away and back (which re-triggers
        # page_shown() + validate_next() via _wire_wizard_events).
        self.validate_next()

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

    def page_shown(self):
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
        # wx relabels this button "Finish" on its own, since GetNext()
        # is None -- but never enables it on its own; that's this
        # page's job, same as every other page's Next button. Gate on
        # _applied (set by page_shown(), which runs before
        # validate_next() -- see _wire_wizard_events()) rather than
        # unconditional True/False, so Finish never becomes clickable
        # before the apply it's supposed to be confirming has actually
        # happened.
        return self._applied

    def GetPrev(self):
        # Deliberately no way back from Result: Apply already ran
        # (page_shown(), one-shot) by the time this page is visible,
        # and it is not itself undoable-and-rebuildable via wizard
        # navigation -- only via the editor's own Undo afterward. Back
        # returning "to Review" would misleadingly suggest re-applying
        # is possible/safe. GetPrev() alone doesn't disable the Back
        # button in this wx binding (confirmed empirically -- it stays
        # enabled and clicking it does something undefined, observed
        # as closing the wizard); AssistantPage.validate_next() now
        # explicitly disables it whenever GetPrev() is None, which is
        # what actually prevents that here.
        return None


def _wire_wizard_events(wizard):
    """Bind the two page-transition events every AssistantPage relies
    on. Factored out of do_programming_assistant() so tests can drive
    a real wizard through real ShowPage()/button-click transitions
    with the exact same wiring production uses, instead of calling
    page_shown()/validate_success() directly and only ever exercising
    each page in isolation -- see the "no page can advance..." review
    finding for why that isolation previously hid a real defect
    (ResultPage.validate_success() could never fire at all, since it
    only runs on the page being LEFT during a forward transition, and
    Result has no next page to leave towards -- Apply never ran)."""

    def _on_page_changed(e):
        page = e.GetPage()
        # page_shown() first: it may populate/refresh content
        # (ReviewPage's list, ResultPage's apply) that validate_next()
        # -> _validate_next() then needs to inspect to set the
        # Next/Finish button's initial enabled state correctly.
        page.page_shown()
        page.validate_next()

    wizard.Bind(wx.adv.EVT_WIZARD_PAGE_CHANGED, _on_page_changed)
    wizard.Bind(wx.adv.EVT_WIZARD_PAGE_CHANGING,
                lambda e: (e.GetPage().validate_success(e)
                           if e.GetDirection() else None))


_LAUNCH_IN_PROGRESS = set()

_NO_EDITOR_ERROR = _(
    'Programming Assistant could not create a new memory editor.\n\n'
    'No compatible memory editor is currently available. Create a new '
    'radio image manually and try again.'
)


def _show_no_editor_error(parent):
    wx.MessageDialog(
        parent, _NO_EDITOR_ERROR, _('Programming Assistant'),
        style=wx.OK | wx.ICON_ERROR).ShowModal()


def _ensure_blank_memory_document(chirpmain):
    """Creates a new blank memory document through CHIRP's normal
    New-document workflow -- the same chirpmain.open_file('Untitled.
    csv', exists=False) call Radio > New uses -- and leaves it as the
    active tab, so a subsequent AssistantContext(...) construction
    resolves a real, already-initialized memory editor from it rather
    than a stale reference to whatever tab was active before.

    This is a synchronous call: open_file() constructs a real
    generic_csv.CSVRadio(None) (a blank, in-memory-only radio -- the
    same one this project's tests, and CSVRadio(None) callers
    generally, already rely on: no file I/O, no serial port, no
    hardware detection), builds a real ChirpEditorSet around it
    (which synchronously constructs and refreshes its
    memedit.ChirpMemEdit inside its own __init__ -- confirmed by
    reading chirp.wxui.main.ChirpEditorSet.__init__, which has no
    thread, timer, or deferred (wx.CallAfter-style) step anywhere in
    this path), and registers+selects it as a normal tab via
    add_editorset(). By the time this function returns, there is
    nothing left to wait for.

    Returns True if a compatible memory editor is present on the
    (now current) tab afterward, False otherwise -- covering both a
    raised exception during creation and the -- unreachable via this
    exact call, but checked defensively rather than assumed -- case
    of creation completing without leaving a usable editor behind.
    Never raises: do_programming_assistant() below treats False as an
    actionable, sanitized error condition, not an unhandled exception.
    """
    try:
        chirpmain.open_file('Untitled.csv', exists=False)
    except Exception as e:
        LOG.exception(
            'Failed to create a blank memory document for Programming '
            'Assistant launch: %s', e)
        return False
    return _find_memedit(chirpmain.current_editorset) is not None


@common.error_proof()
def do_programming_assistant(parent, event):
    # A modal wx.adv.Wizard (below) blocks this window's own event
    # loop for as long as it's open, so in practice a second EVT_MENU
    # for this same command cannot be dispatched while one is already
    # running against the same @parent -- but a stale queued event or
    # a programmatic re-entry could still reach here before the first
    # call's own `finally` clears this, so the guard is real, not
    # decorative. Keyed by id(parent) (not a single flag) since CHIRP
    # supports more than one top-level main window (see
    # _menu_new_window) -- launching in one window must not block
    # launching in another.
    launch_key = id(parent)
    if launch_key in _LAUNCH_IN_PROGRESS:
        return
    _LAUNCH_IN_PROGRESS.add(launch_key)

    wizard = None
    try:
        wizard = wx.adv.Wizard(parent)
        wizard.SetPageSize((620, 520))

        context = AssistantContext(wizard, parent)

        if context.memedit is None:
            # The normal case for a freshly launched CHIRP, or a
            # non-memory (Settings/Banks-only, or no image at all) tab
            # active -- no longer a dead end: create a new blank
            # memory document through the same workflow Radio > New
            # uses, exactly as if the user had done so manually, then
            # continue with that as the target.
            if not _ensure_blank_memory_document(parent):
                _show_no_editor_error(parent)
                return
            # Re-resolve against whatever is now the active tab -- the
            # document just created, not the (possibly still-absent-a-
            # memedit) tab that was active when this function started.
            context = AssistantContext(wizard, parent)
            if context.memedit is None:
                # Reachable only if a future change breaks the
                # invariant _ensure_blank_memory_document's own
                # docstring proves today -- kept as a real check
                # rather than an assumption, per the same "do not
                # leave a partially initialized assistant open"
                # principle as the branch above.
                LOG.error(
                    'Blank memory document created but no compatible '
                    'memory editor was found on the resulting tab')
                _show_no_editor_error(parent)
                return

        audit.dialog_opened()

        _wire_wizard_events(wizard)

        start = context.get_page('describe', DescribePage)
        wizard.GetPageAreaSizer().Add(start)
        wizard.RunWizard(start)
    finally:
        # Always cleared/destroyed, on every exit path -- success,
        # cancellation, the no-editor-available error returns above,
        # or an exception @common.error_proof() will catch after this
        # function returns -- so a failed or cancelled launch never
        # leaves the menu command permanently unusable. A background
        # _build_worker()/_interpret_worker() thread may still be in
        # flight at this point if the user cancelled or closed the
        # wizard early; each posts its result via _safe_post_event()
        # below rather than directly, so a stale post to an
        # already-destroyed page is dropped instead of raising into
        # the worker thread.
        _LAUNCH_IN_PROGRESS.discard(launch_key)
        if wizard is not None:
            wizard.Destroy()
