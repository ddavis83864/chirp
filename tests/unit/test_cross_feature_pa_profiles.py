"""Cross-feature integration coverage for the combined Programming
Assistant + Radio Profile Foundation integration branch (section 10
of the integration task this module was written for).

Each feature line already has its own exhaustive, display-free test
suite (test_assistant_*.py / test_wxui_programming_assistant.py and
test_profiles_*.py / test_wxui_profiles.py). This module does not
repeat that coverage. It exists only to prove the two features do not
interfere with each other when exercised together against a single,
real chirp.wxui.main.ChirpMain -- the one object both features extend
independently. Like test_wxui_profiles.py, every test here needs a
real (or virtual) X display and is skipped cleanly, not failed, when
none is available.
"""

import os
import shutil
import tempfile
import unittest
from unittest import mock

from tests.unit import base  # noqa: F401 -- installs builtins._

from chirp import directory
from chirp.profiles import schema as profile_schema

_HAS_DISPLAY = bool(os.environ.get('DISPLAY'))

directory.import_drivers()

_SAMPLE_IMAGE = os.path.join(
    os.path.dirname(__file__), '..', 'images', 'Icom_IC-V80.img')


@unittest.skipUnless(_HAS_DISPLAY, 'requires a real or virtual X display')
class CrossFeatureTestCase(unittest.TestCase):
    """Mirrors test_wxui_profiles.py's ProfileGuiTestCase (see that
    file's own docstring for why the real wx imports are deferred to
    setUpClass, and why a stray sys.modules['wx'] mock from another
    test module makes this skip rather than fail)."""

    _app = None

    @classmethod
    def setUpClass(cls):
        import sys
        import unittest.mock as _mock
        if isinstance(sys.modules.get('wx'), _mock.Mock):
            raise unittest.SkipTest(
                'sys.modules["wx"] was replaced by a mock from another '
                'test module in this run; re-run this file alone to get '
                'real coverage')

        global wx, wxmain, profilecontroller, programming_assistant
        global chirp_common, config
        import wx
        from chirp import chirp_common as _chirp_common
        chirp_common = _chirp_common
        from chirp.wxui import main as wxmain
        from chirp.wxui import config as config
        from chirp.wxui import profilecontroller
        from chirp.wxui import programming_assistant

        app = wx.App()
        app._lc = wx.Locale(wx.LANGUAGE_ENGLISH)
        import builtins
        builtins._ = wx.GetTranslation
        cls._app = app

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmpdir, ignore_errors=True)
        # Isolated config storage (same pattern as
        # test_wxui_programming_assistant.py) so enabling the
        # assistant here never touches, or is affected by, a real
        # user's persisted CHIRP config.
        config._CONFIG = config.ChirpConfig(tempfile.mkdtemp())
        programming_assistant.set_assistant_enabled(True)
        self.frame = wxmain.ChirpMain(None, title='test')
        self.addCleanup(self.frame.Destroy)

    def _open_copy(self, name='test.img'):
        path = os.path.join(self.tmpdir, name)
        shutil.copy(_SAMPLE_IMAGE, path)
        self.frame.open_file(path)
        return self.frame.current_editorset


class MenuStructureTest(CrossFeatureTestCase):
    """Both menus must exist, be uniquely bound, and never collide --
    each feature line was developed independently against an older
    common ancestor of chirp/wxui/main.py, so this is the one file
    where the two branches could plausibly have clobbered each
    other's menu wiring during the merge."""

    def test_both_top_level_menus_present(self):
        menu_bar = self.frame.GetMenuBar()
        labels = [menu_bar.GetMenuLabelText(i)
                  for i in range(menu_bar.GetMenuCount())]
        self.assertIn('Profile', labels)
        radio_index = labels.index('Radio')
        radio_menu = menu_bar.GetMenu(radio_index)
        item_labels = [i.GetItemLabelText() for i in
                       radio_menu.GetMenuItems()]
        self.assertTrue(
            any('Programming Assistant' in label
                for label in item_labels),
            'Programming Assistant item missing from the Radio menu')

    def test_no_duplicate_menu_item_ids(self):
        menu_bar = self.frame.GetMenuBar()
        seen = {}
        dupes = []
        for i in range(menu_bar.GetMenuCount()):
            for item in menu_bar.GetMenu(i).GetMenuItems():
                item_id = item.GetId()
                if item_id in (wx.ID_SEPARATOR, wx.ID_ANY):
                    continue
                if item_id in seen:
                    dupes.append((seen[item_id], item.GetItemLabelText()))
                seen[item_id] = item.GetItemLabelText()
        self.assertEqual([], dupes,
                         'menu items unexpectedly share a wx id: %r' % dupes)

    def test_programming_assistant_and_profile_items_bind_independently(
            self):
        with mock.patch.object(
                programming_assistant, 'do_programming_assistant'
                ) as pa_handler, \
                mock.patch.object(
                    self.frame, '_menu_profile_create') as profile_handler:
            radio_menu = None
            menu_bar = self.frame.GetMenuBar()
            for i in range(menu_bar.GetMenuCount()):
                if menu_bar.GetMenuLabelText(i) == 'Radio':
                    radio_menu = menu_bar.GetMenu(i)
            pa_item = next(
                item for item in radio_menu.GetMenuItems()
                if 'Programming Assistant' in item.GetItemLabelText())
            self.frame.ProcessEvent(
                wx.CommandEvent(wx.EVT_MENU.typeId, pa_item.GetId()))
            pa_handler.assert_called_once()
            profile_handler.assert_not_called()


class ProfileMenuSurvivesAssistantLaunchTest(CrossFeatureTestCase):
    def test_profile_menu_functional_after_pa_creates_blank_document(self):
        from chirp.profiles import errors as profile_errors

        self.assertIsNone(self.frame.current_editorset)

        with mock.patch.object(wx.adv.Wizard, 'RunWizard',
                               return_value=True):
            programming_assistant.do_programming_assistant(
                self.frame, None)

        self.assertIsNotNone(self.frame.current_editorset)
        memedit_widget = profilecontroller.get_memedit(
            self.frame.current_editorset)
        self.assertIsNotNone(memedit_widget)

        # The blank document the assistant creates is a
        # generic_csv.CSVRadio(None) -- unbounded memory count by
        # design (a CSV can always grow). chirp.profiles' own
        # capability layer correctly refuses to enumerate an
        # infinite-capacity radio for extraction (see
        # profilecontroller.py / capabilities.has_infinite_number)
        # rather than silently extracting nothing or crashing. The
        # cross-feature guarantee this proves is narrower than "you
        # can make a profile from a brand new PA document" (that is
        # not a supported workflow, on either branch, independent of
        # this merge): it's that the Profile menu's own entry point
        # reaches that same, correct, pre-existing refusal -- not a
        # merge-introduced crash or a silent no-op -- when pointed at
        # a tab the assistant created.
        with self.assertRaises(profile_errors.CapabilityUnknownError):
            profilecontroller.create_profile_from_editorset(
                self.frame.current_editorset, name='From Blank Doc')


class ExtractFromAssistantPopulatedGridTest(CrossFeatureTestCase):
    def test_profile_extraction_sees_assistant_style_memory_writes(self):
        eset = self._open_copy()
        radio = eset.radio
        mem = chirp_common.Memory()
        mem.number = 5
        mem.freq = 146520000
        mem.name = 'SIMPX'
        mem.duplex = ''
        radio.set_memory(mem)

        result = profilecontroller.create_profile_from_editorset(
            eset, name='From Populated Grid')
        extracted_names = [c.name for c in result.profile.channels]
        self.assertIn('SIMPX', extracted_names)


class ApplyDoesNotDisturbUnrelatedMemoriesTest(CrossFeatureTestCase):
    def test_apply_leaves_untargeted_slots_alone(self):
        source_eset = self._open_copy('source.img')
        source_result = profilecontroller.create_profile_from_editorset(
            source_eset, name='Partial Apply')

        target_eset = self._open_copy('target.img')
        target_radio = target_eset.radio
        sentinel_number = 199
        sentinel = chirp_common.Memory()
        sentinel.number = sentinel_number
        sentinel.freq = 173000000  # in-band for this VHF-only radio
        sentinel.name = 'UNTCH'
        target_radio.set_memory(sentinel)

        change_set = profilecontroller.build_changeset_for_editorset(
            source_result.profile, target_eset)
        for item in change_set.items:
            if not item.blocked and (
                    item.target_memory_number == sentinel_number):
                # Should never happen (this small source image's
                # extracted profile places well below the top of the
                # target's memory range), but guard against ever
                # silently approving onto the sentinel slot.
                change_set.set_approval(item.logical_id,
                                        profile_schema.APPROVAL_REJECTED)
        for item in change_set.items:
            if not item.blocked and (
                    item.target_memory_number != sentinel_number):
                change_set.set_approval(item.logical_id,
                                        profile_schema.APPROVAL_APPROVED)

        memedit_widget = profilecontroller.get_memedit(target_eset)
        profilecontroller.apply_changeset(
            memedit_widget, source_result.profile.name, change_set)

        after = target_radio.get_memory(sentinel_number)
        self.assertEqual('UNTCH', after.name)
        self.assertEqual(173000000, after.freq)


class AssistantLaunchAfterProfileAppliedTest(CrossFeatureTestCase):
    def test_pa_reaches_wizard_on_an_image_a_profile_was_applied_to(self):
        source_eset = self._open_copy('source.img')
        source_result = profilecontroller.create_profile_from_editorset(
            source_eset, name='Pre-PA Apply')

        target_eset = self._open_copy('target.img')
        change_set = profilecontroller.build_changeset_for_editorset(
            source_result.profile, target_eset)
        for item in change_set.items:
            if not item.blocked:
                change_set.set_approval(item.logical_id,
                                        profile_schema.APPROVAL_APPROVED)
        memedit_widget = profilecontroller.get_memedit(target_eset)
        profilecontroller.apply_changeset(
            memedit_widget, source_result.profile.name, change_set)

        with mock.patch.object(wx.adv.Wizard, 'RunWizard',
                               return_value=True) as run:
            programming_assistant.do_programming_assistant(
                self.frame, None)
        run.assert_called_once()

        # The assistant must have resolved the same, already-populated
        # editor -- not created a new blank one on top of it.
        self.assertIs(
            memedit_widget,
            profilecontroller.get_memedit(self.frame.current_editorset))


class ClosingAssistantTabLeavesProfileStateAloneTest(CrossFeatureTestCase):
    def test_closing_pa_blank_tab_does_not_clear_open_profile(self):
        from chirp.profiles import model as profile_model
        held_profile = profile_model.Profile(name='Held Open')
        held_profile.add_channel(profile_model.ProfileChannel(
            logical_id='held-ch', name='Held',
            rx_freq_hz=146_500_000,
            transmit=profile_model.TransmitBehavior(
                mode=profile_schema.TRANSMIT_RECEIVE_ONLY)))
        self.frame._current_profile = held_profile
        self.frame._current_profile_path = None

        # No editorset open at all yet -- do_programming_assistant
        # must take the auto-blank-document path, not the
        # existing-editor path, for this test to exercise what it
        # claims to.
        self.assertIsNone(self.frame.current_editorset)
        with mock.patch.object(wx.adv.Wizard, 'RunWizard',
                               return_value=True):
            programming_assistant.do_programming_assistant(
                self.frame, None)
        new_tab = self.frame.current_editorset
        self.assertIsNotNone(new_tab)

        new_tab.close()
        self.frame._editors.DeletePage(self.frame._editors.GetSelection())

        self.assertIs(held_profile, self.frame._current_profile)


class LaunchGuardIndependentOfProfileEditorTest(CrossFeatureTestCase):
    def test_profile_editor_does_not_leak_into_pa_launch_guard(self):
        self.assertNotIn(id(self.frame),
                         programming_assistant._LAUNCH_IN_PROGRESS)

        eset = self._open_copy()
        result = profilecontroller.create_profile_from_editorset(eset)
        from chirp.wxui import profileeditor
        dlg = profileeditor.ProfileEditorDialog(self.frame, result.profile)
        self.addCleanup(dlg.Destroy)

        self.assertNotIn(id(self.frame),
                         programming_assistant._LAUNCH_IN_PROGRESS)

        with mock.patch.object(wx.adv.Wizard, 'RunWizard',
                               return_value=True):
            programming_assistant.do_programming_assistant(
                self.frame, None)

        self.assertNotIn(id(self.frame),
                         programming_assistant._LAUNCH_IN_PROGRESS)


class ProfileOperationsNeverTouchAIProviderTest(CrossFeatureTestCase):
    def test_profile_create_and_apply_never_call_the_ai_provider(self):
        with mock.patch(
                'chirp.assistant.providers.create_provider') as create:
            eset = self._open_copy()
            result = profilecontroller.create_profile_from_editorset(
                eset, name='No AI Involved')
            target_eset = self._open_copy('target.img')
            change_set = profilecontroller.build_changeset_for_editorset(
                result.profile, target_eset)
            for item in change_set.items:
                if not item.blocked:
                    change_set.set_approval(
                        item.logical_id, profile_schema.APPROVAL_APPROVED)
            memedit_widget = profilecontroller.get_memedit(target_eset)
            profilecontroller.apply_changeset(
                memedit_widget, result.profile.name, change_set)
        create.assert_not_called()


class ExplicitTransmitPermissionSurvivesExtractionTest(CrossFeatureTestCase):
    def test_transmit_enabled_offset_channel_extracts_unchanged(self):
        eset = self._open_copy()
        radio = eset.radio
        mem = chirp_common.Memory()
        mem.number = 10
        mem.freq = 146940000
        mem.name = 'RPTR'
        mem.duplex = '-'
        mem.offset = 600000
        radio.set_memory(mem)

        result = profilecontroller.create_profile_from_editorset(eset)
        chan = next(c for c in result.profile.channels
                    if c.name == 'RPTR')
        self.assertEqual(profile_schema.TRANSMIT_ENABLED,
                         chan.transmit.mode)
        self.assertEqual('-', chan.transmit.duplex)
        self.assertEqual(600000, chan.transmit.offset_hz)


class ReceiveOnlySafetyRoundTripTest(CrossFeatureTestCase):
    def test_receive_only_memory_never_becomes_transmit_enabled(self):
        source_eset = self._open_copy('source.img')
        radio = source_eset.radio
        mem = chirp_common.Memory()
        mem.number = 20
        mem.freq = 162550000
        mem.name = 'WX'
        mem.duplex = 'off'
        radio.set_memory(mem)

        result = profilecontroller.create_profile_from_editorset(
            source_eset, name='RX Only')
        chan = next(c for c in result.profile.channels
                    if c.name == 'WX')
        self.assertEqual(profile_schema.TRANSMIT_RECEIVE_ONLY,
                         chan.transmit.mode)
        self.assertTrue(chan.receive_only)

        target_eset, target_memedit = self._empty_target()
        change_set = profilecontroller.build_changeset_for_editorset(
            result.profile, target_eset)
        item = next(i for i in change_set.items
                    if i.logical_id == chan.logical_id)
        self.assertFalse(item.blocked)
        change_set.set_approval(item.logical_id,
                                profile_schema.APPROVAL_APPROVED)
        profilecontroller.apply_changeset(
            target_memedit, result.profile.name, change_set)

        applied = target_eset.radio.get_memory(item.target_memory_number)
        self.assertEqual('off', applied.duplex)

    def _empty_target(self):
        eset = self._open_copy('rx_target.img')
        memedit_widget = profilecontroller.get_memedit(eset)
        features = eset.radio.get_features()
        lo, hi = features.memory_bounds
        for n in range(lo, hi + 1):
            try:
                eset.radio.erase_memory(n)
            except Exception:
                pass
        memedit_widget.refresh()
        return eset, memedit_widget
