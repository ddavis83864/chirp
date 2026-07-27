"""Integration coverage for chirp.assistant.providers against a real,
local, loopback-only HTTP fixture server -- not a live third-party AI
provider, and not a mock of the `requests` library.

tests/unit/test_assistant_providers.py already covers request/response
handling with `requests.post` mocked out entirely, which validates the
provider classes' own logic but never exercises the actual HTTP
plumbing (real sockets, real header transmission, real JSON body
parsing, real timeout behavior). This module closes that gap by
spinning up a throwaway http.server.HTTPServer bound to
127.0.0.1:0 (an OS-assigned free loopback port) for the duration of
each test, and pointing the real provider classes at it.

This is still fully offline: nothing here ever resolves a hostname or
opens a socket beyond 127.0.0.1. It must never be described as "live
provider" testing -- it is a deterministic local fixture standing in
for one.
"""

import contextlib
import http.server
import json
import threading
import unittest

from chirp.assistant import providers


def _handler_factory(handle_post):
    """Builds a BaseHTTPRequestHandler subclass whose do_POST delegates
    to @handle_post(handler_instance), and that captures request
    headers/body onto the server object for assertions."""

    class _Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a, **kw):
            pass  # keep test output quiet

        def do_POST(self):
            length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(length) if length else b''
            self.server.captured_headers = dict(self.headers)
            self.server.captured_body = body
            handle_post(self)

    return _Handler


@contextlib.contextmanager
def _local_fixture_server(handle_post):
    server = http.server.HTTPServer(
        ('127.0.0.1', 0), _handler_factory(handle_post))
    server.captured_headers = None
    server.captured_body = None
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        yield server, 'http://%s:%i/v1/chat/completions' % (host, port)
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def _json_response(handler, status, payload):
    body = json.dumps(payload).encode('utf-8')
    handler.send_response(status)
    handler.send_header('Content-Type', 'application/json')
    handler.send_header('Content-Length', str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


class OpenAICompatibleFixtureServerTest(unittest.TestCase):
    def test_happy_path_over_real_http(self):
        def handle_post(h):
            _json_response(h, 200, {
                'choices': [{'message': {
                    'content': '{"location_text": "Boise"}'}}]})

        with _local_fixture_server(handle_post) as (server, url):
            provider = providers.OpenAICompatibleProvider(
                url, 'gpt-x', api_key='sk-test')
            req = provider.extract_intent('program my radio near Boise')

        self.assertEqual('Boise', req.location_text)
        # Confirm the API key really went out over the wire as a
        # header, not just that the provider *would* set one.
        self.assertEqual('Bearer sk-test',
                         server.captured_headers.get('Authorization'))
        sent = json.loads(server.captured_body)
        self.assertEqual('gpt-x', sent['model'])

    def test_ollama_happy_path_over_real_http(self):
        def handle_post(h):
            _json_response(h, 200, {
                'message': {'content': '{"location_text": "Spokane"}'}})

        with _local_fixture_server(handle_post) as (server, url):
            provider = providers.OllamaProvider(url, 'llama3')
            req = provider.extract_intent('near Spokane')

        self.assertEqual('Spokane', req.location_text)
        sent = json.loads(server.captured_body)
        self.assertEqual('llama3', sent['model'])
        # Ollama provider carries no API key; no Authorization header
        # should have been sent at all.
        self.assertNotIn('Authorization', server.captured_headers)

    def test_auth_failure_real_401(self):
        def handle_post(h):
            _json_response(h, 401, {'error': 'bad key'})

        with _local_fixture_server(handle_post) as (_server, url):
            provider = providers.OpenAICompatibleProvider(
                url, 'gpt-x', api_key='bad-key')
            with self.assertRaises(providers.ProviderError) as cm:
                provider.extract_intent('text')
        self.assertIn('authentication', str(cm.exception).lower())
        self.assertNotIn('bad-key', str(cm.exception))

    def test_rate_limited_real_429(self):
        def handle_post(h):
            _json_response(h, 429, {'error': 'slow down'})

        with _local_fixture_server(handle_post) as (_server, url):
            provider = providers.OpenAICompatibleProvider(url, 'gpt-x')
            with self.assertRaises(providers.ProviderError):
                provider.extract_intent('text')

    def test_server_error_real_500(self):
        def handle_post(h):
            _json_response(h, 500, {'error': 'boom'})

        with _local_fixture_server(handle_post) as (_server, url):
            provider = providers.OpenAICompatibleProvider(url, 'gpt-x')
            with self.assertRaises(providers.ProviderError):
                provider.extract_intent('text')

    def test_malformed_json_body_over_real_http(self):
        def handle_post(h):
            body = b'this is not json'
            h.send_response(200)
            h.send_header('Content-Type', 'text/plain')
            h.send_header('Content-Length', str(len(body)))
            h.end_headers()
            h.wfile.write(body)

        with _local_fixture_server(handle_post) as (_server, url):
            provider = providers.OpenAICompatibleProvider(url, 'gpt-x')
            with self.assertRaises(providers.ProviderError):
                provider.extract_intent('text')

    def test_unexpected_shape_over_real_http(self):
        def handle_post(h):
            _json_response(h, 200, {'unexpected': 'shape'})

        with _local_fixture_server(handle_post) as (_server, url):
            provider = providers.OpenAICompatibleProvider(url, 'gpt-x')
            with self.assertRaises(providers.ProviderError):
                provider.extract_intent('text')

    def test_real_socket_timeout(self):
        # The fixture server accepts the connection but never responds
        # before the client's timeout elapses -- a real socket-level
        # timeout, not a mocked requests.exceptions.Timeout.
        release = threading.Event()

        def handle_post(h):
            release.wait(5)
            _json_response(h, 200, {
                'choices': [{'message': {'content': '{}'}}]})

        with _local_fixture_server(handle_post) as (_server, url):
            provider = providers.OpenAICompatibleProvider(url, 'gpt-x')
            try:
                with self.assertRaises(providers.ProviderError) as cm:
                    provider.extract_intent('text', timeout=0.3)
                self.assertIn('timed out', str(cm.exception))
            finally:
                release.set()

    def test_connection_refused_real_socket(self):
        # Nothing is listening on this loopback port.
        provider = providers.OpenAICompatibleProvider(
            'http://127.0.0.1:1/v1/chat/completions', 'gpt-x')
        with self.assertRaises(providers.ProviderError) as cm:
            provider.extract_intent('text')
        self.assertIn('reach', str(cm.exception).lower())

    def test_oversized_response_still_rejected_over_real_http(self):
        def handle_post(h):
            huge = 'x' * (providers.MAX_RESPONSE_CHARS + 1)
            content = '{"location_text": "%s"}' % huge
            _json_response(h, 200, {
                'choices': [{'message': {'content': content}}]})

        with _local_fixture_server(handle_post) as (_server, url):
            provider = providers.OpenAICompatibleProvider(url, 'gpt-x')
            with self.assertRaises(providers.ProviderError):
                provider.extract_intent('text')


if __name__ == '__main__':
    unittest.main()
