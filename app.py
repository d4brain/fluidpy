"""Local Python simulation and HTML5 interface. No cloud or CDN dependencies.

The solver runs in its own thread and publishes frames; the browser polls the
newest frame and interpolates between the last two. Rendering is therefore no
longer blocked by a solver step, and the particle payload is transferred as raw
float32 instead of JSON.
"""
import argparse
import json
import math
from pathlib import Path
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from physics import Simulation, Material, RESOLUTIONS

ROOT = Path(__file__).resolve().parent
FILES = {'/': ('index.html', 'text/html; charset=utf-8'),
         '/style.css': ('style.css', 'text/css'),
         '/app.js': ('app.js', 'text/javascript'),
         '/renderer.js': ('renderer.js', 'text/javascript')}


def number(data, key, default, low, high):
    value = float(data.get(key, default))
    if not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f'{key}: erwartet {low} bis {high}')
    return value


def frame_bytes(meta, particles):
    head = json.dumps(meta, allow_nan=False).encode()
    head += b' '*(-len(head) % 4)                      # keep float32 block aligned
    return len(head).to_bytes(4, 'little')+head+particles


class Engine:
    """Simulation thread. Steps only while a browser is actually polling."""

    idle_after = 1.0
    sim_step = 1/120   # smaller publish step: smoother interpolation, faster input echo

    def __init__(self):
        self.sim = Simulation()
        self.sim.scene('dam')
        self.lock = threading.Lock()
        self.commands = []
        self.frame = 0
        self.compute_ms = 0.
        self.interval_ms = 16.
        self.last_poll = 0.
        self.payload = frame_bytes(dict(self.sim.meta(), frame=0, compute_ms=0., interval_ms=16.),
                                   self.sim.packed())
        threading.Thread(target=self.run, daemon=True).start()

    def submit(self, apply_commands):
        with self.lock:
            self.commands.append(apply_commands)

    def poll(self):
        self.last_poll = time.monotonic()
        return self.payload

    def run(self):
        previous = last_frame = time.monotonic()
        budget = 0.
        while True:
            now = time.monotonic()
            if now-self.last_poll > self.idle_after:
                time.sleep(.05)
                previous = last_frame = time.monotonic()
                budget = 0.
                continue
            # Never run ahead of the wall clock; falling behind means honest
            # slow motion instead of a time jump.
            budget = min(budget+(now-previous), 2*self.sim_step)
            previous = now
            step = budget >= self.sim_step
            if not step and not self.commands:
                time.sleep(.001)
                continue
            if step:
                budget -= self.sim_step
            with self.lock:
                pending, self.commands = self.commands, []
                start = time.perf_counter()
                for apply_commands in pending:
                    try:
                        apply_commands(self.sim)
                    except (ValueError, TypeError, KeyError, OverflowError):
                        pass
                if step:
                    self.sim.advance(self.sim_step)
                self.compute_ms = (time.perf_counter()-start)*1000
                self.frame += 1
                span = (now-last_frame)*1000
                last_frame = now
                self.interval_ms = .85*self.interval_ms+.15*min(span, 500)
                meta = dict(self.sim.meta(), frame=self.frame,
                            compute_ms=round(self.compute_ms, 1),
                            interval_ms=round(self.interval_ms, 2))
                self.payload = frame_bytes(meta, self.sim.packed())
            # Never spin faster than the display; leaves a core for the browser.
            time.sleep(max(0., .0045-(time.perf_counter()-start)))


def build_commands(data):
    """Validate the request once, then return a closure applied in the thread."""
    action = data.get('action')
    if action not in (None, 'scene', 'pause', 'material', 'single', 'resolution'):
        raise ValueError('Unbekannte Aktion')
    scene = data.get('scene')
    if action == 'scene' and scene not in ('empty', 'dam', 'layers'):
        raise ValueError('Unbekannte Szene')
    resolution = data.get('resolution')
    if action == 'resolution' and resolution not in RESOLUTIONS:
        raise ValueError('Unbekannte Auflösung')
    gravity = number(data, 'gravity', 9.81, 0, 20)
    pointer = data.get('pointer')
    shot = None
    if pointer:
        shot = {'x': number(pointer, 'x', .5, 0, Simulation.width),
                'y': number(pointer, 'y', .5, 0, Simulation.height),
                'radius': number(pointer, 'radius', .06, .025, .16),
                'tool': pointer.get('tool', 'emit'),
                'kind': int(number(pointer, 'kind', 0, 0, 31)),
                'temperature': number(pointer, 'temperature', 20, 0, 800),
                'dx': number(pointer, 'dx', 0, -2, 2), 'dy': number(pointer, 'dy', 0, -2, 2)}
        if shot['tool'] not in ('emit', 'heat', 'cool', 'stir', 'erase', 'obstacle'):
            raise ValueError('Unbekanntes Werkzeug')
    material = None
    if action == 'material':
        material = (number(data, 'density', 1000, 300, 3000),
                    number(data, 'viscosity', .01, .0001, 10),
                    number(data, 'flammability', 0, 0, 1),
                    number(data, 'ignition', 300, 50, 800),
                    number(data, 'cohesion', .05, 0, .15))

    def apply_commands(sim):
        sim.gravity = gravity
        if action == 'scene':
            sim.scene(scene)
        elif action == 'resolution':
            sim.set_resolution(resolution)
        elif action == 'pause':
            sim.paused = not sim.paused
        elif action == 'material':
            if len(sim.materials) >= 32:
                raise ValueError('Maximal 32 Materialien')
            sim.materials.append(Material('Eigenes '+str(len(sim.materials)-3), '#69e8bc',
                                          material[0], material[1], material[2],
                                          material[3], 2500, material[4]))
        if shot:
            if shot['tool'] == 'emit':
                sim.emit(shot['x'], shot['y'], min(shot['kind'], len(sim.materials)-1),
                         shot['radius'], shot['temperature'])
            else:
                sim.interact(shot['tool'], shot['x'], shot['y'], shot['radius'],
                             shot['dx'], shot['dy'])
        if action == 'single':
            was = sim.paused
            sim.paused = False
            sim.advance()
            sim.paused = was
    return apply_commands


def create_server(port=8765):
    engine = Engine()

    class Handler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'                  # keep-alive for 60 polls/s

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
            if self.path == '/api/frame':
                self.respond(engine.poll(), mime='application/octet-stream')
            elif self.path == '/api/state':
                with engine.lock:
                    data = engine.sim.snapshot()
                self.respond(json.dumps(data).encode())
            elif self.path in FILES:
                name, mime = FILES[self.path]
                self.respond((ROOT/'web'/name).read_bytes(), mime=mime)
            else:
                self.respond(b'{}', 404)

        def do_POST(self):
            if self.path != '/api/step':
                self.respond(b'{}', 404)
                return
            # Reject cross-origin browser requests to this local application.
            origin = self.headers.get('Origin')
            if origin and origin != f'http://{self.headers.get("Host")}':
                self.respond(b'{}', 403)
                return
            try:
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 <= size <= 32768:
                    raise ValueError('Ungueltige Anfragegroesse')
                data = json.loads(self.rfile.read(size)) if size else {}
                if not isinstance(data, dict):
                    raise ValueError('JSON-Objekt erwartet')
                if data:
                    engine.submit(build_commands(data))
                self.respond(engine.poll(), mime='application/octet-stream')
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
