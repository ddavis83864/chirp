"""pytest plugin that forces sys.platform to a non-'linux' value for
the duration of test execution, loaded via the PYTEST_PLUGINS
environment variable in a subprocess (see
test_programming_assistant_headless_regression.py).

Only flips sys.platform after collection has finished
(pytest_collection_modifyitems), not at import time, so no stdlib or
pytest import machinery that branches on sys.platform at import time
(e.g. shutil's conditional `import _winapi`) is disturbed -- only
runtime `sys.platform` checks inside application code under test are
affected, which is exactly the condition real Windows/macOS CI runs
under.
"""
import sys


def pytest_collection_modifyitems(config, items):
    sys.platform = 'win32'
