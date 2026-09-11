"""Local Python simulation and HTML5 interface. No cloud or CDN dependencies."""
import argparse
import json
import math
from pathlib import Path
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from physics import Simulation, Material

ROOT = Path(__file__).resolve().parent


def number(data, key, default, low, high):
    value = float(data.get(key, default))
    if not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f'{key}: erwartet {low} bis {high}')
    return value


def create_server(port=8765):
    sim = Simulation()
    sim.scene('dam')
    lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            if args and str(args[1] if len(args) > 1 else '') not in ('200', '304'):
                super().log_message(fmt, *args)

        def respond(self, body, status=200, mime='application/json'):
            self.send_response(status)
            self.send_header('Content-Type', mime)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path == '/api/state':
                with lock:
                    data = sim.snapshot()
                self.respond(json.dumps(data).encode())
            elif self.path in ('/', '/style.css', '/app.js', '/renderer.js'):
                name = {'/':'index.html', '/style.css':'style.css', '/app.js':'app.js', '/renderer.js':'renderer.js'}[self.path]
                mime = {'/':'text/html; charset=utf-8', '/style.css':'text/css', '/app.js':'text/javascript', '/renderer.js':'text/javascript'}[self.path]
                self.respond((ROOT/'web'/name).read_bytes(), mime=mime)
            else:
                self.respond(b'{}', 404)

        def do_POST(self):
            if self.path != '/api/step':
                self.respond(b'{}', 404); return
            # Reject cross-origin browser requests to this local application.
            origin = self.headers.get('Origin')
            if origin and origin != f'http://{self.headers.get("Host")}':
                self.respond(b'{}', 403); return
            try:
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 < size <= 32768:
                    raise ValueError('Ungueltige Anfragegroesse')
                data = json.loads(self.rfile.read(size))
                if not isinstance(data, dict):
                    raise ValueError('JSON-Objekt erwartet')
                with lock:
                    start = time.perf_counter()
                    action = data.get('action')
                    if action == 'scene':
                        if data.get('scene') not in ('empty', 'dam', 'layers'):
                            raise ValueError('Unbekannte Szene')
                        sim.scene(data['scene'])
                    elif action == 'pause':
                        sim.paused = not sim.paused
                    elif action == 'material':
                        if len(sim.materials) >= 32:
                            raise ValueError('Maximal 32 Materialien')
                        sim.materials.append(Material('Eigenes '+str(len(sim.materials)-3), '#69e8bc',
                            number(data, 'density', 1000, 300, 3000),
                            number(data, 'viscosity', .01, .0001, 10),
                            number(data, 'flammability', 0, 0, 1),
                            number(data, 'ignition', 300, 50, 800), 2500,
                            number(data, 'cohesion', .05, 0, .15)))
                    sim.gravity = number(data, 'gravity', sim.gravity, 0, 20)
                    pointer = data.get('pointer')
                    if pointer:
                        x = number(pointer, 'x', .5, 0, sim.width)
                        y = number(pointer, 'y', .5, 0, sim.height)
                        radius = number(pointer, 'radius', .06, .025, .16)
                        tool = pointer.get('tool', 'emit')
                        if tool == 'emit':
                            sim.emit(x, y, int(number(pointer, 'kind', 0, 0, len(sim.materials)-1)), radius,
                                     number(pointer, 'temperature', 20, 0, 800))
                        else:
                            sim.interact(tool, x, y, radius,
                                number(pointer, 'dx', 0, -2, 2), number(pointer, 'dy', 0, -2, 2))
                    if action == 'single':
                        old = sim.paused
                        sim.paused = False
                        sim.advance()
                        sim.paused = old
                    elif not action:
                        sim.advance(number(data, 'dt', 1/60, 0, 1/30))
                    result = sim.snapshot()
                    result['compute_ms'] = round((time.perf_counter()-start)*1000, 1)
                self.respond(json.dumps(result, allow_nan=False).encode())
            except (ValueError, TypeError, KeyError, OverflowError) as exc:
                self.respond(json.dumps({'error': str(exc)}).encode(), 400)

    return ThreadingHTTPServer(('127.0.0.1', port), Handler)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='FluidPy – Python SPH + HTML5')
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args()
    try:
        server = create_server(args.port)
    except OSError as exc:
        parser.exit(1, f'Port {args.port} nicht verfuegbar: {exc}\nTipp: --port 8766\n')
    url = f'http://127.0.0.1:{server.server_port}'
    print(f'FluidPy: {url}\nBeenden: Strg+C', flush=True)
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
