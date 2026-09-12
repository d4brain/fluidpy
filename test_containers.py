import unittest
import numpy as np
from physics import Simulation, RESOLUTIONS
from containers import ASSETS, boundary
from fluid_server import build_commands


class ContainerTests(unittest.TestCase):
    def test_all_vessels_catch_poured_water_at_every_resolution(self):
        for key in ASSETS:
            for resolution in RESOLUTIONS:
                with self.subTest(key=key, resolution=resolution):
                    sim=Simulation();sim.set_resolution(resolution);sim.set_container(key)
                    # Above each opening, not already at the bottom.
                    top={'mug':.53,'glass':.68,'toilet':.48,'bowl':.38,'bucket':.61}[key]+.10
                    sim.emit(.85,top+.10,radius=.045)
                    count=sim.count();self.assertGreater(count,0)
                    for _ in range(100):sim.advance()
                    self.assertEqual(sim.count(),count)
                    self.assertTrue(np.isfinite(sim.pos).all())
                    # No particle escapes to the world floor or tunnels through a wall.
                    self.assertGreater(float(sim.pos[:,1].min()),.15)
                    self.assertTrue((abs(sim.pos[:,0]-.85)<.30).all())
                    for p in sim.container_polygons:
                        self.assertGreaterEqual(float(boundary(sim.pos,p)[0].min()),sim.spacing*.44)

    def test_empty_resolution_reset_and_validation(self):
        sim=Simulation();build_commands({'action':'container','container':'mug'})(sim)
        sim.emit(.85,.4);self.assertGreater(sim.count(),0)
        build_commands({'action':'empty_container'})(sim)
        self.assertEqual(sim.container,'mug');self.assertEqual(sim.count(),0)
        sim.set_resolution('grob');self.assertEqual(sim.container,'mug')
        sim.scene('dam');self.assertIsNone(sim.container)
        for bad in ('missing',None,[],{}):
            with self.assertRaises(ValueError):build_commands({'action':'container','container':bad})

    def test_walls_reject_emission_and_blender_meshes_exist(self):
        for key,asset in ASSETS.items():
            sim=Simulation();sim.set_container(key)
            for y in np.arange(.15,.85,.08):sim.emit(.85,y,radius=.3)
            for p in sim.container_polygons:
                self.assertTrue((boundary(sim.pos,p)[0]>=sim.spacing/2-1e-10).all())
            self.assertGreater(len(asset['vertices']),30)
            self.assertEqual(len(asset['vertices'])%15,0)

if __name__=='__main__':unittest.main()
