"""Regression: HTTPS reverse proxy must permit drawing, not arbitrary origins."""
import json
import threading
import unittest
from http.client import HTTPConnection
from app import create_server


class ProxyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = create_server(0, public_origins=['https://fluid.occdn.com'])
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def request(self, origin, data, extra=None):
        c = HTTPConnection('127.0.0.1', self.server.server_port, timeout=10)
        headers = {'Content-Type': 'application/json', 'Origin': origin}
        headers.update(extra or {})
        c.request('POST', '/api/step', json.dumps(data), headers)
        r = c.getresponse()
        status, body = r.status, json.loads(r.read())
        c.close()
        return status, body

    def test_https_proxy_can_draw_with_internal_host(self):
        origin = 'https://fluid.occdn.com'
        status, before = self.request(origin, {'dt': 0})
        self.assertEqual(status, 200)
        status, after = self.request(origin, {'action': 'pointer', 'pointer': {
            'x': 1.4, 'y': .85, 'tool': 'emit', 'kind': 0, 'radius': .04}})
        self.assertEqual(status, 200)
        self.assertGreater(after['count'], before['count'])

    def test_local_origin_still_works(self):
        status, _ = self.request(f'http://127.0.0.1:{self.server.server_port}', {'dt': 0})
        self.assertEqual(status, 200)

    def test_unknown_origins_and_forged_forwarded_headers_rejected(self):
        for origin in ('https://evil.example', 'https://fluid.occdn.com.evil.example', 'null', 'http://fluid.occdn.com'):
            with self.subTest(origin=origin):
                status, body = self.request(origin, {'dt': 0}, {
                    'Host': 'evil.example', 'X-Forwarded-Host': 'fluid.occdn.com', 'X-Forwarded-Proto': 'https'})
                self.assertEqual(status, 403)
                self.assertIn('error', body)


if __name__ == '__main__':
    unittest.main(verbosity=2)
