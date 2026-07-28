import threading
import unittest
from unittest import mock

import requests

from chirp.assistant import providers


class DisabledProviderTest(unittest.TestCase):
    def test_disabled_always_raises(self):
        p = providers.DisabledProvider()
        with self.assertRaises(providers.ProviderError):
            p.extract_intent('anything')

    def test_import_or_instantiate_makes_no_remote_call(self):
        # Constructing a provider must never make a remote call by
        # itself -- only extract_intent() may.
        with mock.patch('requests.post') as post:
            providers.DisabledProvider()
            providers.create_provider(providers.PROVIDER_DISABLED)
            post.assert_not_called()


class ParseStructuredResponseTest(unittest.TestCase):
    def test_valid_response(self):
        req = providers._parse_structured_response(
            '{"location_text": "Boise", "amateur_license": "general"}')
        self.assertEqual('Boise', req.location_text)
        self.assertEqual('general', req.amateur_license)

    def test_markdown_fence_tolerated(self):
        req = providers._parse_structured_response(
            '```json\n{"location_text": "Boise"}\n```')
        self.assertEqual('Boise', req.location_text)

    def test_malformed_json_rejected(self):
        with self.assertRaises(providers.ProviderError):
            providers._parse_structured_response('not json at all')

    def test_non_object_json_rejected(self):
        with self.assertRaises(providers.ProviderError):
            providers._parse_structured_response('[1, 2, 3]')

    def test_response_too_large_rejected(self):
        huge = '{"location_text": "%s"}' % ('x' * providers.MAX_RESPONSE_CHARS)
        with self.assertRaises(providers.ProviderError):
            providers._parse_structured_response(huge)

    def test_frequency_injection_ignored(self):
        req = providers._parse_structured_response(
            '{"location_text": "x", "freq": 146520000, '
            '"tone": 100.0, "offset": 600000}')
        self.assertFalse(hasattr(req, 'freq'))
        self.assertFalse(hasattr(req, 'tone'))
        self.assertFalse(hasattr(req, 'offset'))

    def test_excessive_channel_limit_rejected(self):
        with self.assertRaises(providers.ProviderError):
            providers._parse_structured_response(
                '{"channel_limit": 999999}')

    def test_invalid_license_rejected(self):
        with self.assertRaises(providers.ProviderError):
            providers._parse_structured_response(
                '{"amateur_license": "master"}')

    def test_non_string_content_rejected(self):
        with self.assertRaises(providers.ProviderError):
            providers._parse_structured_response(12345)


class HTTPProviderTest(unittest.TestCase):
    def test_openai_compatible_happy_path(self):
        provider = providers.OpenAICompatibleProvider(
            'https://example.invalid/v1/chat/completions', 'gpt-x',
            api_key='sk-test')
        fake_response = mock.Mock()
        fake_response.status_code = 200
        fake_response.json.return_value = {
            'choices': [{'message': {
                'content': '{"location_text": "Boise"}'}}]}
        with mock.patch('requests.post', return_value=fake_response) as post:
            req = provider.extract_intent('program my radio near Boise')
        self.assertEqual('Boise', req.location_text)
        # API key must be sent as a header, never appended to the URL.
        _args, kwargs = post.call_args
        self.assertIn('Authorization', kwargs['headers'])
        self.assertEqual('Bearer sk-test', kwargs['headers']['Authorization'])

    def test_ollama_happy_path(self):
        provider = providers.OllamaProvider(
            'http://localhost:11434/api/chat', 'llama3')
        fake_response = mock.Mock()
        fake_response.status_code = 200
        fake_response.json.return_value = {
            'message': {'content': '{"location_text": "Spokane"}'}}
        with mock.patch('requests.post', return_value=fake_response):
            req = provider.extract_intent('near Spokane')
        self.assertEqual('Spokane', req.location_text)

    def test_timeout_raises_provider_error(self):
        provider = providers.OpenAICompatibleProvider(
            'https://example.invalid', 'model')
        with mock.patch('requests.post',
                        side_effect=requests.exceptions.Timeout):
            with self.assertRaises(providers.ProviderError) as cm:
                provider.extract_intent('text')
        self.assertIn('timed out', str(cm.exception))

    def test_connection_error_message_sanitized(self):
        provider = providers.OpenAICompatibleProvider(
            'https://user:secretpass@example.invalid', 'model')
        with mock.patch(
                'requests.post',
                side_effect=requests.exceptions.ConnectionError(
                    'secretpass leaked in error')):
            with self.assertRaises(providers.ProviderError) as cm:
                provider.extract_intent('text')
        self.assertNotIn('secretpass', str(cm.exception))

    def test_auth_failure(self):
        provider = providers.OpenAICompatibleProvider(
            'https://example.invalid', 'model', api_key='bad-key')
        fake_response = mock.Mock()
        fake_response.status_code = 401
        with mock.patch('requests.post', return_value=fake_response):
            with self.assertRaises(providers.ProviderError) as cm:
                provider.extract_intent('text')
        self.assertIn('authentication', str(cm.exception).lower())
        self.assertNotIn('bad-key', str(cm.exception))

    def test_rate_limited(self):
        provider = providers.OpenAICompatibleProvider(
            'https://example.invalid', 'model')
        fake_response = mock.Mock()
        fake_response.status_code = 429
        with mock.patch('requests.post', return_value=fake_response):
            with self.assertRaises(providers.ProviderError):
                provider.extract_intent('text')

    def test_non_json_response(self):
        provider = providers.OpenAICompatibleProvider(
            'https://example.invalid', 'model')
        fake_response = mock.Mock()
        fake_response.status_code = 200
        fake_response.json.side_effect = ValueError('bad json')
        with mock.patch('requests.post', return_value=fake_response):
            with self.assertRaises(providers.ProviderError):
                provider.extract_intent('text')

    def test_unexpected_response_shape(self):
        provider = providers.OpenAICompatibleProvider(
            'https://example.invalid', 'model')
        fake_response = mock.Mock()
        fake_response.status_code = 200
        fake_response.json.return_value = {'unexpected': 'shape'}
        with mock.patch('requests.post', return_value=fake_response):
            with self.assertRaises(providers.ProviderError):
                provider.extract_intent('text')

    def test_input_too_long_rejected_before_remote_call(self):
        provider = providers.OpenAICompatibleProvider(
            'https://example.invalid', 'model')
        huge_text = 'x' * (providers.MAX_INPUT_CHARS + 1)
        with mock.patch('requests.post') as post:
            with self.assertRaises(providers.ProviderError):
                provider.extract_intent(huge_text)
            post.assert_not_called()

    def test_empty_text_rejected(self):
        provider = providers.OpenAICompatibleProvider(
            'https://example.invalid', 'model')
        with self.assertRaises(providers.ProviderError):
            provider.extract_intent('   ')

    def test_cancelled_before_request(self):
        provider = providers.OpenAICompatibleProvider(
            'https://example.invalid', 'model')
        cancel_event = threading.Event()
        cancel_event.set()
        with mock.patch('requests.post') as post:
            with self.assertRaises(providers.ProviderCancelled):
                provider.extract_intent('text', cancel_event=cancel_event)
            post.assert_not_called()

    def test_no_retry_on_failure(self):
        provider = providers.OpenAICompatibleProvider(
            'https://example.invalid', 'model')
        with mock.patch(
                'requests.post',
                side_effect=requests.exceptions.Timeout) as post:
            with self.assertRaises(providers.ProviderError):
                provider.extract_intent('text')
        self.assertEqual(1, post.call_count)


class FactoryTest(unittest.TestCase):
    def test_disabled_default(self):
        p = providers.create_provider('bogus_kind')
        self.assertEqual(providers.PROVIDER_DISABLED, p.kind)

    def test_openai_compatible_requires_endpoint_and_model(self):
        with self.assertRaises(providers.ProviderError):
            providers.create_provider(providers.PROVIDER_OPENAI_COMPATIBLE)

    def test_ollama_requires_endpoint_and_model(self):
        with self.assertRaises(providers.ProviderError):
            providers.create_provider(providers.PROVIDER_OLLAMA)

    def test_no_hidden_fallback_between_providers(self):
        # Creating an OpenAI-compatible provider must never silently
        # hand back an Ollama or other provider instance.
        p = providers.create_provider(
            providers.PROVIDER_OPENAI_COMPATIBLE,
            endpoint='https://example.invalid', model='m')
        self.assertIsInstance(p, providers.OpenAICompatibleProvider)


if __name__ == '__main__':
    unittest.main()
