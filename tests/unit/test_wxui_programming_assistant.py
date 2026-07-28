"""Real-wx (not mocked) tests for the Programming Assistant wizard.

Unlike most chirp.wxui.* tests, this module needs actual wx.adv.Wizard/
WizardPage behavior (page chaining, Next-button gating) that isn't
meaningfully exercisable behind a MagicMock, so it uses the real
wxPython installed in the test environment instead of the
sys.modules['wx']-mocking pattern used elsewhere (see
test_wxui_memquery.py). CI must have wxPython available for this file
to run (it already does, per tox.ini's [testenv:unit] sitepackages).
"""

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

_APP = None


def _ensure_wx_app():
    """Lazily create the one wx.App this file's real-wx.Frame/wx.adv.
    Wizard-based tests need, instead of constructing it unconditionally
    at module import time.

    wx.App() requires a real (or virtual, e.g. Xvfb) X display --
    confirmed empirically (and via this repo's own CI workflow/action
    files, which set up no virtual display anywhere) that headless CI
    has none. Constructing it eagerly at import time meant this
    entire file -- including tests that never touch a real wx.Frame
    at all, like HelperFunctionTest's _parse_ranges/_freq_str
    coverage -- failed to even collect there, aborting the whole
    `pytest tests/unit` run with no tests from any file able to run.

    Called from the setUp()/test methods that actually construct a
    real wx.Frame, so only *those* tests skip (cleanly, with a clear
    reason) when no display is available, while every other test in
    this file collects and runs normally either way.
    """
    global _APP
    if _APP is not None:
        return _APP
    try:
        _APP = wx.App()
    except SystemExit as e:
        # wx.App.__init__ raises SystemExit (not a more specific
        # exception) when it can't open a display -- confirmed via
        # direct reproduction with DISPLAY/WAYLAND_DISPLAY unset.
        raise unittest.SkipTest(
            'no display available for wx GUI tests: %s' % e)
    return _APP


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
        _ensure_wx_app()
        config._CONFIG = config.ChirpConfig(tempfile.mkdtemp())
        # CSVRadio(None) builds a blank, in-memory-only radio -- no
        # file is read or written, so this can never collide with an
        # unrelated developer file (e.g. a personal test.csv left at
        # the repo root), differ by working directory, or leak state
        # between tests or parallel runs. This was previously
        # generic_csv.CSVRadio applied to a hardcoded repo-root
        # 'test.csv' filename
        # -- when absent (every normal checkout) CSVRadio already fell
        # back to this same blank-radio behavior, so this is not a
        # behavior change; it makes that reliance explicit instead of
        # accidental.
        self.radio = generic_csv.CSVRadio(None)
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
        # Explicitly destroy the wizard rather than relying on
        # frame.Destroy() to cascade to it -- wx.adv.Wizard is a
        # top-level window in its own right (passing frame as
        # "parent" only sets ownership for modal/z-order purposes).
        # wx.Window.Destroy() defers the actual C++-level deletion to
        # the next idle/event-loop pass rather than freeing it
        # immediately, and nothing here ever runs an event loop
        # between tests -- so without wx.Yield() below, an
        # un-destroyed-but-not-yet-actually-freed wizard's
        # wx.ID_FORWARD button (a wx *stock* ID, shared by every
        # wizard instance) can still be found by a LATER test's
        # FindWindowById(wx.ID_FORWARD) instead of that test's own
        # fresh one -- confirmed empirically (a trivial two-wizards-
        # in-a-row repro shows the second FindWindowById() returning
        # the FIRST wizard's button, whose GetTopLevelParent() isn't
        # even the second wizard) and confirmed to cause exactly this
        # failure mode when the whole suite runs together, despite
        # passing every time in isolation, before this fix.
        self.wizard.Destroy()
        self.frame.Destroy()
        wx.Yield()


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
        _ensure_wx_app()
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
        _ensure_wx_app()
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

    def test_redo_restores_exact_post_apply_state(self):
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
        after_apply = {
            n: self.radio.get_memory(n).freq for n in applied_numbers}

        self.editor._undo(None)
        for n in applied_numbers:
            self.assertTrue(self.radio.get_memory(n).empty)

        self.editor._redo(None)
        for n in applied_numbers:
            mem = self.radio.get_memory(n)
            self.assertFalse(mem.empty)
            self.assertEqual(after_apply[n], mem.freq)

    def test_unrelated_edit_before_apply_is_not_touched_by_undo(self):
        # Undoing the Programming Assistant's transaction must not
        # affect an edit the user made before running it.
        lo, _hi = self.radio.get_features().memory_bounds
        manual_number = lo + 50
        manual_mem = chirp_common.Memory(number=manual_number, name='MANUAL')
        manual_mem.freq = 146900000
        with self.editor.undo_context('manual edit'):
            self.editor.set_memory(manual_mem)
        self.assertFalse(self.radio.get_memory(manual_number).empty)

        req = models.ProgrammingRequest(
            requested_services=(models.SERVICE_WEATHER,), channel_limit=20)
        plan = self.context.service.build_plan(req, network_allowed=False)
        self.context.service.convert_and_validate(plan)
        self.context.request = req
        self.context.plan = plan
        page = programming_assistant.ResultPage(self.context)
        page._apply()

        self.editor._undo(None)  # undoes only the assistant's own plan

        manual_after = self.radio.get_memory(manual_number)
        self.assertFalse(manual_after.empty)
        self.assertEqual(146900000, manual_after.freq)
        self.assertEqual('MANUAL', manual_after.name)

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

    def test_full_image_snapshot_only_included_rows_change(self):
        # Compare the COMPLETE memory state before/after, not just the
        # rows involved in the plan: an excluded row's target number
        # must be untouched, and every unrelated memory across the
        # whole numeric range must be bit-for-bit identical.
        lo, hi = self.radio.get_features().memory_bounds

        req = models.ProgrammingRequest(
            requested_services=(models.SERVICE_WEATHER,), channel_limit=20)
        plan = self.context.service.build_plan(req, network_allowed=False)
        self.context.service.convert_and_validate(plan)
        weather = [
            c for c in plan.all_candidates
            if c.service == models.SERVICE_WEATHER]
        self.assertGreaterEqual(len(weather), 2)
        excluded = weather[0]
        excluded.include = False
        excluded_number = excluded.memory_number
        included_numbers = {c.memory_number for c in weather if c.include}

        def _snapshot(mem):
            return (mem.empty, mem.freq, mem.name, mem.mode, mem.duplex,
                    mem.offset, mem.tmode, mem.rtone, mem.ctone, mem.dtcs)

        before = {n: _snapshot(self.radio.get_memory(n))
                  for n in range(lo, hi + 1)}

        self.context.request = req
        self.context.plan = plan
        page = programming_assistant.ResultPage(self.context)
        page._apply()

        after = {n: _snapshot(self.radio.get_memory(n))
                 for n in range(lo, hi + 1)}

        # The excluded row's own slot must be untouched.
        self.assertEqual(before[excluded_number], after[excluded_number])

        for n in range(lo, hi + 1):
            if n in included_numbers:
                self.assertNotEqual(
                    before[n], after[n],
                    'memory %i was included but did not change' % n)
            else:
                self.assertEqual(
                    before[n], after[n],
                    'memory %i changed but was not part of the plan' % n)

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


class DescribePageServiceValidationTest(ProgrammingAssistantWxTestBase):
    """Regression coverage for a Windows validation report:
    DescribePage._validate_next() depends entirely on
    self.services.GetCheckedItems(), but self.services had no event
    binding at all -- toggling a checkbox via a real user click never
    re-evaluated the wizard's Next button, which stayed stuck disabled
    from when the page was first shown (nothing checked yet yet), no
    matter what the user subsequently checked or how many other
    fields were correctly filled in.

    Confirmed empirically that wx.CheckListBox.Check() alone does NOT
    fire EVT_CHECKLISTBOX (only a genuine UI toggle, or an explicitly
    constructed and dispatched one, does) -- a test that only called
    .Check() would not have caught this bug, which is exactly why the
    original RealWizardEventFlowTest (which calls .Check() directly)
    missed it. These tests fire a real EVT_CHECKLISTBOX via
    ProcessEvent() instead, against a real wx.adv.Wizard using the
    production event wiring, and check the actual wx.ID_FORWARD
    button's real IsEnabled() state -- not just _validate_next()'s
    return value -- since the bug was specifically that the button
    itself never got re-Enable()'d.
    """

    def _setup_describe_page(self):
        # Reuse self.wizard/self.context from setUp() rather than
        # constructing a second, separate wizard: with two wizard
        # instances simultaneously alive, FindWindowById(wx.ID_FORWARD)
        # -- a wx *stock* ID, shared by every wizard's Next button --
        # does not reliably scope to the calling page's own wizard in
        # this environment and can return the OTHER wizard's button
        # instead (confirmed empirically: btn.GetTopLevelParent() is
        # not even the wizard that owns the page that found it). Since
        # every page in a test only ever needs one live wizard at a
        # time, avoiding a redundant second one sidesteps the problem
        # entirely rather than fighting wx's window-lookup internals.
        wizard = self.wizard
        programming_assistant._wire_wizard_events(wizard)
        describe = self.context.get_page(
            'describe', programming_assistant.DescribePage)
        wizard.GetPageAreaSizer().Add(describe)
        wizard.ShowPage(describe)
        return wizard, describe

    def _check_service(self, describe, index, checked):
        describe.services.Check(index, checked)
        evt = wx.CommandEvent(wx.EVT_CHECKLISTBOX.typeId,
                              describe.services.GetId())
        evt.SetInt(index)
        describe.services.GetEventHandler().ProcessEvent(evt)

    def _service_index(self, service):
        return [
            i for i, (value, _label) in
            enumerate(programming_assistant._SERVICE_LABELS)
            if value == service][0]

    def test_next_disabled_with_nothing_checked(self):
        _wizard, describe = self._setup_describe_page()
        forward = describe.FindWindowById(wx.ID_FORWARD)
        self.assertFalse(forward.IsEnabled())
        self.assertTrue(describe.services_status.GetLabel())

    def test_checking_a_service_via_real_event_enables_next(self):
        _wizard, describe = self._setup_describe_page()
        forward = describe.FindWindowById(wx.ID_FORWARD)
        self.assertFalse(forward.IsEnabled())

        self._check_service(describe, self._service_index(
            models.SERVICE_HAM), True)

        self.assertTrue(forward.IsEnabled())
        self.assertEqual('', describe.services_status.GetLabel())

    def test_invalid_to_valid_to_invalid_cycle(self):
        _wizard, describe = self._setup_describe_page()
        forward = describe.FindWindowById(wx.ID_FORWARD)
        ham = self._service_index(models.SERVICE_HAM)
        weather = self._service_index(models.SERVICE_WEATHER)

        self.assertFalse(forward.IsEnabled())

        self._check_service(describe, ham, True)
        self.assertTrue(forward.IsEnabled())

        self._check_service(describe, ham, False)
        self.assertFalse(forward.IsEnabled())
        self.assertTrue(describe.services_status.GetLabel())

        self._check_service(describe, weather, True)
        self.assertTrue(forward.IsEnabled())
        self.assertEqual('', describe.services_status.GetLabel())

    def test_ai_populated_services_also_enable_next(self):
        # _apply_request_to_fields() checks services programmatically
        # (as if the AI interpreter populated them), which also
        # doesn't fire EVT_CHECKLISTBOX -- must be refreshed
        # explicitly rather than relying on the (nonexistent) event.
        _wizard, describe = self._setup_describe_page()
        forward = describe.FindWindowById(wx.ID_FORWARD)
        self.assertFalse(forward.IsEnabled())

        req = models.ProgrammingRequest(
            requested_services=(models.SERVICE_HAM,))
        describe._apply_request_to_fields(req)

        self.assertTrue(forward.IsEnabled())

    def test_reproduces_exact_windows_report_form(self):
        # The precise field values from the Windows validation report
        # that could never advance past Describe.
        wizard, describe = self._setup_describe_page()

        describe.text.SetValue(
            "I use my Yaesu FT-60 amateur radio in the Coeur d'Alene "
            "area for listening to local repeater")
        describe.location.SetValue('83815')
        describe.radius.SetValue(50)
        describe.license_choice.SetSelection([
            i for i, (v, _l) in
            enumerate(programming_assistant._LICENSE_LABELS)
            if v == models.LICENSE_TECHNICIAN][0])
        describe.gmrs_chk.SetValue(True)
        describe.activities.SetValue('Local Repeaters')
        for service in (models.SERVICE_HAM, models.SERVICE_GMRS,
                        models.SERVICE_FRS, models.SERVICE_MURS,
                        models.SERVICE_WEATHER, models.SERVICE_AVIATION):
            self._check_service(describe, self._service_index(service),
                                True)
        describe.channel_limit.SetValue(100)
        describe.naming_choice.SetSelection([
            i for i, (v, _l) in
            enumerate(programming_assistant._NAMING_LABELS)
            if v == models.NAMING_SHORT][0])
        describe.preserve_existing.SetValue(True)
        describe.allow_replace.SetValue(False)
        describe.use_range.SetValue(False)
        describe.protected.SetValue('')

        forward = describe.FindWindowById(wx.ID_FORWARD)
        self.assertTrue(
            forward.IsEnabled(),
            'Next stayed disabled with a fully valid, populated form '
            '-- reproduces the Windows validation report exactly')

        next_page = describe.GetNext()
        ok = wizard.ShowPage(next_page, True)
        self.assertTrue(ok, 'wizard refused to advance past Describe')
        self.assertIsInstance(next_page, programming_assistant.ConfirmPage)


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
        # Reuse self.wizard/self.context from setUp() -- see the
        # comment on DescribePageServiceValidationTest._setup_describe_
        # page() for why a second, separate wizard instance is best
        # avoided here (FindWindowById(wx.ID_FORWARD) does not
        # reliably scope to the correct wizard when more than one is
        # simultaneously alive).
        wizard = self.wizard
        context = self.context
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

        # A single click starts the build and -- once it succeeds --
        # the page advances to Review automatically; no second click
        # is required.
        review = self._build_and_advance_to_review(wizard, confirm)
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

    def _drive_to_confirm(self, service=models.SERVICE_WEATHER):
        wizard = self.wizard
        context = self.context
        programming_assistant._wire_wizard_events(wizard)
        describe = context.get_page(
            'describe', programming_assistant.DescribePage)
        wizard.GetPageAreaSizer().Add(describe)
        wizard.ShowPage(describe)
        describe.services.Check(
            [i for i, (value, _label) in
             enumerate(programming_assistant._SERVICE_LABELS)
             if value == service][0], True)
        confirm = self._click_next(wizard, describe)
        confirm.network_allowed.SetValue(False)
        return wizard, context, describe, confirm

    def _build_and_advance_to_review(self, wizard, confirm):
        # The background build thread is replaced with one that runs
        # synchronously (deterministic), but wx.PostEvent()'s hop back
        # to the main thread is queued and drained only *after* the
        # triggering ShowPage() call returns, mirroring real timing:
        # in production, PostEvent() queues onto the wx event loop for
        # an independent, later dispatch -- it does not call the
        # handler inline from within the original transition. Calling
        # _build_done() (and therefore its auto-advance to Review)
        # from *inside* the same ShowPage() call that triggered the
        # build is a test-only artifact that cannot happen in
        # production and confuses wx.adv.Wizard's own return-value
        # bookkeeping for that call (observed: the outer ShowPage()
        # reports failure even though the nested call it triggered
        # did move the wizard forward).
        posted = []
        with mock.patch(
                'chirp.wxui.programming_assistant.wx.PostEvent',
                side_effect=lambda t, e: posted.append((t, e))), \
                mock.patch(
                    'chirp.wxui.programming_assistant.threading.Thread',
                    ConfirmPageBuildFreshnessTest._ImmediateThread):
            wizard.ShowPage(confirm.GetNext(), True)
        self.assertEqual(1, len(posted), 'expected exactly one build '
                         'completion event to be posted')
        target, evt = posted[0]
        target._build_done(evt)
        review = wizard.GetCurrentPage()
        self.assertIsInstance(review, programming_assistant.ReviewPage)
        return review

    def test_confirm_populated_immediately_no_extra_click_required(self):
        # Windows validation report: the Confirm summary was blank on
        # arrival and only populated as a side effect of a first,
        # silently-vetoed Next click -- the user had to click twice
        # to advance, with no indication why the first click "did
        # nothing" visible.
        wizard, _context, describe, confirm = self._drive_to_confirm()
        self.assertIn('Requested services: %s' % models.SERVICE_WEATHER,
                      confirm.summary.GetValue())

    def test_confirm_to_review_single_click_auto_advances_on_success(
            self):
        # Windows validation report: the first Next click on Confirm
        # silently started the build and stayed put, with nothing on
        # screen indicating why -- the user had to notice the status
        # text changed and click Next a second time. Preferred fix:
        # one click starts the build, and once it succeeds the wizard
        # advances to Review on its own.
        wizard, _context, _describe, confirm = self._drive_to_confirm()
        review = self._build_and_advance_to_review(wizard, confirm)
        self.assertIsInstance(review, programming_assistant.ReviewPage)

    def test_confirm_duplicate_next_events_do_not_start_duplicate_builds(
            self):
        # A build already in flight must veto (not restart) a second
        # Next event that arrives before it completes -- e.g. a
        # double-click or a duplicate/queued wx event.
        wizard, _context, _describe, confirm = self._drive_to_confirm()

        # A controllable stand-in for threading.Thread that does NOT
        # run its target on start() -- this lets the test simulate a
        # second Next event arriving while the first build is still
        # "in flight" (self._build_thread is not None).
        class _HeldThread:
            def __init__(self, target=None, args=()):
                self._target = target
                self._args = args

            def start(self):
                pass

            def join(self, timeout=None):
                pass

        start_build_calls = []
        real_start_build = confirm._start_build

        def counting_start_build():
            start_build_calls.append(1)
            return real_start_build()

        with mock.patch.object(
                confirm, '_start_build',
                side_effect=counting_start_build), \
                mock.patch(
                    'chirp.wxui.programming_assistant.threading.Thread',
                    _HeldThread):
            first_event = _FakeWizardEvent()
            confirm.validate_success(first_event)
            self.assertTrue(first_event.vetoed)
            self.assertEqual(1, len(start_build_calls))
            held_thread = confirm._build_thread
            self.assertIsInstance(held_thread, _HeldThread)

            # Second Next event while the first build is still in
            # flight -- must veto without starting another build.
            second_event = _FakeWizardEvent()
            confirm.validate_success(second_event)
            self.assertTrue(second_event.vetoed)
            self.assertEqual(
                1, len(start_build_calls),
                'a duplicate Next event started a second build')
            self.assertIs(
                held_thread, confirm._build_thread,
                'a duplicate Next event replaced the in-flight build')

    def test_confirm_navigation_disabled_while_building(self):
        # While a build is in flight, both Next and Back must be
        # disabled -- Next because there's nothing to advance to yet,
        # Back because leaving would let _build_done()'s auto-advance
        # (once the build finishes) try to move a page the user is no
        # longer on.
        wizard, _context, _describe, confirm = self._drive_to_confirm()

        class _HeldThread:
            def __init__(self, target=None, args=()):
                self._target = target
                self._args = args

            def start(self):
                pass  # never runs -- build stays "in flight" forever

            def join(self, timeout=None):
                pass

        with mock.patch(
                'chirp.wxui.programming_assistant.threading.Thread',
                _HeldThread):
            wizard.ShowPage(confirm.GetNext(), True)

        forward = confirm.FindWindowById(wx.ID_FORWARD)
        back = confirm.FindWindowById(wx.ID_BACKWARD)
        self.assertIn('Building', confirm.status.GetLabel())
        self.assertFalse(
            forward.IsEnabled(),
            'Next must stay disabled while a build is in flight')
        self.assertFalse(
            back.IsEnabled(),
            'Back must be disabled while a build is in flight')

    def test_confirm_build_failure_via_real_wizard_stays_and_retries(self):
        # The failure path, driven through the real wizard rather than
        # calling validate_success() directly: a failed build must not
        # advance, must show a clear error, and must allow a retry
        # that actually attempts another build.
        wizard, context, _describe, confirm = self._drive_to_confirm()
        with mock.patch(
                'chirp.wxui.programming_assistant.wx.PostEvent',
                side_effect=lambda t, e: t._build_done(e)), \
                mock.patch(
                    'chirp.wxui.programming_assistant.threading.Thread',
                    ConfirmPageBuildFreshnessTest._ImmediateThread), \
                mock.patch.object(
                    context.service, 'build_plan',
                    side_effect=RuntimeError('simulated build failure')):
            still_confirm = self._click_next_or_veto(wizard, confirm)
        self.assertIs(
            confirm, still_confirm,
            'a failed build must not advance to Review')
        self.assertIn('Error', confirm.status.GetLabel())
        self.assertIsNone(context.plan)
        forward = confirm.FindWindowById(wx.ID_FORWARD)
        self.assertTrue(
            forward.IsEnabled(),
            'Next must be re-enabled after a failed build so the '
            'user can retry')

        # Retry, now succeeding.
        review = self._build_and_advance_to_review(wizard, confirm)
        self.assertIsInstance(review, programming_assistant.ReviewPage)

    def test_review_populated_immediately_on_arrival(self):
        wizard, _context, _describe, confirm = self._drive_to_confirm()
        review = self._build_and_advance_to_review(wizard, confirm)
        self.assertEqual(7, review.list.GetItemCount())
        self.assertEqual(7, len(review._row_candidates))

    def test_result_populated_immediately_apply_occurs_once(self):
        wizard, context, _describe, confirm = self._drive_to_confirm()
        review = self._build_and_advance_to_review(wizard, confirm)
        result = self._click_next(wizard, review)

        self.assertIsInstance(result, programming_assistant.ResultPage)
        self.assertTrue(result._applied)
        self.assertIn('Applied: 7', result.result.GetValue())
        applied_numbers = [
            c.memory_number for c in context.plan.all_candidates
            if c.include]
        for n in applied_numbers:
            self.assertFalse(self.radio.get_memory(n).empty)

    def test_finish_enabled_and_back_disabled_on_result(self):
        # Windows validation report: Finish was unavailable, and Back
        # closed the wizard entirely instead of being disabled.
        wizard, _context, _describe, confirm = self._drive_to_confirm()
        review = self._build_and_advance_to_review(wizard, confirm)
        result = self._click_next(wizard, review)

        finish = result.FindWindowById(wx.ID_FORWARD)
        back = result.FindWindowById(wx.ID_BACKWARD)
        self.assertEqual('&Finish', finish.GetLabel())
        self.assertTrue(
            finish.IsEnabled(),
            'Finish must be enabled once Apply has completed')
        self.assertFalse(
            back.IsEnabled(),
            'Back must be disabled on Result -- GetPrev() is None and '
            'there is no safe way back after Apply already ran')

    def test_describe_back_also_disabled(self):
        # Same underlying fix (AssistantPage.validate_next() now
        # manages the Back button, not just Forward) -- Describe has
        # no previous page either. Checked while Describe is still the
        # CURRENT page: the Back button is one shared wizard control,
        # so checking it after already advancing to Confirm (which
        # legitimately has a previous page) would just observe
        # Confirm's state instead.
        wizard = self.wizard
        context = self.context
        programming_assistant._wire_wizard_events(wizard)
        describe = context.get_page(
            'describe', programming_assistant.DescribePage)
        wizard.GetPageAreaSizer().Add(describe)
        wizard.ShowPage(describe)

        back = describe.FindWindowById(wx.ID_BACKWARD)
        self.assertFalse(back.IsEnabled())

    def test_page_shown_apply_is_idempotent_across_repeated_calls(self):
        # Duplicate-event protection: nothing in the real wizard should
        # ever call page_shown() twice for the same visit to Result,
        # but if it did (or some other navigation path re-triggered
        # it), Apply must not run twice.
        wizard, _context, _describe, confirm = self._drive_to_confirm()
        review = self._build_and_advance_to_review(wizard, confirm)
        result = self._click_next(wizard, review)
        self.assertTrue(result._applied)

        applied_calls = []
        real_apply = result._apply

        def counting_apply():
            applied_calls.append(1)
            return real_apply()
        result._apply = counting_apply
        result.page_shown()
        result.page_shown()
        self.assertEqual(0, len(applied_calls))

    def test_back_from_confirm_to_describe_then_forward_updates_confirm(
            self):
        wizard, context, describe, confirm = self._drive_to_confirm(
            service=models.SERVICE_HAM)
        self.assertIn('ham', confirm.summary.GetValue())

        # Real Back navigation, not a direct method call.
        back_to_describe = wizard.ShowPage(describe, False)
        self.assertTrue(back_to_describe)

        describe.services.Check(
            [i for i, (value, _label) in
             enumerate(programming_assistant._SERVICE_LABELS)
             if value == models.SERVICE_WEATHER][0], True)
        describe.services.Check(
            [i for i, (value, _label) in
             enumerate(programming_assistant._SERVICE_LABELS)
             if value == models.SERVICE_HAM][0], False)

        confirm_again = self._click_next(wizard, describe)
        self.assertIs(confirm, confirm_again)
        self.assertIn('weather', confirm_again.summary.GetValue())
        self.assertNotIn('ham', confirm_again.summary.GetValue())

    @staticmethod
    def _full_snapshot(mem):
        return (mem.empty, mem.freq, mem.name, mem.mode, mem.duplex,
                mem.offset, mem.tmode, mem.rtone, mem.ctone, mem.dtcs)

    def test_full_transaction_snapshot_finish_then_undo_restores_exactly(
            self):
        # Phase 2 of the round-4 Windows validation request: one full
        # wizard run through Result/Finish must be exactly one Undo
        # transaction, and undoing it must restore the COMPLETE
        # editable memory state -- not just the frequencies of the
        # rows the plan touched -- bit for bit, with nothing left
        # over and no second Undo needed. Also verifies Redo restores
        # the exact post-Apply state, via this same real-wizard Finish
        # path (existing Redo coverage in ResultPageApplyTest drives
        # ResultPage._apply() directly, not the full wizard flow).
        lo, hi = self.radio.get_features().memory_bounds
        before = {n: self._full_snapshot(self.radio.get_memory(n))
                  for n in range(lo, hi + 1)}
        undo_queue_len_before = len(self.editor._undo_queue)

        wizard, context, _describe, confirm = self._drive_to_confirm()
        review = self._build_and_advance_to_review(wizard, confirm)
        result = self._click_next(wizard, review)
        self.assertTrue(result._applied)

        after_apply = {n: self._full_snapshot(self.radio.get_memory(n))
                       for n in range(lo, hi + 1)}
        self.assertNotEqual(before, after_apply,
                            'nothing changed -- Apply did not run')
        # Exactly one new transaction was pushed by this one wizard
        # run -- not zero (Apply silently failing) and not more than
        # one (a partial/split transaction that would need more than
        # one Undo to fully unwind).
        self.assertEqual(undo_queue_len_before + 1,
                         len(self.editor._undo_queue))

        self.editor._undo(None)
        after_undo = {n: self._full_snapshot(self.radio.get_memory(n))
                      for n in range(lo, hi + 1)}
        # The complete memory state -- every field, every memory
        # number in range, including ones the plan never touched --
        # matches the pre-Apply snapshot exactly after a single Undo.
        self.assertEqual(before, after_undo,
                         'one Undo did not restore the exact pre-Apply '
                         'state -- partial changes remain')
        self.assertEqual(
            undo_queue_len_before, len(self.editor._undo_queue),
            'the one Undo call did not fully drain this transaction')

        # Redo, via the same real-wizard-driven transaction, restores
        # the exact post-Apply state -- CHIRP's existing Redo
        # mechanism (_redo/_redo_queue), not a new one.
        self.editor._redo(None)
        after_redo = {n: self._full_snapshot(self.radio.get_memory(n))
                      for n in range(lo, hi + 1)}
        self.assertEqual(after_apply, after_redo,
                         'one Redo did not restore the exact post-Apply '
                         'state produced by this wizard run')


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
