import sys
from unittest import mock

from chirp import chirp_common
import lark
from tests.unit import base

# Snapshot sys.modules before mocking, and evict any already-imported
# chirp.wxui.* submodule, so this file's mock 'wx' can't leak into (or
# inherit stale state from) a real-wx test collected before or after
# it in the same pytest session. chirp.wxui.memquery itself defines
# classes (SearchHelp, SearchBox) that subclass real wx types, so it
# is exactly as much at risk here as chirp.wxui.common is elsewhere.
# Same pattern as, and adapted from,
# tests/unit/test_wxui_linux_launcher.py -- see that file's own
# comments for the full rationale and confirmed-by-reproduction
# details; this file only needs the short version.
_PRE_MOCK_SYS_MODULES = dict(sys.modules)


def _evict_chirp_wxui_modules():
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
sys.modules['wx.adv'] = wx = mock.MagicMock()

from chirp.wxui import memquery  # noqa

# Restore sys.modules immediately (synchronously, during this file's
# own collection -- see test_wxui_linux_launcher.py's comments for why
# a pytest fixture's teardown would run too late to help).
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
