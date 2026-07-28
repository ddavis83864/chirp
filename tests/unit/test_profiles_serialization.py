import json
import os
import tempfile
import unittest

from chirp.profiles import errors
from chirp.profiles import model
from chirp.profiles import schema
from chirp.profiles import serialization


def _valid_profile():
    p = model.Profile(name='North Idaho Camping', region='US')
    p.groups['local-repeaters'] = model.LogicalGroup(
        id='local-repeaters', name='Local Repeaters')
    p.add_channel(model.ProfileChannel(
        logical_id='local-cda-2m-repeater-01',
        name='CDA Repeater',
        rx_freq_hz=146520000,
        transmit=model.TransmitBehavior(mode=schema.TRANSMIT_ENABLED,
                                        duplex=schema.DUPLEX_POSITIVE,
                                        offset_hz=600000),
        groups=('local-repeaters',),
    ))
    p.add_channel(model.ProfileChannel(
        logical_id='noaa-weather-01',
        name='NOAA WX1',
        rx_freq_hz=162550000,
        transmit=model.TransmitBehavior(mode=schema.TRANSMIT_RECEIVE_ONLY),
    ))
    return p


class JsonRoundTripTest(unittest.TestCase):
    def test_round_trip_preserves_content(self):
        p = _valid_profile()
        text = serialization.to_json(p)
        p2 = serialization.from_json(text)
        self.assertEqual(p.profile_id, p2.profile_id)
        self.assertEqual(p.name, p2.name)
        self.assertEqual(len(p.channels), len(p2.channels))
        self.assertEqual(p.channels[0].logical_id, p2.channels[0].logical_id)
        self.assertTrue(p2.channels[1].receive_only)

    def test_output_is_deterministic(self):
        p = _valid_profile()
        self.assertEqual(serialization.to_json(p), serialization.to_json(p))

    def test_output_is_plain_json_no_executable_content(self):
        text = serialization.to_json(_valid_profile())
        # json.loads succeeding (and nothing resembling a python object
        # tag) is our proof there's no pickle/eval-able payload embedded.
        data = json.loads(text)
        self.assertIsInstance(data, dict)
        self.assertNotIn('__reduce__', text)
        self.assertNotIn('!!python', text)

    def test_utf8_names_round_trip(self):
        p = model.Profile(name='Profil Radioamateur – café')
        p.add_channel(model.ProfileChannel(logical_id='x-1',
                                           name='Répéteur',
                                           rx_freq_hz=146520000))
        text = serialization.to_json(p)
        p2 = serialization.from_json(text)
        self.assertEqual('Profil Radioamateur – café', p2.name)
        self.assertEqual('Répéteur', p2.channels[0].name)


class MalformedInputTest(unittest.TestCase):
    def test_malformed_json_raises_parse_error(self):
        with self.assertRaises(errors.ProfileParseError):
            serialization.from_json('{not valid json')

    def test_non_object_json_raises(self):
        with self.assertRaises(errors.ProfileValidationError):
            serialization.from_json('[1, 2, 3]')

    def test_unknown_major_schema_version_rejected(self):
        p = _valid_profile()
        data = p.to_dict()
        data['schema_version'] = '99.0'
        with self.assertRaises(errors.ProfileSchemaVersionError):
            serialization.from_dict(data)

    def test_missing_required_field_rejected(self):
        data = _valid_profile().to_dict()
        del data['channels']
        with self.assertRaises(errors.ProfileValidationError):
            serialization.from_dict(data)

    def test_duplicate_logical_ids_rejected(self):
        data = _valid_profile().to_dict()
        data['channels'].append(dict(data['channels'][0]))
        with self.assertRaises(errors.ProfileValidationError):
            serialization.from_dict(data)

    def test_invalid_uuid_rejected(self):
        data = _valid_profile().to_dict()
        data['profile_id'] = 'not-a-uuid'
        with self.assertRaises(errors.ProfileValidationError):
            serialization.from_dict(data)

    def test_invalid_frequency_rejected(self):
        data = _valid_profile().to_dict()
        data['channels'][0]['rx_freq_hz'] = 'a lot'
        with self.assertRaises(errors.ProfileValidationError):
            serialization.from_dict(data)

    def test_malformed_json_does_not_execute_anything(self):
        # A python/pickle-style tag embedded in a string value is just
        # inert text to json.loads -- there is no code path that would
        # act on it.
        text = '{"schema_version": "1.0", "profile_id": ' \
              '"11111111-1111-1111-1111-111111111111", "name": ' \
              '"!!python/object/apply:os.system [\\"echo pwned\\"]", ' \
              '"created_at": "2026-01-01T00:00:00+00:00", ' \
              '"modified_at": "2026-01-01T00:00:00+00:00", "channels": []}'
        p = serialization.from_json(text)
        self.assertIn('!!python', p.name)  # treated as inert string data


class AtomicSaveLoadTest(unittest.TestCase):
    def test_save_then_load_round_trips(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, 'test.chirp-profile.json')
            p = _valid_profile()
            serialization.save(p, path)
            p2 = serialization.load(path)
            self.assertEqual(p.profile_id, p2.profile_id)

    def test_save_does_not_corrupt_existing_file_on_validation_failure(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, 'test.chirp-profile.json')
            good = _valid_profile()
            serialization.save(good, path)
            with open(path, 'r', encoding='utf-8') as f:
                original_text = f.read()

            bad = _valid_profile()
            bad.channels[0].rx_freq_hz = -1
            with self.assertRaises(errors.ProfileValidationError):
                serialization.save(bad, path)

            with open(path, 'r', encoding='utf-8') as f:
                self.assertEqual(original_text, f.read())

    def test_save_leaves_no_temp_file_behind(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, 'test.chirp-profile.json')
            serialization.save(_valid_profile(), path)
            self.assertEqual(['test.chirp-profile.json'], os.listdir(d))

    def test_load_missing_file_raises_io_error(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(errors.ProfileIOError):
                serialization.load(os.path.join(d, 'does-not-exist.json'))
