"""HTTP regression tests for the binary frame API and queued commands."""
import json
import threading
import time
import unittest
from http.client import HTTPConnection
from app import create_server


class HttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = create_server(0)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def request(self, method, path, data=None, origin=None):
        c = HTTPConnection('127.0.0.1', self.server.server_port, timeout=10)
        headers = {'Content-Type': 'application/json'}
        if origin:
            headers['Origin'] = origin
        c.request(method, path, None if data is None else json.dumps(data), headers)
        r = c.getresponse()
        status, body = r.status, r.read()
        c.close()
        return status, body

    def decode(self, body):
        size = int.from_bytes(body[:4], 'little')
        meta = json.loads(body[4:4+size])
        self.assertEqual(len(body)-4-size, meta['count']*8)
        return meta, body[4+size:]

    def test_same_host_https_and_local_origin(self):
        for scheme in ('http', 'https'):
            status, body = self.request('POST', '/api/step', {},
                f'{scheme}://127.0.0.1:{self.server.server_port}')
            self.assertEqual(status, 200)
            self.decode(body)

    def test_foreign_origins_rejected(self):
        for origin in ('https://evil.example', 'null',
                       f'http://127.0.0.1:{self.server.server_port}.evil.example'):
            status, _ = self.request('POST', '/api/step', {}, origin)
            self.assertEqual(status, 403)

    def test_new_scene_commands_publish_materials(self):
        for name, kind in [('diarrhea', 4), ('clumps', 5), ('vomit', 6), ('soup', 7)]:
            status, body = self.request('POST', '/api/step', {'action':'scene','scene':name})
            self.assertEqual(status, 200)
            self.decode(body)
            deadline = time.monotonic()+5
            while True:
                status, body = self.request('GET', '/api/frame')
                self.assertEqual(status, 200)
                meta, raw = self.decode(body)
                kinds = set(raw[6::8])
                if kind in kinds:
                    break
                if time.monotonic() >= deadline:
                    self.fail(f'Scene {name} did not arrive')
                time.sleep(.01)
            if kind in (6, 7):
                self.assertIn(kind+2, kinds)
            self.assertEqual(len(meta['materials']), 10)

    def test_invalid_scene_and_static_files(self):
        status, body = self.request('POST', '/api/step', {'action':'scene','scene':'invalid'})
        self.assertEqual(status, 400)
        self.assertIn('error', json.loads(body))
        for path in ('/', '/app.js', '/renderer.js', '/style.css'):
            status, body = self.request('GET', path)
            self.assertEqual(status, 200)
            self.assertTrue(body)


if __name__ == '__main__':
    unittest.main()
