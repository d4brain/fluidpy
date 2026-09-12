import base64
import io
import json
import tempfile
import threading
import time
import unittest
from http.client import HTTPConnection
import numpy as np
from PIL import Image
from physics import Simulation
from sharing import Shares, dump_sim, restore_sim
from fluid_server import create_server

def image(size):
    out=io.BytesIO();Image.new('RGB',size,'#183f58').save(out,format='PNG')
    return base64.b64encode(out.getvalue()).decode()

class SharingTests(unittest.TestCase):
    def test_full_state_roundtrip_including_solid_groups(self):
        sim=Simulation();sim.set_container('mug');sim.emit(.85,.4,7,radius=.07)
        sim.vel[:]=[.2,-.4];sim.fuel[:]=.7;sim.gravity=4.5;sim.advance()
        saved=json.loads(json.dumps(dump_sim(sim)))
        target=Simulation();restore_sim(target,saved)
        self.assertEqual(dump_sim(target),saved)
        self.assertTrue(target.paused)
        target.paused=False;target.advance();self.assertTrue(np.isfinite(target.pos).all())

    def test_capture_persistence_validation_and_immutability(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=Shares(tmp);sim=Simulation();shot=store.capture(dump_sim(sim),b'frame',{})
            data=dict(token=shot['token'],preview=image((1200,630)),post=image((1080,1080)),story=image((1080,1920)))
            sid=store.save(data);self.assertEqual(store.save(data),sid)
            row=Shares(tmp).get(sid);self.assertEqual(row['frame'],b'frame')
            sim.emit(.5,.5);self.assertEqual(json.loads(row['state'])['pos'],[])
            with self.assertRaises(KeyError):store.get('../../secrets')
            bad=store.capture(dump_sim(sim),b'frame',{})
            with self.assertRaises(ValueError):store.save(dict(data,token=bad['token'],preview=image((1,1))))

    def test_http_capture_share_preview_restore(self):
        with tempfile.TemporaryDirectory() as tmp:
            server=create_server(0,data_dir=tmp);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            def request(method,path,data=None,origin=None):
                c=HTTPConnection('127.0.0.1',server.server_port,timeout=20)
                headers={'Content-Type':'application/json'}
                if origin:headers['Origin']=origin
                c.request(method,path,json.dumps(data) if data is not None else None,headers)
                res=c.getresponse();status=res.status;mime=res.getheader('Content-Type');raw=res.read();c.close();return status,mime,raw
            try:
                request('POST','/api/step',dict(action='container',container='mug'))
                status,_,raw=request('POST','/api/capture',{'ui':{'view':'thermal'}});self.assertEqual(status,200)
                shot=json.loads(raw)
                frame=base64.b64decode(shot['frame']);n=int.from_bytes(frame[:4],'little');meta=json.loads(frame[4:4+n]);self.assertEqual(meta['container'],'mug')
                status,_,raw=request('POST','/api/shares',dict(token=shot['token'],preview=image((1200,630)),post=image((1080,1080)),story=image((1080,1920))))
                self.assertEqual(status,200);sid=json.loads(raw)['id']
                status,_,raw=request('GET','/s/'+sid);self.assertEqual(status,200);self.assertIn(b'property="og:image"',raw);self.assertIn(('/s/'+sid+'/preview.png').encode(),raw)
                for name in ('preview','post','story'):
                    status,mime,raw=request('GET',f'/s/{sid}/{name}.png');self.assertEqual((status,mime),(200,'image/png'));self.assertTrue(raw.startswith(b'\x89PNG'))
                request('POST','/api/step',dict(action='scene',scene='empty'))
                status,_,raw=request('POST','/api/capture',{});self.assertEqual(status,200)
                request('GET','/s/'+sid) # Viewing a share must not restore it.
                status,_,raw=request('GET','/api/state');self.assertIsNone(json.loads(raw)['container'])
                self.assertEqual(request('POST','/api/restore',{'id':sid},'https://evil.example')[0],403)
                self.assertEqual(request('POST','/api/restore',{'id':sid})[0],200)
                deadline=time.monotonic()+3
                while time.monotonic()<deadline:
                    status,_,raw=request('GET','/api/state');state=json.loads(raw)
                    if state['container']=='mug':break
                    time.sleep(.02)
                self.assertEqual(state['container'],'mug');self.assertTrue(state['paused'])
            finally:server.shutdown();server.server_close();thread.join()

if __name__=='__main__':unittest.main()
