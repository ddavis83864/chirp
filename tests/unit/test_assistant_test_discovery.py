"""Regression guard for a real bug found during remediation review: five
assistant test methods had "network" as a substring in their name (e.g.
test_no_network_call_when_network_disallowed), which caused pytest's
`-k "not network"` keyword filter -- exactly what CI's unit job uses,
see .github/workflows/py3-test.yaml -- to silently deselect them. They
were legitimate offline/mocked tests with no actual network I/O; the
bug was purely nominal, but CI never ran them as a result.

This test statically inspects every chirp.assistant/programming_assistant
test module for method names containing a keyword substring that would
collide with pytest -k filters known to be used by CI or documented
here, so a later test addition can't reintroduce the same silent gap.
"""

import importlib
import inspect
import unittest

# Keep in sync with any `-k` expression used by CI or documented as a
# standard invocation for this project (currently just "network", from
# .github/workflows/py3-test.yaml's `tox_args: -k "not network"`).
_FORBIDDEN_SUBSTRINGS = ('network',)

_MODULES = (
    'tests.unit.test_assistant_models',
    'tests.unit.test_assistant_policies',
    'tests.unit.test_assistant_planner',
    'tests.unit.test_assistant_converter_validator',
    'tests.unit.test_assistant_providers',
    'tests.unit.test_assistant_providers_integration',
    'tests.unit.test_assistant_planning_scenarios',
    'tests.unit.test_assistant_radio_profiles',
    'tests.unit.test_assistant_save_reopen',
    'tests.unit.test_assistant_sources',
    'tests.unit.test_assistant_service',
    'tests.unit.test_wxui_programming_assistant',
)


class TestNamingDoesNotCollideWithCIFilters(unittest.TestCase):
    def test_no_test_method_name_contains_forbidden_substring(self):
        offenders = []
        for modname in _MODULES:
            module = importlib.import_module(modname)
            for _name, cls in inspect.getmembers(module, inspect.isclass):
                if not issubclass(cls, unittest.TestCase):
                    continue
                if cls.__module__ != modname:
                    continue  # skip imported base classes
                for attr in dir(cls):
                    if not attr.startswith('test_'):
                        continue
                    for bad in _FORBIDDEN_SUBSTRINGS:
                        if bad in attr:
                            offenders.append(
                                '%s.%s.%s (contains %r)' % (
                                    modname, cls.__name__, attr, bad))
        self.assertEqual(
            [], offenders,
            'Test method names below contain a substring that pytest\'s '
            '-k "not network" (used by CI\'s unit job) would silently '
            'deselect, even though these are offline/mocked tests. '
            'Rename them to avoid the substring:\n' + '\n'.join(offenders))


if __name__ == '__main__':
    unittest.main()
