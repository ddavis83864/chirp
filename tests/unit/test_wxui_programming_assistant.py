"""Real-wx (not mocked) tests for the Programming Assistant wizard.

Unlike most chirp.wxui.* tests, this module needs actual wx.adv.Wizard/
WizardPage behavior (page chaining, Next-button gating) that isn't
meaningfully exercisable behind a MagicMock, so it uses the real
wxPython installed in the test environment instead of the
sys.modules['wx']-mocking pattern used elsewhere (see
test_wxui_memquery.py). CI must have wxPython available for this file
to run (it already does, per tox.ini's [testenv:unit] sitepackages).
"""

import os
import sys
import tempfile
import unittest
from unittest import mock

# Other test modules (e.g. test_wxui_memquery.py) mock sys.modules['wx']
# at import time to test wx.* code without a real wx runtime. Since
# pytest imports all test modules into the same process, that mock can
# still be sitting in sys.modules by the time this file is collected,
# which breaks the real `import wx.adv`/`import wx.lib.newevent` this
# file actually needs. Purge any such entries first so this file always
# gets a genuine wx import regardless of collection order.
for _name in [n for n in sys.modules
              if n == 'wx' or n.startswith('wx.')]:
    del sys.modules[_name]

import wx  # noqa: E402
import wx.adv  # noqa: E402

from chirp import chirp_common  # noqa: E402
from chirp.assistant import models  # noqa: E402
from chirp.drivers import generic_csv  # noqa: E402
from chirp.wxui import config  # noqa: E402
from chirp.wxui import memedit  # noqa: E402
from chirp.wxui import programming_assistant  # noqa: E402

_TEST_CSV = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))), 'test.csv')

_APP = wx.App()


class _FakeEditorSet:
    def __init__(self, radio, editor):
        self.radio = radio
        self.current_editor = editor
        self._editor_index = {'Memories': editor}


class _FakeChirpMain:
    def __init__(self, editorset):
        self.current_editorset = editorset


class ProgrammingAssistantWxTestBase(unittest.TestCase):
    def setUp(self):
        config._CONFIG = config.ChirpConfig(tempfile.mkdtemp())
        self.radio = generic_csv.CSVRadio(_TEST_CSV)
        self.frame = wx.Frame(None)
        # Real menu bar so memedit's own _update_menu() (called by its
        # pre-existing undo_context() on every apply, unrelated to this
        # feature) has real Undo/Redo/TX-workflow items to update,
        # matching what main.ChirpMain always provides in the real app.
        menubar = wx.MenuBar()
        editmenu = wx.Menu()
        editmenu.Append(wx.ID_UNDO)
        editmenu.Append(wx.ID_REDO)
        editmenu.Append(wx.MenuItem(editmenu, memedit.TX_WORKFLOW_ID,
                                    'Use TX Frequency Workflow',
                                    kind=wx.ITEM_CHECK))
        menubar.Append(editmenu, '&Edit')
        self.frame.SetMenuBar(menubar)

        self.editor = memedit.ChirpMemEdit(self.radio, self.frame)
        self.editor.refresh()
        eset = _FakeEditorSet(self.radio, self.editor)
        self.chirpmain = _FakeChirpMain(eset)
        self.wizard = wx.adv.Wizard(self.frame)
        self.context = programming_assistant.AssistantContext(
            self.wizard, self.chirpmain)

    def tearDown(self):
        self.frame.Destroy()


class HelperFunctionTest(unittest.TestCase):
    def test_parse_ranges_basic(self):
        self.assertEqual(((0, 9), (90, 99)),
                         programming_assistant._parse_ranges('0-9, 90-99'))

    def test_parse_ranges_single_number(self):
        self.assertEqual(((5, 5),),
                         programming_assistant._parse_ranges('5'))

    def test_parse_ranges_empty(self):
        self.assertEqual((), programming_assistant._parse_ranges(''))

    def test_parse_ranges_ignores_garbage(self):
        self.assertEqual(((0, 9),),
                         programming_assistant._parse_ranges('0-9, banana'))

    def test_freq_str_formats_mhz(self):
        self.assertEqual('146.5200',
                         programming_assistant._freq_str(146520000))

    def test_freq_str_none(self):
        self.assertEqual('', programming_assistant._freq_str(None))

    def test_safe_post_event_survives_destroyed_target(self):
        # Regression coverage for a use-after-close review finding:
        # _interpret_worker()/_build_worker() run on a background
        # thread and post their result back to a wizard page via
        # wx.PostEvent -- if the user cancelled/closed the wizard
        # while that thread was still running, the target page (and
        # its wx C++ object) may already be destroyed. Confirmed
        # empirically that wx.PostEvent on a destroyed window raises
        # RuntimeError (not a silent no-op) -- _safe_post_event must
        # swallow that rather than letting it escape a worker thread.
        frame = wx.Frame(None)
        frame.Destroy()
        wx.GetApp().Yield()

        try:
            programming_assistant._safe_post_event(
                frame, wx.CommandEvent(wx.EVT_MENU.typeId, 1))
        except RuntimeError:
            self.fail('_safe_post_event let RuntimeError escape for a '
                      'destroyed target window')

    def test_safe_post_event_delivers_to_live_target(self):
        # Deliberately not relying on a real wx event-loop round trip
        # (PostEvent + Yield()) here -- that's timing-sensitive and
        # this only needs to confirm _safe_post_event doesn't swallow
        # events for a live (non-destroyed) target, which is the
        # actual behavior under test.
        frame = wx.Frame(None)
        self.addCleanup(frame.Destroy)
        evt = wx.CommandEvent(wx.EVT_MENU.typeId, 1)

        with mock.patch(
                'chirp.wxui.programming_assistant.wx.PostEvent'
                ) as mock_post:
            programming_assistant._safe_post_event(frame, evt)

        mock_post.assert_called_once_with(frame, evt)


class AssistantContextTest(ProgrammingAssistantWxTestBase):
    def test_finds_memedit_from_current_editor(self):
        self.assertIs(self.editor, self.context.memedit)

    def test_finds_memedit_when_other_tab_selected(self):
        eset = _FakeEditorSet(self.radio, None)  # simulate Banks tab active
        eset._editor_index = {'Memories': self.editor, 'Banks': None}
        chirpmain = _FakeChirpMain(eset)
        context = programming_assistant.AssistantContext(
            self.wizard, chirpmain)
        self.assertIs(self.editor, context.memedit)

    def test_default_provider_is_disabled(self):
        self.assertEqual('disabled', self.context.provider().kind)

    def test_get_page_caches_instances(self):
        p1 = self.context.get_page(
            'describe', programming_assistant.DescribePage)
        p2 = self.context.get_page(
            'describe', programming_assistant.DescribePage)
        self.assertIs(p1, p2)


class _FakeWizardEvent:
    """Stands in for the wx.adv.WizardEvent passed to validate_success()
    -- just enough to record whether the page vetoed the transition."""

    def __init__(self):
        self.vetoed = False

    def Veto(self):
        self.vetoed = True


class ConfirmPageBuildFreshnessTest(ProgrammingAssistantWxTestBase):
    """Regression coverage for a defect found reviewing wizard
    navigation: ConfirmPage built its plan once, eagerly, using
    whatever request/checkbox state happened to exist the instant the
    page became current, then cached it forever -- so going Back to
    Describe and changing services/location, or toggling this page's
    own "network allowed"/"share precise location" checkboxes, had no
    effect on the plan actually used, contradicting the page's own
    text ("Nothing is queried or built until you continue -- go back
    to correct anything.").

    These tests run the build synchronously -- both the background
    thread (real OS threading.Thread is replaced with one that just
    calls its target immediately, in-line) and the wx.PostEvent
    round-trip (replaced with a direct call to _build_done()) -- so
    they're deterministic and don't depend on real cross-thread wx
    event delivery, which other test modules in this suite are not
    always careful to leave in a clean, real (non-mocked) state for
    whichever test file happens to be collected after them.
    """

    def setUp(self):
        super().setUp()
        self.context.request.requested_services = (models.SERVICE_HAM,)
        self.page = self.context.get_page(
            'confirm', programming_assistant.ConfirmPage)

    class _ImmediateThread:
        """Stands in for threading.Thread: runs its target immediately,
        in the calling thread, instead of spawning a real OS thread."""

        def __init__(self, target=None, args=()):
            self._target = target
            self._args = args

        def start(self):
            self._target(*self._args)

        def join(self, timeout=None):
            pass

    def _run_build_synchronously(self, captured_network_allowed):
        def fake_post_event(target, event):
            target._build_done(event)

        real_build_plan = self.context.service.build_plan

        def fake_build_plan(request, network_allowed=True):
            captured_network_allowed.append(network_allowed)
            # Stay offline in tests regardless of what the checkbox
            # said -- only the *value passed through* is under test.
            return real_build_plan(request, network_allowed=False)

        with mock.patch(
                'chirp.wxui.programming_assistant.wx.PostEvent',
                side_effect=fake_post_event), \
                mock.patch.object(
                    self.context.service, 'build_plan',
                    side_effect=fake_build_plan), \
                mock.patch(
                    'chirp.wxui.programming_assistant.threading.Thread',
                    self._ImmediateThread):
            event = _FakeWizardEvent()
            self.page.validate_success(event)
        return event

    def test_first_click_builds_and_vetoes_once(self):
        event = self._run_build_synchronously([])
        self.assertTrue(event.vetoed)
        self.assertTrue(self.page._built)
        self.assertIsNotNone(self.context.plan)

        # A second click, with nothing changed, must NOT veto again --
        # it should just let the wizard proceed to Review.
        event2 = self._run_build_synchronously([])
        self.assertFalse(event2.vetoed)

    def test_remote_checkbox_read_at_click_time_not_page_arrival(self):
        # Simulate the user unchecking "Allow network source queries"
        # AFTER the page is shown but BEFORE clicking Next.
        self.page.network_allowed.SetValue(True)
        self.page.validate_next()  # page just became current
        self.page.network_allowed.SetValue(False)

        captured = []
        self._run_build_synchronously(captured)

        self.assertEqual([False], captured)

    def test_editing_describe_after_back_rebuilds_plan(self):
        captured = []
        self._run_build_synchronously(captured)
        self.assertEqual(1, len(captured))
        first_plan = self.context.plan
        self.assertTrue(
            any(c.service == models.SERVICE_HAM
                for c in first_plan.all_candidates))

        # Simulate Back to Describe, changing the request, then
        # forward to Confirm again -- DescribePage.validate_success is
        # what actually mutates context.request in the real wizard.
        self.context.request.requested_services = (models.SERVICE_WEATHER,)

        captured2 = []
        event2 = self._run_build_synchronously(captured2)

        self.assertTrue(event2.vetoed,
                        'stale plan was reused instead of rebuilding '
                        'after the request changed')
        second_plan = self.context.plan
        self.assertIsNot(first_plan, second_plan)
        self.assertTrue(
            any(c.service == models.SERVICE_WEATHER
                for c in second_plan.all_candidates))

    def test_build_failure_allows_retry_not_silent_advance(self):
        # A failed build must never be treated as "successfully built"
        # -- that would let the wizard proceed to Review with
        # context.plan still None (nothing to show, nothing to apply)
        # instead of giving the user a chance to fix the problem and
        # retry.
        def fake_post_event(target, event):
            target._build_done(event)

        with mock.patch(
                'chirp.wxui.programming_assistant.wx.PostEvent',
                side_effect=fake_post_event), \
                mock.patch.object(
                    self.context.service, 'build_plan',
                    side_effect=RuntimeError('simulated build failure')), \
                mock.patch(
                    'chirp.wxui.programming_assistant.threading.Thread',
                    self._ImmediateThread):
            event = _FakeWizardEvent()
            self.page.validate_success(event)

        self.assertTrue(event.vetoed)
        self.assertIsNone(self.context.plan)
        self.assertFalse(self.page._built)

        # Retrying (e.g. after the user notices the error and clicks
        # Next again) must attempt another build, not silently pass
        # through with the still-None plan.
        captured = []
        event2 = self._run_build_synchronously(captured)
        self.assertTrue(event2.vetoed)
        self.assertEqual(1, len(captured))
        self.assertIsNotNone(self.context.plan)


class ReviewPageTest(ProgrammingAssistantWxTestBase):
    def _plan_with_one_ready_one_blocked(self):
        ready = models.ChannelCandidate(
            source='s', service=models.SERVICE_WEATHER, group='Weather',
            label='NOAA 1', freq=162400000, mode='FM',
            status=models.STATUS_RECEIVE_ONLY, receive_only=True,
            include=True, memory_number=1, name='WX1')
        blocked = models.ChannelCandidate(
            source='s', service=models.SERVICE_HAM, group='Amateur Simplex',
            label='Bad', freq=99999999999, mode='FM',
            status=models.STATUS_BLOCKED, include=False,
            errors=('out of range',))
        return models.ChannelPlan(groups=[
            models.PlanGroup(name='Weather', candidates=[ready]),
            models.PlanGroup(name='Amateur Simplex', candidates=[blocked]),
        ])

    def test_populate_creates_one_row_per_candidate(self):
        self.context.plan = self._plan_with_one_ready_one_blocked()
        page = programming_assistant.ReviewPage(self.context)
        page._populate()
        self.assertEqual(2, page.list.GetItemCount())
        self.assertEqual(2, len(page._row_candidates))

    def test_next_disabled_when_nothing_included(self):
        blocked = models.ChannelCandidate(
            source='s', service=models.SERVICE_HAM, group='g', label='Bad',
            freq=1, include=False, status=models.STATUS_BLOCKED)
        self.context.plan = models.ChannelPlan(
            groups=[models.PlanGroup(name='g', candidates=[blocked])])
        page = programming_assistant.ReviewPage(self.context)
        page._populate()
        self.assertFalse(page._validate_next())

    def test_next_enabled_when_something_included(self):
        self.context.plan = self._plan_with_one_ready_one_blocked()
        page = programming_assistant.ReviewPage(self.context)
        page._populate()
        self.assertTrue(page._validate_next())

    def test_unchecking_row_updates_candidate(self):
        self.context.plan = self._plan_with_one_ready_one_blocked()
        page = programming_assistant.ReviewPage(self.context)
        page._populate()
        candidate = page._row_candidates[0]
        self.assertTrue(candidate.include)
        page.list.CheckItem(0, False)
        page._on_check(_FakeIndexEvent(0))
        self.assertFalse(candidate.include)

    def test_rechecking_row_updates_candidate(self):
        self.context.plan = self._plan_with_one_ready_one_blocked()
        page = programming_assistant.ReviewPage(self.context)
        page._populate()
        candidate = page._row_candidates[0]

        page.list.CheckItem(0, False)
        page._on_check(_FakeIndexEvent(0))
        self.assertFalse(candidate.include)

        page.list.CheckItem(0, True)
        page._on_check(_FakeIndexEvent(0))
        self.assertTrue(candidate.include)

    def test_excluding_every_row_disables_next(self):
        self.context.plan = self._plan_with_one_ready_one_blocked()
        page = programming_assistant.ReviewPage(self.context)
        page._populate()
        self.assertTrue(page._validate_next())

        # Only row 0 is include=True to begin with (row 1 is already
        # blocked/excluded) -- uncheck it and confirm Next disables.
        page.list.CheckItem(0, False)
        page._on_check(_FakeIndexEvent(0))
        self.assertFalse(page._validate_next())

    def test_warnings_shown_in_details_column(self):
        warned = models.ChannelCandidate(
            source='s', service=models.SERVICE_HAM, group='g', label='W',
            freq=146520000, mode='FM', status=models.STATUS_ADJUSTED,
            include=True, memory_number=2, name='W1',
            warnings=('Name truncated to fit this radio',))
        self.context.plan = models.ChannelPlan(
            groups=[models.PlanGroup(name='g', candidates=[warned])])
        page = programming_assistant.ReviewPage(self.context)
        page._populate()

        details = page.list.GetItemText(0, 9)
        self.assertIn('Name truncated to fit this radio', details)

    def test_existing_conflict_shown_with_reason(self):
        conflict = models.ChannelCandidate(
            source='s', service=models.SERVICE_HAM, group='g', label='C',
            freq=146520000, mode='FM', status=models.STATUS_EXISTING_CONFLICT,
            include=True, memory_number=3, name='C1',
            reason='Will replace existing memory 3 (Old Channel)')
        self.context.plan = models.ChannelPlan(
            groups=[models.PlanGroup(name='g', candidates=[conflict])])
        page = programming_assistant.ReviewPage(self.context)
        page._populate()

        self.assertEqual(models.STATUS_EXISTING_CONFLICT,
                         page.list.GetItemText(0, 7))
        self.assertIn('Will replace existing memory 3',
                      page.list.GetItemText(0, 9))

    def test_preview_memory_numbers_match_what_apply_would_target(self):
        # The number shown in the "Loc" column must be exactly what
        # finalize_for_apply() would target -- if these ever diverged,
        # the preview would be lying to the user about what Apply does.
        req = models.ProgrammingRequest(
            requested_services=(models.SERVICE_WEATHER,), channel_limit=20)
        plan = self.context.service.build_plan(req, network_allowed=False)
        self.context.service.convert_and_validate(plan)
        self.context.request = req
        self.context.plan = plan

        page = programming_assistant.ReviewPage(self.context)
        page._populate()
        shown_numbers = {int(page.list.GetItemText(i, 0))
                         for i in range(page.list.GetItemCount())
                         if page.list.GetItemText(i, 0)}

        finalized = self.context.service.finalize_for_apply(plan)
        applied_numbers = {memory.number for _c, memory in finalized}
        self.assertTrue(applied_numbers.issubset(shown_numbers))


class _FakeIndexEvent:
    def __init__(self, index):
        self._index = index

    def GetIndex(self):
        return self._index


class ResultPageApplyTest(ProgrammingAssistantWxTestBase):
    def test_apply_creates_one_undo_entry_for_all_candidates(self):
        req = models.ProgrammingRequest(
            requested_services=(models.SERVICE_WEATHER,), channel_limit=20)
        plan = self.context.service.build_plan(req, network_allowed=False)
        self.context.service.convert_and_validate(plan)
        self.context.request = req
        self.context.plan = plan

        page = programming_assistant.ResultPage(self.context)
        page._apply()

        self.assertEqual(1, len(self.editor._undo_queue))
        applied_numbers = [c.memory_number for c in plan.all_candidates
                           if c.include]
        self.assertEqual(7, len(applied_numbers))
        for n in applied_numbers:
            self.assertFalse(self.radio.get_memory(n).empty)

    def test_undo_restores_original_image(self):
        req = models.ProgrammingRequest(
            requested_services=(models.SERVICE_WEATHER,), channel_limit=20)
        plan = self.context.service.build_plan(req, network_allowed=False)
        self.context.service.convert_and_validate(plan)
        self.context.request = req
        self.context.plan = plan
        applied_numbers = [c.memory_number for c in plan.all_candidates
                           if c.include]

        page = programming_assistant.ResultPage(self.context)
        page._apply()
        self.editor._undo(None)

        for n in applied_numbers:
            self.assertTrue(self.radio.get_memory(n).empty)

    def test_apply_never_touches_a_serial_port_or_uploads(self):
        # There is no upload/clone method on AssistantService or the
        # wizard pages at all -- confirm the apply path only calls
        # methods that exist on the in-memory editor/radio.
        req = models.ProgrammingRequest(
            requested_services=(models.SERVICE_WEATHER,), channel_limit=5)
        plan = self.context.service.build_plan(req, network_allowed=False)
        self.context.service.convert_and_validate(plan)
        self.context.request = req
        self.context.plan = plan

        for attr in ('upload', 'clone_to', 'sync_out', 'do_upload'):
            self.assertFalse(hasattr(self.context.service, attr))

        page = programming_assistant.ResultPage(self.context)
        page._apply()
        self.assertIn('Nothing has been uploaded to a radio',
                      page.result.GetValue())

    def test_existing_memories_preserved_through_apply(self):
        existing_occupied = [
            n for n, m in self.context.service.existing_memories
            if not m.empty]
        req = models.ProgrammingRequest(
            requested_services=(models.SERVICE_WEATHER,), channel_limit=5)
        plan = self.context.service.build_plan(req, network_allowed=False)
        self.context.service.convert_and_validate(plan)
        self.context.request = req
        self.context.plan = plan

        page = programming_assistant.ResultPage(self.context)
        page._apply()

        for n in existing_occupied:
            self.assertFalse(self.radio.get_memory(n).empty)

    def test_immutable_memory_blocked_before_apply_not_silently_written(self):
        # generic_csv.CSVRadio doesn't itself enforce
        # check_set_memory_immutable_policy in its own set_memory()
        # (most drivers don't need to), but import_logic.import_mem()
        # -- which converter.convert_candidate() always goes through --
        # calls dst_radio.check_set_memory_immutable_policy() itself
        # during conversion and converter.py catches the resulting
        # ImmutableValueError, well before finalize_for_apply()/_apply()
        # ever run. Confirm that actually holds: a candidate targeting
        # an immutable memory must be blocked at conversion time, never
        # silently written and counted as applied.
        protected_number = 3
        seed = chirp_common.Memory(number=protected_number, name='PROTECT')
        seed.freq = 146520000
        self.radio.set_memory(seed)
        # CSVRadio.set_memory() always clears .immutable on the memory
        # it dupes and stores, so mark it directly on the stored copy
        # afterward -- this simulates a driver that DOES ship with an
        # immutable field on some memory (e.g. a fixed call channel).
        self.radio.memories[protected_number].immutable = ['freq']

        candidate = models.ChannelCandidate(
            source='t', service=models.SERVICE_HAM, group='g',
            label='NEW', freq=146850000, tx_freq=146250000, mode='FM')
        candidate.memory_number = protected_number
        candidate.name = 'NEW'
        plan = models.ChannelPlan(groups=[
            models.PlanGroup(name='g', candidates=[candidate])])
        self.context.service.convert_and_validate(plan)
        self.assertEqual(models.STATUS_BLOCKED, candidate.status)
        self.assertFalse(candidate.include)
        self.context.request = models.ProgrammingRequest()
        self.context.plan = plan

        page = programming_assistant.ResultPage(self.context)
        page._apply()

        self.assertEqual(146520000,
                         self.radio.get_memory(protected_number).freq)
        self.assertIn('Applied: 0', page.result.GetValue())
        self.assertIn('Skipped (not included or invalid): 1',
                      page.result.GetValue())

    def test_partial_apply_failure_reports_and_undo_still_works(self):
        # Apply is explicitly documented as "one undoable action," not
        # an atomic all-or-nothing write (see this module's docstring
        # and the Help-menu disclosure in chirp.wxui.main). Verify that
        # claim precisely: when one candidate in a batch fails mid-apply,
        # an earlier candidate's successful write is NOT rolled back
        # automatically (non-atomic), the failure is reported correctly,
        # and undo_context() alone is still sufficient to revert the
        # whole batch -- including the partial success -- in one action.
        req = models.ProgrammingRequest(
            requested_services=(models.SERVICE_WEATHER,), channel_limit=2)
        plan = self.context.service.build_plan(req, network_allowed=False)
        self.context.service.convert_and_validate(plan)
        self.context.request = req
        self.context.plan = plan

        preview = self.context.service.finalize_for_apply(plan)
        self.assertEqual(2, len(preview))
        first_number = preview[0][1].number
        self.assertTrue(self.radio.get_memory(first_number).empty)

        real_set_memory = self.editor.set_memory
        calls = {'n': 0}

        def flaky_set_memory(mem, refresh=True):
            calls['n'] += 1
            if calls['n'] == 2:
                raise RuntimeError('simulated driver failure')
            return real_set_memory(mem, refresh=refresh)

        self.editor.set_memory = flaky_set_memory
        try:
            page = programming_assistant.ResultPage(self.context)
            page._apply()
        finally:
            self.editor.set_memory = real_set_memory

        # Not atomic: the first candidate's write is still live.
        self.assertFalse(self.radio.get_memory(first_number).empty)
        self.assertIn('Applied: 1', page.result.GetValue())
        self.assertIn('Failed to apply: 1', page.result.GetValue())

        # But the whole batch is still exactly one undo entry, and
        # undoing it reverts the partial success too.
        self.assertEqual(1, len(self.editor._undo_queue))
        self.editor._undo(None)
        self.assertTrue(self.radio.get_memory(first_number).empty)


class DoProgrammingAssistantTest(ProgrammingAssistantWxTestBase):
    """Regression coverage for a Windows validation finding: selecting
    Radio > Programming Assistant with no radio image open at all (no
    ChirpEditorSet tab exists yet, so ChirpMain.current_editorset is
    None) raised 'NoneType' object has no attribute 'current_editor'
    from AssistantContext.__init__ -> _find_memedit(), instead of the
    friendly "No memory editor is available" dialog that
    do_programming_assistant() already intended to show for this exact
    situation. common.error_proof() caught the AttributeError and
    displayed it verbatim as a raw exception dialog rather than letting
    it crash the app outright, which is why the report described a
    Python exception dialog rather than a hard crash.
    """

    def test_no_editor_open_shows_friendly_message_not_a_crash(self):
        # Simulate CHIRP freshly launched: no ChirpEditorSet tab exists
        # yet, so current_editorset is None -- distinct from "a tab is
        # open but it's Settings/Banks, not Memories", which was
        # already handled correctly before this fix.
        self.frame.current_editorset = None

        with mock.patch(
                'chirp.wxui.programming_assistant.wx.MessageDialog'
                ) as mock_dialog_cls, \
                mock.patch(
                    'chirp.wxui.common.error_proof.show_error'
                    ) as mock_show_error:
            mock_dialog_cls.return_value.ShowModal.return_value = wx.ID_OK
            programming_assistant.do_programming_assistant(
                self.frame, None)

        # The intended friendly message fired exactly once...
        mock_dialog_cls.assert_called_once()
        self.assertIn('No memory editor',
                      mock_dialog_cls.call_args[0][1])
        # ...and error_proof() never had to catch an unhandled
        # exception to get there.
        mock_show_error.assert_not_called()

    def test_active_editor_reaches_wizard_run(self):
        self.frame.current_editorset = _FakeEditorSet(
            self.radio, self.editor)

        with mock.patch.object(wx.adv.Wizard, 'RunWizard',
                               return_value=True) as run, \
                mock.patch(
                    'chirp.wxui.common.error_proof.show_error'
                    ) as mock_show_error:
            programming_assistant.do_programming_assistant(
                self.frame, None)

        run.assert_called_once()
        mock_show_error.assert_not_called()


class RealWizardEventFlowTest(ProgrammingAssistantWxTestBase):
    """Drives the wizard through Describe -> Confirm -> Review ->
    Result using real wx.adv.Wizard ShowPage() transitions and the
    exact production event wiring (_wire_wizard_events()), instead of
    calling each page's internal methods directly the way every other
    test in this file does.

    That distinction matters: it's what caught a release-blocking
    defect during review. wx.adv.WizardEvent.GetPage() for
    EVT_WIZARD_PAGE_CHANGING returns the page being LEFT, so
    validate_success() only ever fires on the outgoing page of a
    forward transition. ResultPage has no next page, so
    ResultPage.validate_success() -- which used to contain the entire
    _apply() call -- could never fire in the real app; Apply was
    silently a no-op end to end, and ReviewPage's list, populated the
    same wrong way, stayed empty until the moment the user clicked
    Next past it. Confirmed by reverting the page_shown() fix locally
    and re-running this test: it fails exactly as described (list
    count 0, result._applied False, nothing written to the radio)
    before the fix, and passes after.
    """

    def _click_next(self, wizard, current):
        next_page = current.GetNext()
        self.assertIsNotNone(next_page, 'no next page from %r' % current)
        ok = wizard.ShowPage(next_page, True)
        self.assertTrue(ok, 'wizard refused to advance past %r' % current)
        return next_page

    def test_full_wizard_flow_populates_review_and_applies_result(self):
        wizard = wx.adv.Wizard(self.frame)
        context = programming_assistant.AssistantContext(
            wizard, self.chirpmain)
        programming_assistant._wire_wizard_events(wizard)

        describe = context.get_page(
            'describe', programming_assistant.DescribePage)
        wizard.GetPageAreaSizer().Add(describe)
        wizard.ShowPage(describe)

        describe.services.Check(
            [i for i, (value, _label) in
             enumerate(programming_assistant._SERVICE_LABELS)
             if value == models.SERVICE_WEATHER][0], True)

        confirm = self._click_next(wizard, describe)
        self.assertIsInstance(confirm, programming_assistant.ConfirmPage)
        confirm.network_allowed.SetValue(False)

        # The build runs on a real background thread in production;
        # replace it with one that runs synchronously so this test
        # doesn't depend on real OS-thread timing or a live wx event
        # loop -- the actual thing under test here is wizard page
        # transitions, not threading.
        with mock.patch(
                'chirp.wxui.programming_assistant.wx.PostEvent',
                side_effect=lambda target, evt: target._build_done(evt)), \
                mock.patch(
                    'chirp.wxui.programming_assistant.threading.Thread',
                    ConfirmPageBuildFreshnessTest._ImmediateThread):
            # First click starts the build and is vetoed; second
            # click (now that it's built and nothing changed) proceeds.
            still_confirm = self._click_next_or_veto(wizard, confirm)
            self.assertIs(confirm, still_confirm)
            review = self._click_next(wizard, confirm)

        self.assertIsInstance(review, programming_assistant.ReviewPage)
        # This is the crux of the regression: the list must already be
        # populated as soon as Review is shown, not only once the user
        # tries to leave it.
        self.assertEqual(7, review.list.GetItemCount())
        self.assertEqual(7, len(review._row_candidates))

        result = self._click_next(wizard, review)
        self.assertIsInstance(result, programming_assistant.ResultPage)
        self.assertTrue(result._applied)
        self.assertIn('Applied: 7', result.result.GetValue())
        applied_numbers = [
            c.memory_number for c in context.plan.all_candidates
            if c.include]
        self.assertEqual(7, len(applied_numbers))
        for n in applied_numbers:
            self.assertFalse(self.radio.get_memory(n).empty)

    def _click_next_or_veto(self, wizard, current):
        """Like _click_next(), but for a page (ConfirmPage) whose
        first click may legitimately veto its own transition (to
        start an async build) and stay put."""
        next_page = current.GetNext()
        wizard.ShowPage(next_page, True)
        # wx.adv.Wizard doesn't expose "did the last ShowPage veto"
        # directly in a way independent of GetCurrentPage(), so ask it.
        return wizard.GetCurrentPage()


class MenuIntegrationTest(unittest.TestCase):
    def test_assistant_disabled_by_default(self):
        # Conservative default: the experimental assistant must be
        # opt-in, not opt-out, until it has more field validation.
        config._CONFIG = config.ChirpConfig(tempfile.mkdtemp())
        self.assertFalse(programming_assistant.assistant_enabled())

    def test_set_assistant_enabled_persists(self):
        config._CONFIG = config.ChirpConfig(tempfile.mkdtemp())
        self.assertFalse(programming_assistant.assistant_enabled())

        programming_assistant.set_assistant_enabled(True)
        self.assertTrue(programming_assistant.assistant_enabled())

        programming_assistant.set_assistant_enabled(False)
        self.assertFalse(programming_assistant.assistant_enabled())


if __name__ == '__main__':
    unittest.main()
