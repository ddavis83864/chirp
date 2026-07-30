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

from tests.unit import base  # noqa: F401 -- installs the gettext _

from chirp import directory
from chirp.profiles import schema as profile_schema

_HAS_DISPLAY = bool(os.environ.get('DISPLAY'))

directory.import_drivers()

_SAMPLE_IMAGE = os.path.join(
    os.path.dirname(__file__), '..', 'images', 'Icom_IC-V80.img')


def _mock_file_dialog(path=None, cancel=False):
    """Patch chirp.wxui.main.wx.FileDialog so a real Save/Open Profile
    menu handler can run in a test without a real native file dialog:
    ShowModal() reports Cancel (@cancel) or OK with @path as both
    GetPath() and (its containing directory as) GetDirectory().
    """
    import wx
    instance = mock.MagicMock()
    instance.__enter__.return_value = instance
    instance.ShowModal.return_value = (
        wx.ID_CANCEL if cancel else wx.ID_OK)
    if path is not None:
        instance.GetPath.return_value = path
        instance.GetDirectory.return_value = os.path.dirname(path)
    return mock.patch('chirp.wxui.main.wx.FileDialog',
                      return_value=instance)


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
        base.builtins._ = wx.GetTranslation
        cls._app = app

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmpdir, ignore_errors=True)
        # Isolated config storage (same pattern as
        # test_wxui_programming_assistant.py) so enabling the
        # assistant here never touches, or is affected by, a real
        # user's persisted CHIRP config.
        config._CONFIG = config.ChirpConfig(tempfile.mkdtemp())
        # programming_assistant.CONF is a ChirpConfigProxy captured
        # once, at that module's own first import, bound to whatever
        # config._CONFIG was at that moment -- reassigning
        # config._CONFIG here (above) does not retarget it. So
        # set_assistant_enabled(True) below writes through to the
        # same config store for the rest of this process's lifetime
        # regardless of this test's own isolation, and must be
        # restored explicitly, or it leaks into any later test in the
        # same run that checks assistant_enabled().
        programming_assistant.set_assistant_enabled(True)
        self.addCleanup(programming_assistant.set_assistant_enabled, False)
        self.frame = wxmain.ChirpMain(None, title='test')
        self.addCleanup(self.frame.Destroy)

    def _open_copy(self, name='test.img'):
        path = os.path.join(self.tmpdir, name)
        shutil.copy(_SAMPLE_IMAGE, path)
        self.frame.open_file(path)
        return self.frame.current_editorset

    def _blank_csv_editorset(self):
        """The exact document Programming Assistant's automatic
        blank-document workflow creates (see
        chirp.wxui.programming_assistant._ensure_blank_memory_document):
        the same chirpmain.open_file('Untitled.csv', exists=False)
        call Radio > New uses."""
        self.frame.open_file('Untitled.csv', exists=False)
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
        # generic_csv.CSVRadio(None) -- has_infinite_number=True (no
        # fixed ceiling on how large it may grow), but its current
        # memory_bounds is always a real, concrete, enumerable range
        # (see chirp.profiles.extraction.enumerate_source_memories()).
        # generic_csv.CSVRadio(None) is not fully empty either --
        # _blank(setDefault=True) pre-populates memory 0 with a
        # default 146.010 MHz entry -- so extraction from a freshly
        # created blank document succeeds with exactly that one
        # channel, not a CapabilityUnknownError and not zero channels.
        result = profilecontroller.create_profile_from_editorset(
            self.frame.current_editorset, name='From Blank Doc')
        self.assertEqual(1, result.summary.channels_extracted)
        self.assertEqual(146010000, result.profile.channels[0].rx_freq_hz)


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


class RealPathProfileWorkflowTest(CrossFeatureTestCase):
    """Exercises the real Profile menu handlers end to end (section 8
    of the dynamic-memory-extraction corrective task): the exact
    document Programming Assistant's automatic blank-document workflow
    creates, the exact memory-write path its own apply step uses, and
    the actual ChirpMain._menu_profile_create/_save/_save_as/_open/
    _apply handlers -- not only the lower-level
    chirp.wxui.profilecontroller functions those handlers call, which
    is what every other test in this module (and the prior, incorrect
    assertion this corrective phase replaced -- see
    ProfileMenuSurvivesAssistantLaunchTest above) exercised instead.
    This is the level Windows testing actually exercises, and where
    the save/open discoverability gap was found.
    """

    def _populate_via_pa_write_path(self, eset, number, freq, name,
                                    duplex=''):
        """The exact write path Programming Assistant's own apply
        step uses (see programming_assistant.ResultPage._apply():
        one undo_context() wrapping memedit_editor.set_memory(memory)
        calls) -- not radio.set_memory() directly."""
        memedit_widget = profilecontroller.get_memedit(eset)
        mem = chirp_common.Memory()
        mem.number = number
        mem.freq = freq
        mem.name = name
        mem.duplex = duplex
        with memedit_widget.undo_context('Test Populate'):
            memedit_widget.set_memory(mem)
        return memedit_widget

    def test_create_populated_dynamic_grid_reaches_editor_and_saves(self):
        eset = self._blank_csv_editorset()
        self._populate_via_pa_write_path(eset, 5, 146520000, 'REAL')
        save_path = os.path.join(
            self.tmpdir, 'roundtrip' + profile_schema.FILE_EXTENSION)

        with mock.patch.object(wxmain.wx, 'TextEntryDialog') as name_dlg, \
                mock.patch.object(wxmain.wx, 'MessageBox') as msgbox, \
                mock.patch.object(
                    wxmain.wx, 'MessageDialog') as save_prompt, \
                mock.patch.object(
                    wxmain.profileeditor, 'ProfileEditorDialog'
                    ) as editor_dlg, \
                _mock_file_dialog(save_path), \
                mock.patch(
                    'chirp.wxui.common.error_proof.show_error'
                    ) as show_error:
            name_dlg.return_value.ShowModal.return_value = wx.ID_OK
            name_dlg.return_value.GetValue.return_value = 'Round Trip'
            save_prompt.return_value.ShowModal.return_value = wx.ID_YES
            editor_dlg.return_value.ShowModal.return_value = wx.ID_OK

            self.frame._menu_profile_create(None)

        # No fixed-memory-count / capability error -- the whole point
        # of this corrective phase.
        show_error.assert_not_called()

        self.assertTrue(os.path.exists(save_path))
        self.assertEqual(save_path, self.frame._current_profile_path)

        saved_confirmation = [
            c for c in msgbox.call_args_list if 'Profile Saved' in str(c)]
        self.assertTrue(
            saved_confirmation,
            'no path-visible confirmation was shown after save')
        self.assertIn(save_path, str(saved_confirmation[0]))

        from chirp.profiles import serialization as profile_serialization
        reloaded = profile_serialization.load(save_path)
        self.assertEqual('REAL', reloaded.channels[-1].name)

    def test_reopen_through_real_menu_preserves_content(self):
        from chirp.profiles import model as profile_model
        from chirp.profiles import serialization as profile_serialization

        profile = profile_model.Profile(name='Preload')
        profile.add_channel(profile_model.ProfileChannel(
            logical_id='preload-ch', name='PRE',
            rx_freq_hz=146_500_000,
            transmit=profile_model.TransmitBehavior(
                mode=profile_schema.TRANSMIT_ENABLED,
                duplex=profile_schema.DUPLEX_NONE)))
        path = os.path.join(
            self.tmpdir, 'preload' + profile_schema.FILE_EXTENSION)
        profile_serialization.save(profile, path)

        with _mock_file_dialog(path), \
                mock.patch.object(
                    wxmain.profileeditor, 'ProfileEditorDialog'
                    ) as editor_dlg:
            editor_dlg.return_value.ShowModal.return_value = wx.ID_OK
            self.frame._menu_profile_open(None)

        # Defect 2 (Windows validation): Open Profile must produce a
        # visible result, not just update internal state.
        editor_dlg.assert_called_once()
        _call_args, call_kwargs = editor_dlg.call_args
        self.assertEqual(path, call_kwargs.get('path'))
        editor_dlg.return_value.ShowModal.assert_called_once()

        self.assertEqual(path, self.frame._current_profile_path)
        self.assertEqual(profile.profile_id,
                         self.frame._current_profile.profile_id)
        self.assertEqual(
            ['PRE'], [c.name for c in self.frame._current_profile.channels])

    def test_cancel_save_as_performs_no_write_and_raises_no_error(self):
        from chirp.profiles import model as profile_model
        self.frame._current_profile = profile_model.Profile(name='Unsaved')
        self.frame._current_profile_path = None

        with _mock_file_dialog(cancel=True), \
                mock.patch(
                    'chirp.wxui.common.error_proof.show_error'
                    ) as show_error:
            self.frame._menu_profile_save_as(None)

        show_error.assert_not_called()
        self.assertIsNone(self.frame._current_profile_path)
        self.assertEqual(
            [], [f for f in os.listdir(self.tmpdir)
                 if f.endswith(profile_schema.FILE_EXTENSION)])

    def test_cancel_open_produces_no_editor_and_no_error(self):
        with _mock_file_dialog(cancel=True), \
                mock.patch.object(
                    wxmain.profileeditor, 'ProfileEditorDialog'
                    ) as editor_dlg, \
                mock.patch(
                    'chirp.wxui.common.error_proof.show_error'
                    ) as show_error:
            self.frame._menu_profile_open(None)

        editor_dlg.assert_not_called()
        show_error.assert_not_called()
        self.assertIsNone(self.frame._current_profile)
        self.assertIsNone(self.frame._current_profile_path)

    def test_open_malformed_json_shows_actionable_error_no_editor(self):
        bad_path = os.path.join(
            self.tmpdir, 'bad' + profile_schema.FILE_EXTENSION)
        with open(bad_path, 'w') as f:
            f.write('{not valid json')

        with _mock_file_dialog(bad_path), \
                mock.patch.object(
                    wxmain.profileeditor, 'ProfileEditorDialog'
                    ) as editor_dlg, \
                mock.patch(
                    'chirp.wxui.common.error_proof.show_error'
                    ) as show_error:
            self.frame._menu_profile_open(None)

        editor_dlg.assert_not_called()
        show_error.assert_called_once()
        from chirp.profiles import errors as profile_errors
        self.assertIsInstance(show_error.call_args[0][0],
                              profile_errors.ProfileParseError)
        self.assertIsNone(self.frame._current_profile)

    def test_open_missing_file_shows_actionable_error_no_editor(self):
        missing_path = os.path.join(
            self.tmpdir, 'does-not-exist' + profile_schema.FILE_EXTENSION)

        with _mock_file_dialog(missing_path), \
                mock.patch.object(
                    wxmain.profileeditor, 'ProfileEditorDialog'
                    ) as editor_dlg, \
                mock.patch(
                    'chirp.wxui.common.error_proof.show_error'
                    ) as show_error:
            self.frame._menu_profile_open(None)

        editor_dlg.assert_not_called()
        show_error.assert_called_once()
        from chirp.profiles import errors as profile_errors
        self.assertIsInstance(show_error.call_args[0][0],
                              profile_errors.ProfileIOError)
        self.assertIsNone(self.frame._current_profile)

    def test_open_succeeds_with_no_memory_grid_open(self):
        from chirp.profiles import model as profile_model
        from chirp.profiles import serialization as profile_serialization

        self.assertIsNone(self.frame.current_editorset)
        profile = profile_model.Profile(name='NoGrid')
        path = os.path.join(
            self.tmpdir, 'nogrid' + profile_schema.FILE_EXTENSION)
        profile_serialization.save(profile, path)

        with _mock_file_dialog(path), \
                mock.patch.object(
                    wxmain.profileeditor, 'ProfileEditorDialog'
                    ) as editor_dlg, \
                mock.patch(
                    'chirp.wxui.common.error_proof.show_error'
                    ) as show_error:
            editor_dlg.return_value.ShowModal.return_value = wx.ID_OK
            self.frame._menu_profile_open(None)

        show_error.assert_not_called()
        editor_dlg.assert_called_once()
        self.assertEqual('NoGrid', self.frame._current_profile.name)

    def test_entirely_blank_dynamic_grid_shows_actionable_message(self):
        eset = self._blank_csv_editorset()
        memedit_widget = profilecontroller.get_memedit(eset)
        features = eset.radio.get_features()
        lo, hi = features.memory_bounds
        for n in range(lo, hi + 1):
            try:
                eset.radio.erase_memory(n)
            except Exception:
                pass
        memedit_widget.refresh()

        from chirp.profiles import errors as profile_errors

        with mock.patch.object(wxmain.wx, 'TextEntryDialog') as name_dlg, \
                mock.patch.object(
                    wxmain.profileeditor, 'ProfileEditorDialog'
                    ) as editor_dlg, \
                mock.patch(
                    'chirp.wxui.common.error_proof.show_error'
                    ) as show_error:
            name_dlg.return_value.ShowModal.return_value = wx.ID_OK
            name_dlg.return_value.GetValue.return_value = 'Empty'

            self.frame._menu_profile_create(None)

        editor_dlg.assert_not_called()
        show_error.assert_called_once()
        shown_error = show_error.call_args[0][0]
        self.assertIsInstance(shown_error,
                              profile_errors.NoPopulatedMemoriesError)
        self.assertIn('No populated memories', str(shown_error))
        # The old, no-longer-applicable message is gone.
        self.assertNotIn('fixed memory count', str(shown_error))

    def test_apply_through_real_menu_handler_writes_intended_memories(self):
        eset = self._blank_csv_editorset()
        self._populate_via_pa_write_path(eset, 3, 146520000, 'SRC')
        result = profilecontroller.create_profile_from_editorset(
            eset, name='ApplyViaMenu')

        target_eset, target_memedit = self._empty_target_csv()
        # open_file() (inside _empty_target_csv -> _blank_csv_editorset)
        # already made target_eset the active tab -- current_editorset
        # is a read-only, notebook-selection-derived property.
        self.assertIs(target_eset, self.frame.current_editorset)
        self.frame._current_profile = result.profile
        self.frame._current_profile_path = None

        def _approve_and_ok(parent, change_set):
            for item in change_set.items:
                if not item.blocked:
                    change_set.set_approval(
                        item.logical_id, profile_schema.APPROVAL_APPROVED)
            dlg = mock.MagicMock()
            dlg.ShowModal.return_value = wx.ID_OK
            return dlg

        with mock.patch.object(
                wxmain.profileapply, 'ProfileApplyPreviewDialog',
                side_effect=_approve_and_ok) as preview_dlg, \
                mock.patch(
                    'chirp.wxui.common.error_proof.show_error'
                    ) as show_error:
            self.frame._menu_profile_apply(None)

        show_error.assert_not_called()
        preview_dlg.assert_called_once()
        applied_names = [
            target_eset.radio.get_memory(n).name
            for n in range(*target_eset.radio.get_features().memory_bounds)
            if not target_eset.radio.get_memory(n).empty]
        self.assertIn('SRC', applied_names)

    def _empty_target_csv(self):
        target_eset = self._blank_csv_editorset()
        memedit_widget = profilecontroller.get_memedit(target_eset)
        target_eset.radio.erase_memory(0)
        memedit_widget.refresh()
        return target_eset, memedit_widget
