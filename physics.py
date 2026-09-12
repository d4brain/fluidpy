"""2D weakly-compressible, volume-based multiphase SPH, SI units.

Equal reference volumes, unequal masses; symmetric pair forces conserve momentum.
Combustion, cohesion and thermal diffusivity are explicitly reduced models.

Performance notes: the solver keeps particle state in contiguous 1-D arrays
during a step (structure of arrays), rebuilds the neighbour list once per
substep and caches every pair coefficient that depends only on the material
pair. Neighbour search uses SciPy when available and a vectorised uniform grid
otherwise; the previous Python-level cell loop is gone.
"""
from dataclasses import dataclass, asdict
import math
import numpy as np
from containers import ASSETS, outlines, boundary, collide

try:
    from scipy.spatial import cKDTree
except ImportError:
    cKDTree = None


@dataclass
class Material:
    name: str
    color: str
    density: float
    viscosity: float
    flammability: float
    ignition: float
    heat_capacity: float
    cohesion: float
    # Radiuswachstum eines Aetzlochs in m/s bei 20 C. 0 = greift nichts an.
    corrosion: float = 0.
    group: str = 'Flüssigkeiten'
    render: str = "fluid"
    selectable: bool = True
    description: str = ""


PRESETS = [
    Material('Wasser', '#35baff', 998, .001, 0, 500, 4180, .07),
    Material('Öl', '#ffbc48', 850, .08, .65, 300, 2000, .035),
    Material('Alkohol', '#c397ff', 789, .0012, 1, 365, 2440, .022),
    Material('Sirup', '#f07185', 1380, 3, 0, 500, 2500, .08),
    Material('Durchfall', '#927132', 1030, .035, 0, 500, 3800, .025,
             group='Ekliges', description='Dünnflüssig, braun und leicht zäh.'),
    Material('Kot-Klumpen', '#65412b', 1080, 4, 0, 500, 2400, .12,
             group='Ekliges', render='solid',
             description='Zusammenhängende Klumpen, die fallen und sich drehen.'),
    Material('Erbrochenes', '#a6a044', 1020, .18, 0, 500, 3600, .045,
             group='Ekliges', description='Zähe Flüssigkeit mit orangefarbenen Speisestückchen.'),
    Material('Buchstabensuppe', '#ba5825', 1005, .008, 0, 500, 4000, .025,
             group='Ekliges', description='Rote Brühe mit hellen Nudelbuchstaben A, E, F, H, L, O, P, U.'),
    Material('Speisestückchen', '#e9ab66', 1060, 1.5, 0, 500, 2800, .10,
             group='Ekliges', render='solid', selectable=False),
    Material('Buchstabennudeln', '#ffe4a0', 1040, .8, 0, 500, 2800, .10,
             group='Ekliges', render='solid', selectable=False),
    # ------------------------------------------------------------- Getränke
    Material('Kaffee', '#4b2a17', 1002, .0013, 0, 500, 4050, .062,
             group='Getränke',
             description='Heisser schwarzer Kaffee, kaum dicker als Wasser.'),
    Material('Cola', '#2d150c', 1044, .0017, 0, 500, 3800, .055,
             group='Getränke',
             description='Gezuckert, dadurch etwas dichter und zäher als Wasser.'),
    # --------------------------------------------------------------- Säuren
    # corrosion ist ein Spielparameter, keine kalibrierte Korrosionsrate. Die
    # Rangfolge folgt aber dem, was die Stoffe real mit Glas, Keramik und
    # Metall anstellen: Flusssäure frisst Glas, Blausäure praktisch nichts.
    Material('Schwefelsäure', '#d9cf62', 1830, .0248, 0, 500, 1380, .075,
             corrosion=.012, group='Säuren',
             description='96 %, ölig und sehr dicht. Frisst Löcher und wird beim '
                         'Erhitzen deutlich schneller.'),
    Material('Salzsäure', '#a8e6b4', 1180, .0019, 0, 500, 2550, .058,
             corrosion=.008, group='Säuren',
             description='37 %, dünnflüssig. Greift Metall und Kalk an, Glas kaum.'),
    Material('Salpetersäure', '#f2c266', 1510, .00092, 0, 500, 1720, .050,
             corrosion=.011, group='Säuren',
             description='Rauchend, gelblich. Ätzt zügig durch die Gefässwand.'),
    Material('Flusssäure', '#bfe9ff', 1150, .00098, 0, 500, 2500, .048,
             corrosion=.020, group='Säuren',
             description='Löst als einzige Säure Glas und Keramik. Hier die '
                         'aggressivste Flüssigkeit im Becken.'),
    Material('Königswasser', '#e8863c', 1210, .0011, 0, 500, 2300, .052,
             corrosion=.016, group='Säuren',
             description='Salzsäure und Salpetersäure 3:1, löst sogar Gold.'),
    Material('Blausäure', '#cfe4d8', 687, .00018, 0, 500, 2610, .030,
             corrosion=.0004, group='Säuren',
             description='Berüchtigt, aber chemisch eine sehr schwache Säure: '
                         'sie greift die Gefässe fast nicht an.'),
    Material('Natronlauge', '#9fb9ff', 1525, .0042, 0, 500, 3100, .066,
             corrosion=.006, group='Säuren',
             description='Keine Säure, sondern Lauge — ätzt trotzdem, '
                         'besonders Aluminium und Glas.'),
]

INDEX = {m.name: i for i, m in enumerate(PRESETS)}
CLUMP, VOMIT, SOUP = INDEX['Kot-Klumpen'], INDEX['Erbrochenes'], INDEX['Buchstabensuppe']
CHUNK, NOODLE = INDEX['Speisestückchen'], INDEX['Buchstabennudeln']

# Ätzlöcher: Kreise, in denen die Gefässwand weg ist. Sie halten die Kollision
# und die Darstellung auf demselben Stand, ohne die Polygone neu zu vernetzen.
MAX_HOLES = 32
HOLE_START = .004          # frischer Ätzpunkt, noch dicht
HOLE_SPACING = .10         # Mindestabstand zwischen zwei Ätzstellen
HOLE_MAX = .075
# Bis hierhin ist die Mulde nur eine Delle in der Wandstärke; erst darüber
# geht sie durch und lässt Flüssigkeit hindurch.
HOLE_OPEN = .018
NEW_SPOT_CHANCE = .08      # Fraß breitet sich aus, statt überall zugleich zu starten

SCENES = ('empty', 'dam', 'layers', 'diarrhea', 'clumps', 'vomit', 'soup')
# Particle silhouettes; connected strokes stay together through shape matching.
LETTERS = ('010/101/111/101/101', '111/100/110/100/111',
           '111/100/110/100/100', '101/101/111/101/101',
           '100/100/100/100/111', '111/101/101/101/111',
           '110/101/110/100/100', '101/101/101/101/111')

# Resolution presets: particle spacing in metres, support radius factor 2.5.
RESOLUTIONS = {'fein': .015, 'mittel': .020, 'grob': .026}


class Simulation:
    width, height = 1.8, 1.1
    sound_speed = 15.
    limit = 5000
    # Upper bound on substeps per advance() so a single request cannot stall
    # the server for seconds. Exceeding it slows simulated time, never reality.
    max_substeps = 40

    def __init__(self):
        self.materials = list(PRESETS)
        self.rng = np.random.default_rng(12)
        self.gravity = 9.81
        self.time = 0.
        self.paused = False
        self.obstacles = []
        self.topology = 0
        self.last_scene = 'empty'
        self.resolution = 'fein'
        self.spacing = RESOLUTIONS['fein']
        self.h = self.spacing*2.5
        self.substeps = 0
        self.clear()

    # ---------------------------------------------------------------- state

    def clear(self):
        self.pos = np.empty((0, 2))
        self.vel = np.empty((0, 2))
        self.kind = np.empty(0, dtype=int)
        self.temp = np.empty(0)
        self.fuel = np.empty(0)
        self.burning = np.empty(0, dtype=bool)
        self.time = 0.
        self.groups = []
        self.letter_index = 0
        self.obstacles = []
        self.container = None
        self.container_polygons = []
        self.holes = []
        self.topology += 1

    def set_resolution(self, name):
        if name not in RESOLUTIONS:
            raise ValueError('Unbekannte Auflösung')
        self.resolution = name
        self.spacing = RESOLUTIONS[name]
        self.h = self.spacing*2.5
        container = self.container
        self.scene(self.last_scene)
        if container:
            self.set_container(container)

    def set_container(self, key):
        if key not in ASSETS:
            raise ValueError('Unbekanntes Gefäß')
        self.clear()
        self.last_scene = 'empty'
        self.container = key
        self.container_polygons = outlines(key)

    def empty_container(self):
        key = self.container
        if key:
            self.set_container(key)
        else:
            self.scene('empty')

    def open_holes(self):
        """Nur die Ätzstellen, die schon ganz durch die Wand gehen."""
        return [[x, y, r-HOLE_OPEN] for x, y, r in self.holes if r > HOLE_OPEN]

    def _in_holes(self, points):
        """Maske: Punkte, an denen die Gefässwand bereits durchgefressen ist."""
        holes = self.open_holes()
        if not holes or not len(points):
            return np.zeros(len(points), dtype=bool)
        h = np.asarray(holes, dtype=float)
        return (np.hypot(points[:, None, 0]-h[None, :, 0],
                         points[:, None, 1]-h[None, :, 1]) < h[None, :, 2]).any(axis=1)

    def _corrode(self, duration):
        """Säuren fressen Löcher in Gefässwand und Hindernisse.

        Ein Loch ist ein Kreis auf der Wand: die Kollision lässt Partikel dort
        durch, der Shader schneidet dieselbe Scheibe aus dem Gefäss heraus.
        Warme Säure ätzt schneller, gedeckelt bei dreifachem Tempo.
        """
        if not len(self.pos) or not (self.container_polygons or self.obstacles):
            return
        rate = np.array([m.corrosion for m in self.materials])[self.kind]
        active = rate > 0
        if not active.any():
            return
        pts = self.pos[active]
        strength = rate[active]*(1.+np.clip(self.temp[active]-20., 0, 300)/150.)
        contact = self.spacing*1.4
        peak = float(strength.max())
        for polygon in self.container_polygons:
            lo, hi = polygon.min(axis=0)-contact, polygon.max(axis=0)+contact
            near_box = np.flatnonzero((pts[:, 0] >= lo[0]) & (pts[:, 0] <= hi[0]) &
                                      (pts[:, 1] >= lo[1]) & (pts[:, 1] <= hi[1]))
            if not len(near_box):
                continue
            distance, q, _ = boundary(pts[near_box], polygon)
            touch = distance < contact
            if not touch.any():
                continue
            self._etch(q[touch], strength[near_box][touch]*duration, contact, peak*duration)
        for k in range(len(self.obstacles)-1, -1, -1):
            cx, cy, cr = self.obstacles[k]
            gap = np.hypot(pts[:, 0]-cx, pts[:, 1]-cy)-cr
            hit = (gap > -contact) & (gap < contact)
            if not hit.any():
                continue
            cr -= duration*float(strength[hit].max())*1.6
            if cr <= self.spacing:
                self.obstacles.pop(k)
            else:
                self.obstacles[k][2] = cr

    def _etch(self, points, amount, contact, cap):
        """Vorhandene Löcher vergrössern, sonst einen neuen Ätzpunkt setzen."""
        fresh = np.ones(len(points), dtype=bool)
        if self.holes:
            h = np.asarray(self.holes, dtype=float)
            gap = (np.hypot(points[:, None, 0]-h[None, :, 0],
                            points[:, None, 1]-h[None, :, 1])-h[None, :, 2])
            nearest = np.argmin(gap, axis=1)
            known = gap[np.arange(len(points)), nearest] < contact
            fresh = ~known
            if known.any():
                # Deckel pro Bild: viel Säure ätzt breiter, nicht schlagartig tiefer.
                grown = np.minimum(np.bincount(nearest[known], amount[known],
                                               minlength=len(h)), cap)
                h[:, 2] = np.minimum(h[:, 2]+grown, HOLE_MAX)
                self.holes = h.tolist()
        # Höchstens eine neue Stelle pro Aufruf und nur gelegentlich: der Frass
        # wandert dadurch über die Wand, statt sie sofort gleichmässig zu lochen.
        if len(self.holes) >= MAX_HOLES or not fresh.any() or self.rng.random() > NEW_SPOT_CHANCE:
            return
        for point in points[fresh]:
            if self.holes:
                h = np.asarray(self.holes, dtype=float)
                if float(np.min(np.hypot(h[:, 0]-point[0], h[:, 1]-point[1])-h[:, 2])) < HOLE_SPACING:
                    continue
            self.holes.append([float(point[0]), float(point[1]), HOLE_START])
            return

    def _properties(self):
        self.rho0 = np.array([m.density for m in self.materials])[self.kind]
        self.mu = np.array([m.viscosity for m in self.materials])[self.kind]
        self.cp = np.array([m.heat_capacity for m in self.materials])[self.kind]
        self.flash = np.array([m.ignition for m in self.materials])[self.kind]
        self.flame = np.array([m.flammability for m in self.materials])[self.kind]
        self.sigma = np.array([m.cohesion for m in self.materials])[self.kind]
        self.mass = self.rho0 * self.spacing**2
        self.inv_mass = 1./self.mass
        self.capacity = self.mass*self.cp
        self.k_eos = self.rho0*self.sound_speed**2/7

    def _pair_tables(self):
        """Pair coefficients depend only on the two material kinds: cache K×K."""
        k = len(self.materials)
        rho = np.array([m.density for m in self.materials])
        mu = np.array([m.viscosity for m in self.materials])
        cp = np.array([m.heat_capacity for m in self.materials])
        sig = np.array([m.cohesion for m in self.materials])
        mass = rho*self.spacing**2
        cap = mass*cp
        a, b = np.meshgrid(np.arange(k), np.arange(k), indexing='ij')
        same = np.where(a == b, 1., .2)
        self._t_art = (2*mass[a]*mass[b]/(rho[a]+rho[b])).ravel()
        self._t_mu = (2*mu[a]*mu[b]/np.maximum(mu[a]+mu[b], 1e-12)).ravel()
        self._t_coh = (np.sqrt(sig[a]*sig[b])*same).ravel()
        self._t_heat = (.9*cap[a]*cap[b]/(cap[a]+cap[b])).ravel()
        self._kinds = k
        # Single-material scenes (the common case) need no per-pair gathers.
        self._uniform = int(self.kind[0]) if len(self.kind) and (self.kind == self.kind[0]).all() else -1

    # ------------------------------------------------------------ authoring

    def emit(self, x, y, kind=0, radius=.065, temperature=20):
        if not 0 <= kind < len(self.materials):
            raise ValueError('Unbekanntes Material')
        d = self.spacing
        if kind == CLUMP:
            # One compact oval per brush application, independent of liquid grid.
            r = min(radius, .06)
            grid = np.arange(-r, r+d/2, d)
            gx, gy = np.meshgrid(grid, grid)
            mask = (gx/r)**2+(gy/(r*.75))**2 <= 1
            return self._append(np.column_stack((gx[mask]+x, gy[mask]+y)),
                                kind, temperature, solid=True)
        added = 0
        if kind in (VOMIT, SOUP):
            if kind == SOUP:
                glyph = LETTERS[self.letter_index % len(LETTERS)].split('/')
                offsets = np.array([(col-1, 2-row) for row, line in enumerate(glyph)
                                    for col, value in enumerate(line) if value == '1'])
                ingredient = NOODLE
            else:
                offsets = np.array([[-.5, -.5], [.5, -.5], [-.5, .5], [.5, .5]])
                ingredient = CHUNK
            angle = self.rng.uniform(-.65, .65)
            rotation = np.array([[np.cos(angle), -np.sin(angle)],
                                 [np.sin(angle), np.cos(angle)]])
            pts = offsets @ rotation.T*d + [x, y]
            added = self._append(pts, ingredient, temperature, solid=True)
            if added and kind == SOUP:
                self.letter_index += 1
            # Leave space around the inclusion; even the smallest brush emits broth.
            radius = max(radius, 3.2*d if kind == SOUP else 2*d)
        grid = np.arange(-radius, radius+d/2, d)
        ox, oy = np.meshgrid(grid, grid, indexing='ij')
        keep = ox.ravel()**2+oy.ravel()**2 <= radius*radius
        p = np.column_stack((ox.ravel()[keep]+x, oy.ravel()[keep]+y))
        return added + self._append(p, kind, temperature)

    def _append(self, p, kind, temperature, solid=False):
        d = self.spacing
        free = max(0, self.limit-len(self.pos))
        if not free or not len(p):
            return 0
        expected = len(p)
        keep = ((p >= d/2) & (p <= [self.width-d/2, self.height-d/2])).all(axis=1)
        p = p[keep]
        for cx, cy, cr in self.obstacles:
            if len(p):
                p = p[np.hypot(p[:, 0]-cx, p[:, 1]-cy) >= cr+d/2]
        for polygon in self.container_polygons:
            if len(p):
                p = p[(boundary(p, polygon)[0] >= d/2) | self._in_holes(p)]
        if len(p) and len(self.pos):
            # Vectorised overlap rejection against existing particles.
            if cKDTree is not None:
                tree = cKDTree(self.pos, balanced_tree=False, compact_nodes=False)
                p = p[np.array(tree.query_ball_point(p, .88*d, return_length=True)) == 0]
            else:
                gap = np.min(((p[:, None, 0]-self.pos[None, :, 0])**2 +
                              (p[:, None, 1]-self.pos[None, :, 1])**2), axis=1)
                p = p[gap >= (.88*d)**2]
        # Reject incomplete solids instead of clipping letters at walls/obstacles.
        if solid and (len(p) != expected or len(p) > free):
            return 0
        p = p[:free]
        n = len(p)
        if n:
            if solid:
                ids = np.arange(len(self.pos), len(self.pos)+n)
                self.groups.append((ids, p-p.mean(axis=0)))
            self.pos = np.vstack((self.pos, p))
            self.vel = np.vstack((self.vel, np.zeros((n, 2))))
            self.kind = np.r_[self.kind, np.full(n, kind, dtype=int)]
            self.temp = np.r_[self.temp, np.full(n, float(temperature))]
            self.fuel = np.r_[self.fuel, np.ones(n)]
            self.burning = np.r_[self.burning, np.zeros(n, dtype=bool)]
            self.topology += 1
        return n

    def scene(self, name):
        if name not in SCENES:
            raise ValueError('Unbekannte Szene')
        self.clear()
        self.last_scene = name
        if name == 'empty':
            return
        if name in ('diarrhea', 'clumps', 'vomit', 'soup'):
            kind = {'diarrhea': INDEX['Durchfall'], 'clumps': CLUMP,
                    'vomit': VOMIT, 'soup': SOUP}[name]
            for y in (.27, .45, .63):
                for x in np.linspace(.24, 1.56, 8):
                    self.emit(x, y, kind, .075)
            return
        d = self.spacing
        ys = np.arange(.025, .60, d)
        xs = np.arange(.035, .51 if name == 'dam' else 1.765, d)
        gx, gy = np.meshgrid(xs, ys, indexing='xy')
        pts = np.column_stack((gx.ravel(), gy.ravel()))[:self.limit]
        self.pos = pts
        self.kind = np.zeros(len(pts), dtype=int) if name == 'dam' else (pts[:, 1] >= .30).astype(int)
        self.vel = np.zeros_like(pts)
        self.temp = np.full(len(pts), 20.)
        self.fuel = np.ones(len(pts))
        self.burning = np.zeros(len(pts), dtype=bool)
        self.topology += 1

    # ----------------------------------------------------- neighbour search

    def pairs(self, x=None, y=None):
        if x is None:
            x = np.ascontiguousarray(self.pos[:, 0])
            y = np.ascontiguousarray(self.pos[:, 1])
        n = x.size
        if n < 2:
            return np.empty(0, dtype=np.intp), np.empty(0, dtype=np.intp)
        h = self.h
        if cKDTree is not None:
            # Unbalanced build is roughly twice as fast and enough for a near
            # uniform point set; the query result is identical.
            tree = cKDTree(np.column_stack((x, y)), balanced_tree=False, compact_nodes=False)
            ij = tree.query_pairs(h, output_type='ndarray')
            return np.ascontiguousarray(ij[:, 0]), np.ascontiguousarray(ij[:, 1])
        # Vectorised uniform grid: bucket sort, then five cell offsets.
        inv = 1./h
        nx, ny = int(self.width*inv)+3, int(self.height*inv)+3
        gx = np.clip((x*inv).astype(np.int32), 0, nx-3)+1
        gy = np.clip((y*inv).astype(np.int32), 0, ny-3)+1
        cell = gy*nx+gx
        order = np.argsort(cell, kind='stable').astype(np.int32)
        sc = cell[order]
        counts = np.bincount(sc, minlength=nx*ny)
        width = int(counts.max())
        start = np.zeros(nx*ny, dtype=np.int64)
        np.cumsum(counts[:-1], out=start[1:])
        rank = np.arange(n, dtype=np.int64)-start[sc]
        table = np.full((nx*ny, width), -1, dtype=np.int32)
        table[sc, rank] = order
        self_index = np.arange(n, dtype=np.int32)[:, None]
        a_parts, b_parts = [], []
        for offset in (0, 1, nx-1, nx, nx+1):
            nb = table[cell+offset] if offset else np.where(table[cell] > self_index, table[cell], -1)
            rows, cols = np.nonzero(nb >= 0)
            a_parts.append(rows.astype(np.int32))
            b_parts.append(nb[rows, cols])
        a = np.concatenate(a_parts)
        b = np.concatenate(b_parts)
        dx = x[a]-x[b]
        dy = y[a]-y[b]
        near = dx*dx+dy*dy < h*h
        return a[near], b[near]

    # --------------------------------------------------------- interaction

    def interact(self, tool, x, y, radius, dx=0, dy=0):
        if tool == 'obstacle':
            if len(self.obstacles) < 30:
                self.obstacles.append([x, y, radius])
            return
        if not len(self.pos):
            return
        distance = np.hypot(self.pos[:, 0]-x, self.pos[:, 1]-y)
        w = np.maximum(0, 1-distance/radius)
        if tool == 'heat':
            self.temp += w*110
        elif tool == 'cool':
            self.temp = np.maximum(0, self.temp-w*100)
        elif tool == 'stir':
            self.vel += w[:, None]*np.clip([dx, dy], -2, 2)*3
        elif tool == 'erase':
            keep = distance > radius
            if not keep.all():
                remap = np.cumsum(keep)-1
                groups = []
                for ids, rest in self.groups:
                    survive = keep[ids]
                    if survive.sum() > 1:
                        shape = rest[survive]
                        groups.append((remap[ids[survive]], shape-shape.mean(axis=0)))
                self.groups = groups
                for attr in ('pos', 'vel', 'kind', 'temp', 'fuel', 'burning'):
                    setattr(self, attr, getattr(self, attr)[keep])
                self.topology += 1

    # ------------------------------------------------------------- solver

    def advance(self, duration=1/60):
        if self.paused or not len(self.pos):
            self.substeps = 0
            return
        self._properties()
        self._pair_tables()
        # Contiguous structure-of-arrays view for the whole advance.
        x = np.ascontiguousarray(self.pos[:, 0])
        y = np.ascontiguousarray(self.pos[:, 1])
        vx = np.ascontiguousarray(self.vel[:, 0])
        vy = np.ascontiguousarray(self.vel[:, 1])
        remaining, taken = duration, 0
        while remaining > 1e-9 and taken < self.max_substeps:
            vmax = math.sqrt(float(np.max(vx*vx+vy*vy))) if x.size else 0.
            nu = float(np.max(self.mu/self.rho0))
            dt = min(remaining, .22*self.h/(self.sound_speed+vmax), .12*self.h**2/max(nu, 1e-8))
            self._step(dt, x, y, vx, vy)
            self.time += dt
            remaining -= dt
            taken += 1
        self.substeps = taken
        self.pos = np.column_stack((x, y))
        self.vel = np.column_stack((vx, vy))
        self._corrode(duration)

    def _step(self, dt, x, y, vx, vy):
        n = x.size
        h, volume = self.h, self.spacing**2
        i, j = self.pairs(x, y)
        norm = 7/(math.pi*h*h)              # 2D Wendland C2 over support radius h
        inv_h = 1./h
        # Cached pair coefficients, indexed by the material pair; a scene with a
        # single material collapses them to scalars and skips four gathers.
        if self._uniform >= 0:
            same = self._uniform*self._kinds+self._uniform
            c_art, c_heat = self._t_art[same], self._t_heat[same]
            c_mu = self._t_mu[same]*(40*norm*inv_h*inv_h)
            c_coh = self._t_coh[same]*(volume*inv_h)
        else:
            pair_type = self.kind[i]*self._kinds+self.kind[j]
            c_art = self._t_art[pair_type]
            c_mu = self._t_mu[pair_type]*(40*norm*inv_h*inv_h)
            c_coh = self._t_coh[pair_type]*(volume*inv_h)
            c_heat = self._t_heat[pair_type]
        dx = x[i]-x[j]
        dy = y[i]-y[j]
        r2 = dx*dx
        r2 += dy*dy
        np.maximum(r2, 1e-16, out=r2)
        r = np.sqrt(r2)
        q = 1.-r*inv_h
        np.maximum(q, 0, out=q)
        q2 = q*q
        q3 = q2*q
        w = (q2*q2)*(norm*volume)*(1.+(4.*inv_h)*r)
        theta = np.full(n, volume*norm)
        theta += np.bincount(i, w, minlength=n)
        theta += np.bincount(j, w, minlength=n)
        t3 = theta*theta*theta
        pressure = self.k_eos*np.maximum(t3*t3*theta-1., 0)
        effective_v = volume/np.maximum(theta, .65)
        volumes = effective_v[i]*effective_v[j]
        # |∇W| factor: the original ∇W = -grad·delta, and every radial term below
        # carries a leading minus, so the two signs cancel into +grad.
        grad = (20*norm*inv_h*inv_h)*q3
        dvx = vx[i]-vx[j]
        dvy = vy[i]-vy[j]
        # Monaghan artificial viscosity damps approaching acoustic modes. This
        # numerical dissipation is separate from the material's dynamic viscosity.
        approach = dvx*dx
        approach += dvy*dy
        np.minimum(approach, 0, out=approach)
        radial = volumes*(pressure[i]+pressure[j])
        radial += c_art*((-.12*self.sound_speed*h)*approach/(r2+.01*h*h))
        radial *= grad
        # Reduced cohesion. Unlike-material cohesion is lower (immiscibility proxy).
        radial -= c_coh*(q3/r)
        # Symmetric physical viscosity; conservative pair exchange.
        shear = (c_mu*q3)*volumes
        fx = radial*dx
        fx -= shear*dvx
        fy = radial*dy
        fy -= shear*dvy
        ax = (np.bincount(i, fx, minlength=n)-np.bincount(j, fx, minlength=n))*self.inv_mass
        ay = (np.bincount(i, fy, minlength=n)-np.bincount(j, fy, minlength=n))*self.inv_mass
        vx += dt*ax
        vy += dt*(ay-self.gravity)
        x += dt*vx
        y += dt*vy
        # Reduced rigid inclusions: project each particle group onto its closest
        # rotated rest shape. Equal masses within a group preserve its centroid.
        # Fluid pressure/drag, tools and gravity still act on every member.
        for ids, rest in self.groups:
            current = np.column_stack((x[ids], y[ids]))
            center = current.mean(axis=0)
            local = current-center
            cosine = np.sum(rest*local)
            sine = np.sum(rest[:, 0]*local[:, 1]-rest[:, 1]*local[:, 0])
            angle = math.atan2(sine, cosine)
            c, s = math.cos(angle), math.sin(angle)
            target = rest @ np.array([[c, s], [-s, c]]) + center
            correction = (target-current)/dt
            vx[ids] += correction[:, 0]
            vy[ids] += correction[:, 1]
            x[ids], y[ids] = target[:, 0], target[:, 1]
        # Insulated walls mechanically: no penetration, dissipative impact.
        margin = self.spacing*.45
        for axis, vaxis, upper in ((x, vx, self.width), (y, vy, self.height)):
            low = axis < margin
            high = axis > upper-margin
            np.clip(axis, margin, upper-margin, out=axis)
            vaxis[low & (vaxis < 0)] *= -.08
            vaxis[high & (vaxis > 0)] *= -.08
        for cx, cy, radius in self.obstacles:
            ox = x-cx
            oy = y-cy
            dist = np.hypot(ox, oy)
            inside = dist < radius+margin
            if not inside.any():
                continue
            safe = np.maximum(dist, 1e-9)
            nxs = ox/safe
            nys = oy/safe
            degenerate = dist < 1e-9
            nxs[degenerate] = 0.
            nys[degenerate] = 1.
            x[inside] = cx+nxs[inside]*(radius+margin)
            y[inside] = cy+nys[inside]*(radius+margin)
            speed = vx*nxs+vy*nys
            hit = inside & (speed < 0)
            vx[hit] -= 1.08*speed[hit]*nxs[hit]
            vy[hit] -= 1.08*speed[hit]*nys[hit]
        collide(x, y, vx, vy, self.container_polygons, margin, self.open_holes())
        # Accelerated effective heat diffusion, equal and opposite energy exchange.
        heat = (c_heat*q2)*(self.temp[j]-self.temp[i])*dt
        energy = np.bincount(i, heat, minlength=n)-np.bincount(j, heat, minlength=n)
        self.temp += energy/self.capacity
        # Burning is restricted to approximately exposed particles (oxygen proxy).
        exposed = theta < .91
        self.burning = (self.flame > 0) & (self.temp >= self.flash) & (self.fuel > 0) & exposed
        consumed = np.minimum(self.fuel, self.burning*self.flame*dt*.22)
        self.fuel -= consumed
        self.temp += consumed*2e6/self.cp
        self.temp += (20-self.temp)*dt*.12
        self.temp = np.clip(self.temp, 0, 1600)

    # ------------------------------------------------------------- output

    def count(self):
        return len(self.pos)

    # Wire format: 8 bytes per particle instead of 20 floats-as-float32.
    # x, y and temperature are quantised to uint16, which is far finer than the
    # particle spacing (27 µm over 1.8 m) and invisible after interpolation.
    STRIDE = 8
    TEMP_SCALE = 40.            # 0 … 1638 °C in 0.025 °C steps

    def packed(self):
        """Particle payload: uint16 x, uint16 y, uint16 temp, uint8 kind, uint8 burning."""
        n = len(self.pos)
        out = np.zeros((n, self.STRIDE), dtype=np.uint8)
        if n:
            shorts = out.view(np.uint16).reshape(n, self.STRIDE//2)
            shorts[:, 0] = np.clip(self.pos[:, 0]*(65535/self.width), 0, 65535)
            shorts[:, 1] = np.clip(self.pos[:, 1]*(65535/self.height), 0, 65535)
            shorts[:, 2] = np.clip(self.temp*self.TEMP_SCALE, 0, 65535)
            out[:, 6] = np.minimum(self.kind, 255)
            out[:, 7] = self.burning*255
        return out.tobytes()

    def meta(self):
        return {'time': round(self.time, 3), 'gravity': self.gravity, 'paused': self.paused, 'count': len(self.pos),
                'container': self.container, 'limit': self.limit, 'obstacles': self.obstacles,
                'holes': [[round(v, 4) for v in hole] for hole in self.holes],
                'holes_open': len(self.open_holes()), 'width': self.width,
                'height': self.height, 'spacing': self.spacing, 'resolution': self.resolution,
                'topology': self.topology, 'substeps': self.substeps, 'stride': self.STRIDE,
                'materials': [asdict(m) for m in self.materials],
                'hot': int(np.sum(self.burning)),
                'temperature': round(float(np.mean(self.temp)), 1) if len(self.temp) else 20}

    def snapshot(self):
        data = self.meta()
        data['particles'] = np.column_stack((self.pos, self.kind, self.temp,
                                             self.burning.astype(int))).round(4).tolist()
        return data
