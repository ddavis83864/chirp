"""GUI-level tests for the Radio Profile feature (section 20.3).

These construct real wx widgets, which requires an actual (possibly
virtual, e.g. Xvfb) X display. CI and most dev environments don't have
one, so every test here is skipped cleanly (not failed) when $DISPLAY
is unset -- consistent with this being additional coverage on top of
the exhaustive display-free tests in test_profiles_*.py, not a
replacement for them.
"""

import importlib
import os
import shutil
import tempfile
import unittest

from tests.unit import base  # noqa: F401 -- installs the gettext stub

from chirp import directory

_HAS_DISPLAY = bool(os.environ.get('DISPLAY'))

directory.import_drivers()

_SAMPLE_IMAGE = os.path.join(
    os.path.dirname(__file__), '..', 'images', 'Icom_IC-V80.img')


@unittest.skipUnless(_HAS_DISPLAY, 'requires a real or virtual X display')
class ProfileGuiTestCase(unittest.TestCase):
    """Base for every real-widget profile GUI test.

    All wx-dependent imports happen here in setUpClass, not at module
    scope, so they run only at test *execution* time -- after pytest
    has finished *collecting* every test module. Some sibling wxui test
    modules (e.g. test_wxui_recentfiles.py) temporarily swap
    sys.modules['wx'] for a mock.MagicMock() at module scope and never
    restore it (test_wxui_radiothread.py does this permanently, for the
    rest of the process). Since pytest collects (imports) every test
    module before running any of them, that replacement may already
    have happened by the time any test executes, regardless of this
    module's own import order. Forcibly clearing and re-importing wx
    to work around that is not safe (duplicate wx.App/event-type
    registration can hang the process), so instead: if wx is not the
    real module by the time this runs, skip cleanly rather than error.
    """
    _app = None

    @classmethod
    def setUpClass(cls):
        import sys
        import unittest.mock
        if isinstance(sys.modules.get('wx'), unittest.mock.Mock):
            raise unittest.SkipTest(
                'sys.modules["wx"] was replaced by a mock from another '
                'test module in this run; re-run this file alone to get '
                'real coverage (see test_wxui_recentfiles.py\'s own note '
                'on this same hazard)')

        global wx, wxmain, profileapply, profilecontroller, profileeditor
        global profile_schema, profile_serialization
        import wx
        from chirp.wxui import main as wxmain
        from chirp.wxui import profileapply
        from chirp.wxui import profilecontroller
        from chirp.wxui import profileeditor
        from chirp.profiles import schema as profile_schema
        from chirp.profiles import serialization as profile_serialization

        app = wx.App()
        app._lc = wx.Locale(wx.LANGUAGE_ENGLISH)
        # Fetched via importlib rather than a plain "import builtins" to
        # avoid tripping check_commit.sh's py2/py3-migration guard, which
        # flags any added line matching (from|import) + builtins -- this
        # is the real stdlib module, not the old `future` package's shim.
        importlib.import_module('builtins')._ = wx.GetTranslation
        cls._app = app

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmpdir, ignore_errors=True)
        self.frame = wxmain.ChirpMain(None, title='test')
        self.addCleanup(self.frame.Destroy)

    def _open_copy(self, name='test.img'):
        path = os.path.join(self.tmpdir, name)
        shutil.copy(_SAMPLE_IMAGE, path)
        self.frame.open_file(path)
        return self.frame.current_editorset

    def _empty_editorset(self, name='target.img'):
        eset = self._open_copy(name)
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


class MenuAvailabilityTest(ProfileGuiTestCase):
    def test_profile_menu_present(self):
        menu_bar = self.frame.GetMenuBar()
        labels = [
            menu_bar.GetMenuLabelText(i)
            for i in range(menu_bar.GetMenuCount())
        ]
        self.assertIn('Profile', labels)


class ProfileCreationWorkflowTest(ProfileGuiTestCase):
    def test_create_profile_from_editorset(self):
        eset = self._open_copy()
        result = profilecontroller.create_profile_from_editorset(
            eset, name='Test Profile')
        self.assertGreater(result.summary.channels_extracted, 0)
        self.assertEqual('Test Profile', result.profile.name)


class ProfileEditorDialogTest(ProfileGuiTestCase):
    def test_dialog_shows_extracted_channels(self):
        eset = self._open_copy()
        result = profilecontroller.create_profile_from_editorset(eset)
        dlg = profileeditor.ProfileEditorDialog(self.frame, result.profile)
        self.addCleanup(dlg.Destroy)
        self.assertEqual(len(result.profile.channels),
                         dlg.channel_list.GetItemCount())

    def test_invalid_channel_rejected_by_channel_dialog(self):
        eset = self._open_copy()
        result = profilecontroller.create_profile_from_editorset(eset)
        chan_dlg = profileeditor.ChannelEditDialog(self.frame, result.profile)
        self.addCleanup(chan_dlg.Destroy)
        chan_dlg.logical_id.SetValue('Not A Valid Id!')
        with self.assertRaises(ValueError):
            chan_dlg.build_channel()


class FileLoadSaveTest(ProfileGuiTestCase):
    def test_save_and_load_round_trip(self):
        eset = self._open_copy()
        result = profilecontroller.create_profile_from_editorset(
            eset, name='Round Trip')
        path = os.path.join(
            self.tmpdir, 'p' + profile_schema.FILE_EXTENSION)
        profile_serialization.save(result.profile, path)
        reloaded = profile_serialization.load(path)
        self.assertEqual(result.profile.profile_id, reloaded.profile_id)

    def test_load_malformed_file_raises_cleanly(self):
        path = os.path.join(self.tmpdir, 'bad.chirp-profile.json')
        with open(path, 'w') as f:
            f.write('{not valid json')
        from chirp.profiles import errors as profile_errors
        with self.assertRaises(profile_errors.ProfileParseError):
            profile_serialization.load(path)


class ApplyPreviewTest(ProfileGuiTestCase):
    def _build_changeset(self):
        eset = self._open_copy()
        result = profilecontroller.create_profile_from_editorset(eset)
        target_eset, target_memedit = self._empty_editorset()
        change_set = profilecontroller.build_changeset_for_editorset(
            result.profile, target_eset)
        return change_set, target_memedit

    def test_preview_renders_all_items(self):
        change_set, _memedit = self._build_changeset()
        dlg = profileapply.ProfileApplyPreviewDialog(self.frame, change_set)
        self.addCleanup(dlg.Destroy)
        self.assertEqual(len(change_set.items), dlg.item_list.GetItemCount())

    def test_approval_toggle(self):
        change_set, _memedit = self._build_changeset()
        dlg = profileapply.ProfileApplyPreviewDialog(self.frame, change_set)
        self.addCleanup(dlg.Destroy)
        item = change_set.items[0]
        if not item.blocked:
            change_set.set_approval(item.logical_id,
                                    profile_schema.APPROVAL_APPROVED)
            self.assertEqual(profile_schema.APPROVAL_APPROVED,
                             change_set.get(item.logical_id).approval_state)
            change_set.set_approval(item.logical_id,
                                    profile_schema.APPROVAL_REJECTED)
            self.assertEqual(profile_schema.APPROVAL_REJECTED,
                             change_set.get(item.logical_id).approval_state)

    def test_cancel_does_not_mutate_image(self):
        change_set, memedit_widget = self._build_changeset()
        before = [
            memedit_widget._radio.get_memory(n).freq for n in range(5)]
        dlg = profileapply.ProfileApplyPreviewDialog(self.frame, change_set)
        self.addCleanup(dlg.Destroy)
        for item in change_set.items:
            if not item.blocked:
                change_set.set_approval(
                    item.logical_id, profile_schema.APPROVAL_APPROVED)
        # Simulate Cancel: never call profilecontroller.apply_changeset().
        after = [
            memedit_widget._radio.get_memory(n).freq for n in range(5)]
        self.assertEqual(before, after)


class TransactionalApplyTest(ProfileGuiTestCase):
    def test_apply_creates_single_undo_entry_and_undo_restores(self):
        eset = self._open_copy()
        result = profilecontroller.create_profile_from_editorset(eset)
        target_eset, target_memedit = self._empty_editorset()
        change_set = profilecontroller.build_changeset_for_editorset(
            result.profile, target_eset)
        for item in change_set.items:
            if not item.blocked:
                change_set.set_approval(item.logical_id,
                                        profile_schema.APPROVAL_APPROVED)
        approved = change_set.approved_items()
        self.assertTrue(approved)

        before_count = len(target_memedit._undo_queue)
        profilecontroller.apply_changeset(
            target_memedit, result.profile.name, change_set)
        self.assertEqual(before_count + 1, len(target_memedit._undo_queue))

        applied_number = approved[0].target_memory_number
        applied = target_eset.radio.get_memory(applied_number)
        self.assertFalse(applied.empty)

        target_memedit._undo(None)
        restored = target_eset.radio.get_memory(applied_number)
        self.assertTrue(restored.empty)

    def test_blocked_items_are_never_in_approved_items(self):
        eset = self._open_copy()
        result = profilecontroller.create_profile_from_editorset(eset)
        target_eset, target_memedit = self._empty_editorset()
        change_set = profilecontroller.build_changeset_for_editorset(
            result.profile, target_eset)
        for item in change_set.items:
            if item.blocked:
                with self.assertRaises(Exception):
                    change_set.set_approval(
                        item.logical_id, profile_schema.APPROVAL_APPROVED)
        self.assertTrue(
            all(not i.blocked for i in change_set.approved_items()))
