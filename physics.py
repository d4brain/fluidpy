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


PRESETS = [
    Material('Wasser', '#35baff', 998, .001, 0, 500, 4180, .07),
    Material('Öl', '#ffbc48', 850, .08, .65, 300, 2000, .035),
    Material('Alkohol', '#c397ff', 789, .0012, 1, 365, 2440, .022),
    Material('Sirup', '#f07185', 1380, 3, 0, 500, 2500, .08),
]

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
        self.obstacles = []
        self.topology += 1

    def set_resolution(self, name):
        if name not in RESOLUTIONS:
            raise ValueError('Unbekannte Auflösung')
        self.resolution = name
        self.spacing = RESOLUTIONS[name]
        self.h = self.spacing*2.5
        self.scene(self.last_scene)

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
        free = max(0, self.limit-len(self.pos))
        if not free:
            return 0
        grid = np.arange(-radius, radius+d/2, d)
        ox, oy = np.meshgrid(grid, grid, indexing='ij')
        p = np.column_stack((ox.ravel()+x, oy.ravel()+y))
        keep = ox.ravel()**2+oy.ravel()**2 <= radius*radius
        keep &= (p[:, 0] >= d/2) & (p[:, 1] >= d/2)
        keep &= (p[:, 0] <= self.width-d/2) & (p[:, 1] <= self.height-d/2)
        p = p[keep]
        for cx, cy, cr in self.obstacles:
            if len(p):
                p = p[np.hypot(p[:, 0]-cx, p[:, 1]-cy) >= cr+d/2]
        if len(p) and len(self.pos):
            # Vectorised overlap rejection against existing particles.
            if cKDTree is not None:
                tree = cKDTree(self.pos, balanced_tree=False, compact_nodes=False)
                p = p[np.array(tree.query_ball_point(p, .88*d, return_length=True)) == 0]
            else:
                gap = np.min(((p[:, None, 0]-self.pos[None, :, 0])**2 +
                              (p[:, None, 1]-self.pos[None, :, 1])**2), axis=1)
                p = p[gap >= (.88*d)**2]
        p = p[:free]
        n = len(p)
        if n:
            self.pos = np.vstack((self.pos, p))
            self.vel = np.vstack((self.vel, np.zeros((n, 2))))
            self.kind = np.r_[self.kind, np.full(n, kind, dtype=int)]
            self.temp = np.r_[self.temp, np.full(n, float(temperature))]
            self.fuel = np.r_[self.fuel, np.ones(n)]
            self.burning = np.r_[self.burning, np.zeros(n, dtype=bool)]
            self.topology += 1
        return n

    def scene(self, name):
        if name not in ('empty', 'dam', 'layers'):
            raise ValueError('Unbekannte Szene')
        self.clear()
        self.last_scene = name
        if name == 'empty':
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

    def packed(self):
        """Particle payload as interleaved float32: x, y, kind, temp, burning."""
        n = len(self.pos)
        out = np.empty((n, 5), dtype=np.float32)
        if n:
            out[:, 0] = self.pos[:, 0]
            out[:, 1] = self.pos[:, 1]
            out[:, 2] = self.kind
            out[:, 3] = self.temp
            out[:, 4] = self.burning
        return out.tobytes()

    def meta(self):
        return {'time': round(self.time, 3), 'paused': self.paused, 'count': len(self.pos),
                'limit': self.limit, 'obstacles': self.obstacles, 'width': self.width,
                'height': self.height, 'spacing': self.spacing, 'resolution': self.resolution,
                'topology': self.topology, 'substeps': self.substeps,
                'materials': [asdict(m) for m in self.materials],
                'hot': int(np.sum(self.burning)),
                'temperature': round(float(np.mean(self.temp)), 1) if len(self.temp) else 20}

    def snapshot(self):
        data = self.meta()
        data['particles'] = np.column_stack((self.pos, self.kind, self.temp,
                                             self.burning.astype(int))).round(4).tolist()
        return data
