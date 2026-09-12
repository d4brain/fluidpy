"""Immutable SQLite shares; captures are made by the server, never client state."""
import base64
from contextlib import contextmanager
from dataclasses import asdict
import html
import io
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import threading
import time
import numpy as np
from PIL import Image
from physics import Material, RESOLUTIONS, FIELDS, FOREVER
from containers import outlines

ID = re.compile(r'^[A-Za-z0-9_-]{22}$')

def dump_sim(sim):
    return dict(schema=1, resolution=sim.resolution, container=sim.container,
                gravity=sim.gravity, time=sim.time, last_scene=sim.last_scene,
                materials=[asdict(m) for m in sim.materials], obstacles=sim.obstacles,
                letter_index=sim.letter_index, rng=sim.rng.bit_generator.state,
                holes=[list(map(float,h)) for h in sim.holes],
                groups=[[ids.tolist(),rest.tolist()] for ids,rest in sim.groups],
                **{k:getattr(sim,k).tolist() for k in FIELDS})

def restore_sim(sim, data):
    # Only stored, server-generated snapshots reach this function.
    sim.clear();sim.resolution=data['resolution'];sim.spacing=RESOLUTIONS[sim.resolution];sim.h=sim.spacing*2.5
    sim.container=data['container'];sim.container_polygons=outlines(sim.container) if sim.container else []
    for k in ('gravity','time','last_scene','obstacles','letter_index'):setattr(sim,k,data[k])
    sim.holes=[list(map(float,h)) for h in data.get('holes',())]
    sim.materials=[Material(**m) for m in data['materials']]
    for k in FIELDS:
        if k not in data:
            continue                      # ältere Aufnahmen kennen milk/sugar/life nicht
        v=np.asarray(data[k],dtype=int if k=='kind' else bool if k=='burning' else float)
        setattr(sim,k,v.reshape(-1,2) if k in ('pos','vel') else v)
    for k,fill in (('milk',0.),('sugar',0.),('life',FOREVER)):
        if len(getattr(sim,k))!=len(sim.pos):setattr(sim,k,np.full(len(sim.pos),fill))
    sim.groups=[(np.asarray(ids,dtype=int),np.asarray(rest,dtype=float)) for ids,rest in data['groups']]
    sim.rng.bit_generator.state=data['rng'];sim.paused=True

def png(value, expected):
    if not isinstance(value,str) or len(value)>4_000_000:raise ValueError('Bild zu groß')
    raw=base64.b64decode(value,validate=True)
    with Image.open(io.BytesIO(raw)) as im:
        if im.format!='PNG' or im.size!=expected:raise ValueError('Ungültiges Bildformat')
        im.load();out=io.BytesIO();im.convert('RGB').save(out,format='PNG')
    return out.getvalue()

class Shares:
    def __init__(self, path=None):
        self.path=Path(path or os.environ.get('FLUIDPY_DATA_DIR',Path(__file__).parent/'data'))/'shares.sqlite3'
        self.lock=threading.Lock();self.pending={}

    @contextmanager
    def db(self):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        con=sqlite3.connect(self.path,timeout=20)
        try:
            with con:
                con.execute('CREATE TABLE IF NOT EXISTS shares (id TEXT PRIMARY KEY, created REAL, state TEXT, frame BLOB, ui TEXT, preview BLOB, post BLOB, story BLOB)')
                yield con
        finally:con.close()

    def capture(self, state, frame, ui):
        with self.lock:
            now=time.monotonic();self.pending={k:v for k,v in self.pending.items() if now-v[0]<180}
            if len(self.pending)>=16:raise ValueError('Zu viele Aufnahmen. Bitte kurz warten.')
            token=secrets.token_urlsafe(16);sid=secrets.token_urlsafe(16)
            self.pending[token]=(now,sid,json.dumps(state,allow_nan=False),frame,json.dumps(ui))
        return dict(token=token,id=sid,frame=base64.b64encode(frame).decode(),ui=ui)

    def save(self, data):
        token=data.get('token')
        if not isinstance(token,str):raise ValueError('Aufnahme fehlt')
        with self.lock:
            item=self.pending.get(token)
            if not item or time.monotonic()-item[0]>180:raise ValueError('Aufnahme abgelaufen. Erneut speichern.')
        preview=png(data.get('preview'),(1200,630));post=png(data.get('post'),(1080,1080));story=png(data.get('story'),(1080,1920))
        with self.lock:
            with self.db() as con:
                if con.execute('SELECT 1 FROM shares WHERE id=?',(item[1],)).fetchone():return item[1]
                count,total=con.execute('SELECT count(*),coalesce(sum(length(state)+length(frame)+length(preview)+length(post)+length(story)),0) FROM shares').fetchone()
                if count>=int(os.environ.get('FLUIDPY_MAX_SHARES','1000')) or total+len(preview)+len(post)+len(story)+len(item[2])+len(item[3])>1_000_000_000:
                    raise ValueError('Speicher für Freigaben voll. Betreiber kontaktieren.')
                con.execute('INSERT INTO shares VALUES (?,?,?,?,?,?,?,?)',(item[1],time.time(),item[2],item[3],item[4],preview,post,story))
        return item[1]

    def get(self,sid):
        if not ID.fullmatch(sid):raise KeyError('Freigabe nicht gefunden')
        with self.db() as con:
            con.row_factory=sqlite3.Row
            row=con.execute('SELECT * FROM shares WHERE id=?',(sid,)).fetchone()
        if row is None:raise KeyError('Freigabe nicht gefunden')
        return row

def social_html(source,base,sid):
    url=html.escape(base+'/s/'+sid,quote=True)
    image=html.escape(base+'/s/'+sid+'/preview.png',quote=True)
    tags=f'''<meta property="og:type" content="website"><meta property="og:title" content="Meine FluidPy-Kreation">
<meta property="og:description" content="Gefäße, Flüssigkeiten und Experimente – öffne diesen gespeicherten Moment im Fluidlabor.">
<meta property="og:url" content="{url}"><meta property="og:image" content="{image}">
<meta property="og:image:width" content="1200"><meta property="og:image:height" content="630">
<meta name="twitter:card" content="summary_large_image"><meta name="twitter:image" content="{image}">'''
    return source.replace('<title>FluidPy · Fluidlabor</title>','<title>Gespeicherte Kreation · FluidPy</title>').replace('</head>',tags+'</head>')
