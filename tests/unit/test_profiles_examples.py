import os
import unittest

from chirp.profiles import serialization

_EXAMPLES_DIR = os.path.join(
    os.path.dirname(__file__), '..', '..', 'docs', 'examples')


class ExampleProfileFixtureTest(unittest.TestCase):
    """Keeps the example profile shipped in docs/examples/ schema-valid
    as the domain model evolves (section 17: "Add fixtures for valid
    and invalid profiles")."""

    def test_north_idaho_camping_example_loads_and_validates(self):
        path = os.path.join(
            _EXAMPLES_DIR, 'north_idaho_camping.chirp-profile.json')
        profile = serialization.load(path)
        self.assertEqual('North Idaho Camping', profile.name)
        self.assertGreaterEqual(len(profile.channels), 4)
        rx_only = [c for c in profile.channels if c.receive_only]
        self.assertTrue(rx_only)
