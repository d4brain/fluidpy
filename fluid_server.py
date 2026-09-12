"""Local Python simulation and HTML5 interface. No cloud or CDN dependencies.

The solver runs in its own thread and publishes frames; the browser polls the
newest frame and interpolates between the last two. Rendering is therefore no
longer blocked by a solver step, and the particle payload is transferred as raw
float32 instead of JSON.
"""
import argparse
import json
import os
import math
import signal
import socket
import sqlite3
from pathlib import Path
import threading
import time
import webbrowser
from urllib.parse import urlsplit
from sharing import Shares, dump_sim, restore_sim, social_html, ID
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from physics import Simulation, Material, RESOLUTIONS, SCENES, PRESETS, cKDTree

from containers import ASSETS

VERSION = '2.2'
STREAM_SECONDS = 120          # bounded so proxy read timeouts never cut a frame
ROOT = Path(__file__).resolve().parent
FILES = {'/share.js': ('share.js', 'text/javascript'),'/': ('index.html', 'text/html; charset=utf-8'),
         '/style.css': ('style.css', 'text/css'),
         '/app.js': ('app.js', 'text/javascript'),
         '/assets/vessels.json': ('assets/vessels.json', 'application/json'),
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
    sim_step = 1/120       # physics granularity
    publish_step = 1/40    # frames actually sent; the browser interpolates the rest

    def __init__(self):
        self.sim = Simulation()
        self.sim.scene('dam')
        self.lock = threading.Lock()          # guards the simulation itself
        # Input must never wait for a solver step: at 5000 particles a step
        # holds `lock` for ~100 ms, which starved the pointer requests.
        self.inbox = threading.Lock()
        self.commands = []
        self.frame = 0
        self.compute_ms = 0.
        self.interval_ms = 16.
        self.last_poll = 0.
        self.payload = frame_bytes(dict(self.sim.meta(), frame=0, compute_ms=0., interval_ms=16.),
                                   self.sim.packed())
        threading.Thread(target=self.run, daemon=True).start()

    def submit(self, apply_commands):
        with self.inbox:
            if len(self.commands) < 60:        # bound the queue, never block
                self.commands.append(apply_commands)
                return True
            return False

    def poll(self):
        self.last_poll = time.monotonic()
        return self.payload

    def follow(self, seen):
        """Block until a frame newer than `seen` exists, then return it."""
        deadline = time.monotonic()+10
        while True:
            self.last_poll = time.monotonic()
            frame, payload = self.frame, self.payload
            if frame != seen or time.monotonic() > deadline:
                return frame, payload
            time.sleep(.002)

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
            # Bandwidth is particles x frames: sending more than ~40 frames per
            # second buys nothing that the client's interpolation does not
            # already cover. Input is always answered with a fresh frame.
            publish = bool(self.commands) or now-last_frame >= self.publish_step
            with self.inbox:
                pending, self.commands = self.commands, []
            with self.lock:
                start = time.perf_counter()
                for apply_commands in pending:
                    try:
                        apply_commands(self.sim)
                    except (ValueError, TypeError, KeyError, OverflowError):
                        pass
                if step:
                    self.sim.advance(self.sim_step)
                self.compute_ms = .7*self.compute_ms+.3*(time.perf_counter()-start)*1000
                if publish:
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
    if action not in (None, 'scene', 'pause', 'material', 'single', 'resolution', 'container', 'empty_container'):
        raise ValueError('Unbekannte Aktion')
    container = data.get('container')
    if action == 'container' and (not isinstance(container, str) or container not in ASSETS):
        raise ValueError('Unbekanntes Gefäß')
    scene = data.get('scene')
    if action == 'scene' and scene not in SCENES:
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
        elif action == 'container':
            sim.set_container(container)
        elif action == 'empty_container':
            sim.empty_container()
        elif action == 'resolution':
            sim.set_resolution(resolution)
        elif action == 'pause':
            sim.paused = not sim.paused
        elif action == 'material':
            if len(sim.materials) >= 32:
                raise ValueError('Maximal 32 Materialien')
            sim.materials.append(Material('Eigenes '+str(len(sim.materials)-len(PRESETS)+1), '#69e8bc',
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


def create_server(port=8765, host='127.0.0.1', data_dir=None):
    engine = Engine()
    shares = Shares(data_dir)

    class Handler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'
        timeout = 130                                  # outlives one stream window

        def log_message(self, fmt, *args):
            if args and str(args[1] if len(args) > 1 else '') not in ('200', '304'):
                super().log_message(fmt, *args)

        def handle_one_request(self):
            # A reload, a closed tab or a navigation drops the socket while a
            # response is in flight. At tens of polls per second that is normal
            # operation, not an error, so it must not reach the log as a
            # traceback: close the connection and let the thread finish.
            try:
                super().handle_one_request()
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError,
                    TimeoutError, socket.timeout):
                self.close_connection = True

        def respond(self, body, status=200, mime='application/json'):
            try:
                self.send_response(status)
                self.send_header('Content-Type', mime)
                self.send_header('Content-Length', str(len(body)))
                self.send_header('Cache-Control', 'no-store')
                self.send_header('X-Content-Type-Options', 'nosniff')
                self.end_headers()
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                self.close_connection = True

        def stream(self):
            """One long-lived response carrying every new frame as a chunk.

            Steady state costs a single connection instead of dozens of requests
            per second, which is what a reverse proxy in front of this server
            actually copes with. `X-Accel-Buffering: no` stops nginx from
            buffering the response; the client falls back to polling if a proxy
            swallows the stream anyway.
            """
            try:
                self.send_response(200)
                self.send_header('Content-Type', 'application/octet-stream')
                self.send_header('Cache-Control', 'no-store')
                self.send_header('X-Content-Type-Options', 'nosniff')
                self.send_header('X-Accel-Buffering', 'no')
                self.send_header('Transfer-Encoding', 'chunked')
                self.end_headers()
                seen, until = -1, time.monotonic()+STREAM_SECONDS
                while time.monotonic() < until:
                    seen, payload = engine.follow(seen)
                    body = len(payload).to_bytes(4, 'little')+payload
                    self.wfile.write(b'%X\r\n' % len(body)+body+b'\r\n')
                    self.wfile.flush()
                self.wfile.write(b'0\r\n\r\n')          # clean end, client reconnects
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError,
                    TimeoutError, socket.timeout, OSError):
                pass
            self.close_connection = True

        def public_base(self):
            configured=os.environ.get('FLUIDPY_PUBLIC_URL','').rstrip('/')
            if configured:return configured
            host_header=self.headers.get('Host','localhost')
            if not all(c.isalnum() or c in '.:-[]' for c in host_header):raise ValueError('Ungültiger Host')
            hostname=urlsplit('//'+host_header).hostname
            return ('http://' if hostname in ('127.0.0.1','localhost','::1') else 'https://')+host_header

        def do_GET(self):
            route=urlsplit(self.path).path
            if route.startswith('/s/') or route.startswith('/api/shares/'):
                try:
                    parts=route.strip('/').split('/')
                    sid=parts[1] if parts[0]=='s' else parts[2]
                    row=shares.get(sid)
                    if route=='/s/'+sid:
                        body=social_html((ROOT/'web/index.html').read_text(encoding='utf-8'),self.public_base(),sid)
                        self.respond(body.encode(),mime='text/html; charset=utf-8')
                    elif route in ('/s/'+sid+'/preview.png','/s/'+sid+'/post.png','/s/'+sid+'/story.png'):
                        self.respond(row[parts[-1][:-4]],mime='image/png')
                    elif route=='/api/shares/'+sid:
                        import base64
                        self.respond(json.dumps(dict(frame=base64.b64encode(row['frame']).decode(),ui=json.loads(row['ui']))).encode())
                    else:self.respond(b'{}',404)
                except (KeyError,IndexError,ValueError):self.respond(b'{"error":"Freigabe nicht gefunden"}',404)
                except (OSError,sqlite3.Error):self.respond(b'{"error":"Speicher nicht erreichbar"}',503)
                return
            if self.path == '/api/stream':
                self.stream()
            elif self.path == '/api/frame':
                self.respond(engine.poll(), mime='application/octet-stream')
            elif self.path == '/api/health':
                self.respond(json.dumps({'version': VERSION, 'particles': engine.sim.count(),
                                         'frame': engine.frame,
                                         'compute_ms': round(engine.compute_ms, 1),
                                         'bind': f'{host}:{port}',
                                         'neighbours': 'scipy' if cKDTree else 'numpy'}).encode())
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
            if self.path not in ('/api/step','/api/capture','/api/shares','/api/restore'):
                self.respond(b'{}', 404)
                return
            # Reject cross-origin browser requests. Compared without the scheme
            # so the app also works behind a local TLS reverse proxy.
            origin = self.headers.get('Origin')
            if origin and origin.split('://')[-1] != (self.headers.get('Host') or ''):
                self.close_connection=True
                self.respond(b'{}', 403)
                return
            try:
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 <= size <= (9_000_000 if self.path=='/api/shares' else 32768):
                    self.close_connection=True
                    raise ValueError('Ungueltige Anfragegroesse')
                data = json.loads(self.rfile.read(size)) if size else {}
                if not isinstance(data, dict):
                    raise ValueError('JSON-Objekt erwartet')
                if self.path=='/api/capture':
                    ui=data.get('ui',{})
                    if not isinstance(ui,dict):raise ValueError('Ansicht ungültig')
                    ui={k:ui.get(k,v) for k,v in dict(view='fluid',kind=0,radius=6.5,temperature=20).items()}
                    if ui['view'] not in ('fluid','thermal','particles'):raise ValueError('Ansicht ungültig')
                    ui['kind']=int(number(ui,'kind',0,0,31));ui['radius']=number(ui,'radius',6.5,2.5,16);ui['temperature']=number(ui,'temperature',20,0,800)
                    ready=threading.Event();capture={}
                    def take_snapshot(sim):
                        try:
                            meta=dict(sim.meta(),paused=True,frame=engine.frame,compute_ms=0,interval_ms=16)
                            capture.update(shares.capture(dump_sim(sim),frame_bytes(meta,sim.packed()),ui))
                        except ValueError as exc:capture['error']=str(exc)
                        finally:ready.set()
                    if not engine.submit(take_snapshot):raise ValueError('Server ausgelastet. Erneut versuchen.')
                    engine.poll()
                    if not ready.wait(12):raise ValueError('Aufnahme nicht verfügbar. Erneut versuchen.')
                    if 'error' in capture:raise ValueError(capture['error'])
                    capture['url']=self.public_base()+'/s/'+capture['id']
                    self.respond(json.dumps(capture).encode());return
                if self.path=='/api/shares':
                    sid=shares.save(data)
                    self.respond(json.dumps(dict(id=sid,url=self.public_base()+'/s/'+sid)).encode());return
                if self.path=='/api/restore':
                    sid=data.get('id')
                    if not isinstance(sid,str):raise ValueError('Freigabe fehlt')
                    snapshot=json.loads(shares.get(sid)['state'])
                    ready=threading.Event()
                    def load_snapshot(sim):
                        restore_sim(sim,snapshot);ready.set()
                    if not engine.submit(load_snapshot):raise ValueError('Server ausgelastet')
                    engine.poll()
                    if not ready.wait(12):raise ValueError('Laden dauert zu lange. Bitte erneut versuchen.')
                    with engine.lock:pass  # Wait for the restored frame to be published.
                elif data:
                    engine.submit(build_commands(data))
                self.respond(engine.poll(), mime='application/octet-stream')
            except (OSError,sqlite3.Error):
                self.respond(b'{"error":"Freigabespeicher nicht beschreibbar"}',503)
            except (ValueError, TypeError, KeyError, OverflowError) as exc:
                self.respond(json.dumps({'error': str(exc)}).encode(), 400)

    class Server(ThreadingHTTPServer):
        daemon_threads = True
        request_queue_size = 128                       # default 5 is too small here
        allow_reuse_address = True

    return Server((host, port), Handler)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='FluidPy – Python SPH + HTML5')
    # Environment fallbacks: a process manager can change these with a plain
    # restart instead of being recreated with new command-line arguments.
    parser.add_argument('--port', type=int, default=int(os.environ.get('FLUIDPY_PORT', 8765)))
    parser.add_argument('--no-browser', action='store_true')
    parser.add_argument('--host', default=os.environ.get('FLUIDPY_HOST', '127.0.0.1'),
                        help='Bindeadresse. Standard 127.0.0.1; alles andere macht die '
                             'Simulation ohne Authentifizierung im Netz erreichbar.')
    args = parser.parse_args()
    try:
        server = create_server(args.port, args.host)
    except OSError as exc:
        parser.exit(1, f'Port {args.port} nicht verfuegbar: {exc}\nTipp: --port 8766\n')
    port = server.server_port
    url = f'http://{"127.0.0.1" if args.host in ("0.0.0.0", "::") else args.host}:{port}'
    local_only = args.host in ('127.0.0.1', 'localhost', '::1')
    # The bind address decides whether a reverse proxy in a container can reach
    # this process at all, so say it plainly instead of always printing loopback.
    print(f'FluidPy {VERSION}: {url}', flush=True)
    print(f'Bindung: {args.host}:{port} · '
          + ('nur lokal, aus einem Docker-Container NICHT erreichbar'
             if local_only else 'auf allen Adressen erreichbar, Firewall beachten')
          + ' · Nachbarsuche: ' + ('SciPy' if cKDTree else 'NumPy-Gitter')
          + '\nBeenden: Strg+C', flush=True)
    if not args.no_browser:
        webbrowser.open(url)
    # Container stop sends SIGTERM: shut the listener down from another thread
    # so the process exits cleanly instead of waiting out the grace period.
    signal.signal(signal.SIGTERM,
                  lambda *_: threading.Thread(target=server.shutdown, daemon=True).start())
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
