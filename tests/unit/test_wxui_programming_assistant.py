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

        class FakeEvent:
            def GetIndex(self):
                return 0
        page._on_check(FakeEvent())
        self.assertFalse(candidate.include)


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
