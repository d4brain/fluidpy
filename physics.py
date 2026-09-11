"""2D weakly-compressible, volume-based multiphase SPH, SI units.

Equal reference volumes, unequal masses; symmetric pair forces conserve momentum.
Combustion, cohesion and thermal diffusivity are explicitly reduced models.
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


class Simulation:
    width, height = 1.8, 1.1
    spacing, h, sound_speed = .015, .0375, 15.
    limit = 5000

    def __init__(self):
        self.materials = list(PRESETS)
        self.rng = np.random.default_rng(12)
        self.gravity = 9.81
        self.time = 0.
        self.paused = False
        self.obstacles = []
        self.clear()

    def clear(self):
        self.pos = np.empty((0, 2))
        self.vel = np.empty((0, 2))
        self.kind = np.empty(0, dtype=int)
        self.temp = np.empty(0)
        self.fuel = np.empty(0)
        self.burning = np.empty(0, dtype=bool)
        self.time = 0.
        self.obstacles = []

    def _properties(self):
        self.rho0 = np.array([m.density for m in self.materials])[self.kind]
        self.mu = np.array([m.viscosity for m in self.materials])[self.kind]
        self.cp = np.array([m.heat_capacity for m in self.materials])[self.kind]
        self.flash = np.array([m.ignition for m in self.materials])[self.kind]
        self.flame = np.array([m.flammability for m in self.materials])[self.kind]
        self.sigma = np.array([m.cohesion for m in self.materials])[self.kind]
        self.mass = self.rho0 * self.spacing**2

    def emit(self, x, y, kind=0, radius=.065, temperature=20):
        if not 0 <= kind < len(self.materials):
            raise ValueError('Unbekanntes Material')
        points = []
        d = self.spacing
        for ox in np.arange(-radius, radius + d / 2, d):
            for oy in np.arange(-radius, radius + d / 2, d):
                if ox*ox + oy*oy > radius*radius:
                    continue
                p = np.array([x+ox, y+oy])
                if np.any(p < d/2) or p[0] > self.width-d/2 or p[1] > self.height-d/2:
                    continue
                if any(np.linalg.norm(p-np.array(o[:2])) < o[2]+d/2 for o in self.obstacles):
                    continue
                if len(self.pos) and np.min(np.sum((self.pos-p)**2, axis=1)) < (.88*d)**2:
                    continue
                points.append(p)
        points = points[:max(0, self.limit-len(self.pos))]
        if points:
            n = len(points)
            self.pos = np.vstack((self.pos, points))
            self.vel = np.vstack((self.vel, np.zeros((n, 2))))
            self.kind = np.r_[self.kind, np.full(n, kind, dtype=int)]
            self.temp = np.r_[self.temp, np.full(n, temperature)]
            self.fuel = np.r_[self.fuel, np.ones(n)]
            self.burning = np.r_[self.burning, np.zeros(n, dtype=bool)]
        return len(points)

    def scene(self, name):
        self.clear()
        if name == 'empty':
            return
        if name not in ('dam', 'layers'):
            raise ValueError('Unbekannte Szene')
        pts, kinds = [], []
        for y in np.arange(.025, .60, self.spacing):
            for x in np.arange(.035, .51 if name == 'dam' else 1.765, self.spacing):
                pts.append([x, y])
                kinds.append(0 if name == 'dam' or y < .30 else 1)
        self.pos = np.array(pts)
        self.kind = np.array(kinds)
        self.vel = np.zeros_like(self.pos)
        self.temp = np.full(len(pts), 20.)
        self.fuel = np.ones(len(pts))
        self.burning = np.zeros(len(pts), dtype=bool)

    def pairs(self):
        if cKDTree:
            return cKDTree(self.pos).query_pairs(self.h, output_type='ndarray').T
        cells = {}
        for i, cell in enumerate(np.floor(self.pos/self.h).astype(int)):
            cells.setdefault(tuple(cell), []).append(i)
        a, b = [], []
        for (x, y), ids in cells.items():
            for k, i in enumerate(ids):
                a.extend([i]*(len(ids)-k-1)); b.extend(ids[k+1:])
            for dx, dy in ((1, 0), (0, 1), (1, 1), (-1, 1)):
                other = cells.get((x+dx, y+dy), [])
                for i in ids:
                    a.extend([i]*len(other)); b.extend(other)
        if not a:
            return np.empty((2, 0), dtype=int)
        a, b = np.array(a), np.array(b)
        near = np.sum((self.pos[a]-self.pos[b])**2, axis=1) < self.h**2
        return np.array([a[near], b[near]])

    def interact(self, tool, x, y, radius, dx=0, dy=0):
        if tool == 'obstacle':
            if len(self.obstacles) < 30:
                self.obstacles.append([x, y, radius])
            return
        if not len(self.pos):
            return
        distance = np.linalg.norm(self.pos-[x, y], axis=1)
        w = np.maximum(0, 1-distance/radius)
        if tool == 'heat':
            self.temp += w*110
        elif tool == 'cool':
            self.temp = np.maximum(0, self.temp-w*100)
        elif tool == 'stir':
            self.vel += w[:, None]*np.clip([dx, dy], -2, 2)*3
        elif tool == 'erase':
            keep = distance > radius
            for attr in ('pos', 'vel', 'kind', 'temp', 'fuel', 'burning'):
                setattr(self, attr, getattr(self, attr)[keep])

    def advance(self, duration=1/60):
        if self.paused or not len(self.pos):
            return
        self._properties()
        remaining = duration
        while remaining > 1e-9:
            vmax = float(np.max(np.linalg.norm(self.vel, axis=1)))
            nu = float(np.max(self.mu/self.rho0))
            dt = min(remaining, .22*self.h/(self.sound_speed+vmax), .12*self.h**2/max(nu, 1e-8))
            self._step(dt)
            self.time += dt
            remaining -= dt

    def _step(self, dt):
        n = len(self.pos)
        h, volume = self.h, self.spacing**2
        i, j = self.pairs()
        delta = self.pos[i]-self.pos[j]
        r = np.maximum(np.linalg.norm(delta, axis=1), 1e-8)
        q = np.maximum(0, 1-r/h)
        # 2D Wendland C2, normalized over support radius h.
        norm = 7/(math.pi*h*h)
        w = norm*q**4*(1+4*r/h)
        theta = np.full(n, volume*norm)
        theta += np.bincount(i, volume*w, minlength=n)+np.bincount(j, volume*w, minlength=n)
        pressure = self.rho0*self.sound_speed**2/7 * np.maximum(theta**7-1, 0)
        effective_v = volume/np.maximum(theta, .65)
        grad = (-20*norm/h**2*q**3)[:, None]*delta
        force = -(effective_v[i]*effective_v[j]*(pressure[i]+pressure[j]))[:, None]*grad
        # Monaghan artificial viscosity damps approaching acoustic modes. This
        # numerical dissipation is separate from the material's dynamic viscosity.
        approach = np.minimum(np.sum((self.vel[i]-self.vel[j])*delta, axis=1), 0)
        acoustic = -.12*self.sound_speed*h*approach/(r*r+.01*h*h)
        force -= (self.mass[i]*self.mass[j]*acoustic/((self.rho0[i]+self.rho0[j])*.5))[:, None]*grad
        # Symmetric physical viscosity; conservative pair exchange.
        mu = 2*self.mu[i]*self.mu[j]/np.maximum(self.mu[i]+self.mu[j], 1e-12)
        lap = 40*norm/h**2*q**3
        force += (mu*effective_v[i]*effective_v[j]*lap)[:, None]*(self.vel[j]-self.vel[i])
        # Reduced cohesion. Unlike-material cohesion is lower (immiscibility proxy).
        sigma = np.sqrt(self.sigma[i]*self.sigma[j]) * np.where(self.kind[i] == self.kind[j], 1., .2)
        force -= (sigma*volume/h*q**3)[:, None]*delta/r[:, None]
        acc = np.zeros((n, 2))
        for axis in (0, 1):
            f = np.bincount(i, force[:, axis], minlength=n)-np.bincount(j, force[:, axis], minlength=n)
            acc[:, axis] = f/self.mass
        acc[:, 1] -= self.gravity
        self.vel += dt*acc
        self.pos += dt*self.vel
        # Insulated walls mechanically: no penetration, dissipative impact.
        margin = self.spacing*.45
        for axis, upper in ((0, self.width), (1, self.height)):
            low = self.pos[:, axis] < margin
            high = self.pos[:, axis] > upper-margin
            self.pos[:, axis] = np.clip(self.pos[:, axis], margin, upper-margin)
            self.vel[low & (self.vel[:, axis] < 0), axis] *= -.08
            self.vel[high & (self.vel[:, axis] > 0), axis] *= -.08
        for x, y, radius in self.obstacles:
            diff = self.pos-[x, y]
            dist = np.linalg.norm(diff, axis=1)
            inside = dist < radius+margin
            normal = diff/np.maximum(dist[:, None], 1e-9)
            normal[dist < 1e-9] = [0, 1]
            self.pos[inside] = np.array([x, y])+normal[inside]*(radius+margin)
            speed = np.sum(self.vel*normal, axis=1)
            hit = inside & (speed < 0)
            self.vel[hit] -= 1.08*speed[hit, None]*normal[hit]
        # Accelerated effective heat diffusion, equal and opposite energy exchange.
        capacity = self.mass*self.cp
        coupling = .9*q**2 * (capacity[i]*capacity[j]/(capacity[i]+capacity[j]))
        heat = coupling*(self.temp[j]-self.temp[i])*dt
        energy = np.bincount(i, heat, minlength=n)-np.bincount(j, heat, minlength=n)
        self.temp += energy/capacity
        # Burning is restricted to approximately exposed particles (oxygen proxy).
        exposed = theta < .91
        self.burning = (self.flame > 0) & (self.temp >= self.flash) & (self.fuel > 0) & exposed
        consumed = np.minimum(self.fuel, self.burning*self.flame*dt*.22)
        self.fuel -= consumed
        self.temp += consumed*2e6/self.cp
        self.temp += (20-self.temp)*dt*.12
        self.temp = np.clip(self.temp, 0, 1600)

    def snapshot(self):
        return {'particles': np.column_stack((self.pos, self.kind, self.temp, self.burning.astype(int))).round(4).tolist(),
                'time': round(self.time, 3), 'paused': self.paused, 'count': len(self.pos), 'limit': self.limit,
                'obstacles': self.obstacles, 'width': self.width, 'height': self.height, 'spacing': self.spacing,
                'materials': [asdict(m) for m in self.materials],
                'hot': int(np.sum(self.burning)), 'temperature': round(float(np.mean(self.temp)), 1) if len(self.temp) else 20}
