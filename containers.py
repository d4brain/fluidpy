"""Collision outlines exported alongside the actual Blender render meshes."""
import json
from pathlib import Path
import numpy as np

ASSETS = json.loads((Path(__file__).parent/'web/assets/vessels.json').read_text(encoding='utf-8'))

def outlines(key):
    return [np.asarray(p, dtype=float)+[.85, .10] for p in ASSETS[key]['polygons']]

def boundary(points, polygon):
    """Signed distance (negative inside), closest point and outward normal."""
    a = polygon
    b = np.roll(a, -1, axis=0)
    edge = b-a
    delta = points[:, None, :]-a
    t = np.clip(np.sum(delta*edge, axis=2)/np.sum(edge*edge, axis=1), 0, 1)
    closest = a+t[:, :, None]*edge
    dsq = np.sum((points[:, None, :]-closest)**2, axis=2)
    ids = np.argmin(dsq, axis=1)
    q = closest[np.arange(len(points)), ids]
    distance = np.sqrt(dsq[np.arange(len(points)), ids])
    x, y = points[:, 0, None], points[:, 1, None]
    cross = ((a[:, 1]>y) != (b[:, 1]>y)) & (x < a[:, 0]+(y-a[:, 1])*edge[:, 0]/np.where(abs(edge[:, 1])>1e-15, edge[:, 1], 1e-15))
    inside = np.logical_xor.reduce(cross, axis=1)
    normal = (points-q)/np.maximum(distance[:, None], 1e-12)
    normal[inside] *= -1
    zero = distance < 1e-10
    area = np.sum(a[:,0]*b[:,1]-b[:,0]*a[:,1])
    fallback = np.column_stack((edge[:,1], -edge[:,0])) * (1 if area>0 else -1)
    fallback /= np.linalg.norm(fallback, axis=1)[:,None]
    normal[zero] = fallback[ids[zero]]
    return np.where(inside, -distance, distance), q, normal

def collide(x, y, vx, vy, polygons, margin, holes=()):
    for polygon in polygons:
        lo, hi = polygon.min(axis=0)-margin, polygon.max(axis=0)+margin
        ids = np.flatnonzero((x>=lo[0]) & (x<=hi[0]) & (y>=lo[1]) & (y<=hi[1]))
        if not len(ids): continue
        distance, q, normal = boundary(np.column_stack((x[ids],y[ids])), polygon)
        hit = distance < margin
        ids, q, normal = ids[hit], q[hit], normal[hit]
        if len(holes) and len(ids):
            # Weggeätzte Stellen halten nichts mehr auf: dort faellt die Wand aus.
            h = np.asarray(holes, dtype=float)
            gone = (np.hypot(q[:,None,0]-h[None,:,0], q[:,None,1]-h[None,:,1]) < h[None,:,2]).any(axis=1)
            ids, q, normal = ids[~gone], q[~gone], normal[~gone]
        if not len(ids): continue
        x[ids], y[ids] = (q+normal*margin).T
        speed = np.minimum(vx[ids]*normal[:,0]+vy[ids]*normal[:,1], 0)
        vx[ids] -= 1.08*speed*normal[:,0]
        vy[ids] -= 1.08*speed*normal[:,1]
