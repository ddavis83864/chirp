import sys
from unittest import mock

from chirp import chirp_common
import lark
from tests.unit import base

# Snapshot sys.modules before mocking so it can be restored exactly,
# immediately below, once this file's own import is done with it. See
# the restore block after the import for why both the snapshot and the
# immediate (not fixture-based) timing are needed -- this mirrors the
# identical pattern (and the identical underlying problem) already
# fixed in test_wxui_radiothread.py and test_wxui_linux_launcher.py.
_PRE_MOCK_SYS_MODULES = dict(sys.modules)


def _evict_chirp_wxui_modules():
    """Remove every already-imported chirp.wxui.* submodule (and the
    parent package's attribute reference to it) so that whatever
    imports chirp.wxui submodules next gets a fresh import rather than
    reusing a module cached from however wx looked the last time it
    was genuinely imported. See test_wxui_linux_launcher.py, which has
    the identical helper (and the identical underlying problem) with a
    more detailed explanation of why both the sys.modules removal and
    the parent-attribute cleanup are needed."""
    for name in list(sys.modules):
        if name != 'chirp.wxui' and not name.startswith('chirp.wxui.'):
            continue
        if name == 'chirp.wxui':
            continue
        del sys.modules[name]
        parent_name, _, attr = name.rpartition('.')
        parent = sys.modules.get(parent_name)
        if parent is not None:
            vars(parent).pop(attr, None)


_evict_chirp_wxui_modules()

sys.modules['wx'] = wx = mock.MagicMock()
sys.modules['wx.adv'] = mock.MagicMock()

from chirp.wxui import memquery  # noqa

# Restore sys.modules immediately -- synchronously, still as part of
# this file's own collection -- for the same reason and via the same
# mechanism as test_wxui_linux_launcher.py / test_wxui_radiothread.py:
# pytest fully collects every test file before executing any test, so
# restoring only once this file's own tests finish executing (e.g. via
# a pytest fixture) is too late to stop a later-collected real-wx test
# file (like test_wxui_programming_assistant.py) from seeing this mock
# during *its* collection.
#
# Without this restore, `chirp.wxui.memquery.SearchBox` -- a real class
# that subclasses wx.TextCtrl -- gets built against the *fake* wx.
# Subclassing a MagicMock attribute doesn't raise; it silently produces
# a MagicMock standing in for the class instead, whose first call
# succeeds and every subsequent call raises StopIteration. Since
# chirp/wxui/memedit.py only constructs a SearchBox when
# `sys.platform != 'linux'`, this stayed invisible as long as tests/unit
# only ever ran on Linux -- confirmed by direct reproduction that
# forcing sys.platform to 'win32' after collection reproduces dozens of
# StopIteration failures across test_wxui_programming_assistant.py
# whenever this file is collected first, and that restoring
# sys.modules here (so memquery is freely reimportable against the real
# wx) eliminates them.
_affected = {n for n in set(_PRE_MOCK_SYS_MODULES) | set(sys.modules)
             if n == 'wx' or n.startswith('wx.') or
             n.startswith('chirp.wxui.')}
for _name in _affected:
    _parent_name, _, _attr = _name.rpartition('.')
    _parent = sys.modules.get(_parent_name)
    if _name in _PRE_MOCK_SYS_MODULES:
        sys.modules[_name] = _PRE_MOCK_SYS_MODULES[_name]
        if _parent is not None:
            setattr(_parent, _attr, _PRE_MOCK_SYS_MODULES[_name])
    else:
        sys.modules.pop(_name, None)
        if _parent is not None:
            vars(_parent).pop(_attr, None)


class TestMemquery(base.BaseTest):
    def _get_sample_memories(self):
        mems = []
        freqs = (118, 145, 146, 440, 800)
        for i, freq in enumerate(freqs):
            mem = chirp_common.Memory(1 + i, name="mem%s" % freq)
            mem.freq = freq * 1000000
            mem.mode = "FM"
            mems.append(mem)
        return mems

    def test_query_parse(self):
        query = ('name="foo" OR name IN ["mem800", "baz"] OR '
                 '(mode="FM" AND freq<144,147.1>) OR '
                 'name~"7$"')
        parser = lark.Lark(memquery.LANG)
        transformer = memquery.Interpreter(self._get_sample_memories())
        filtered = transformer.transform(parser.parse(query)).children[0]
        self.assertEqual(3, len(filtered), filtered)
        self.assertEqual([145, 146, 800],
                         sorted([x.freq // 1000000 for x in filtered]))
