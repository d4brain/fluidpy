"""Säuren: Ätzlöcher in Gefässen, Durchlass, Hindernisauflösung, Persistenz."""
import unittest
import numpy as np
from physics import Simulation, INDEX, HOLE_MAX, MAX_HOLES
from containers import boundary
from sharing import dump_sim, restore_sim

ACID = INDEX['Schwefelsäure']
HF = INDEX['Flusssäure']
CYANIDE = INDEX['Blausäure']
WATER = INDEX['Wasser']
COFFEE = INDEX['Kaffee']
COLA = INDEX['Cola']


def filled(kind, seconds=0., container='mug'):
    sim = Simulation()
    sim.set_container(container)
    sim.emit(.85, .35, kind, .07, 20)
    for _ in range(int(seconds*120)):
        sim.advance(1/120)
    return sim


class DrinkTests(unittest.TestCase):
    def test_coffee_and_cola_are_selectable_liquids(self):
        sim = Simulation()
        for kind in (COFFEE, COLA):
            material = sim.materials[kind]
            self.assertTrue(material.selectable)
            self.assertEqual(material.render, 'fluid')
            self.assertEqual(material.corrosion, 0.)
            self.assertTrue(material.description)
        self.assertGreater(sim.materials[COLA].density, sim.materials[COFFEE].density)

    def test_cola_flows_and_stays_inside_the_mug(self):
        sim = filled(COLA, 1.2)
        self.assertTrue(len(sim.pos))
        self.assertEqual(sim.holes, [])
        for polygon in sim.container_polygons:
            self.assertTrue((boundary(sim.pos, polygon)[0] > -sim.spacing).all())


class CorrosionTests(unittest.TestCase):
    def test_acid_eats_holes_into_the_vessel(self):
        sim = filled(ACID, 2.)
        self.assertTrue(sim.holes, 'Säure muss die Wand angreifen')
        self.assertTrue(all(h[2] >= 0 for h in sim.holes))

    def test_water_leaves_the_vessel_intact(self):
        self.assertEqual(filled(WATER, 2.).holes, [])

    def test_cyanide_is_a_weak_acid(self):
        strong = len(filled(HF, 1.5).holes)
        weak = filled(CYANIDE, 1.5).holes
        self.assertTrue(strong)
        self.assertTrue(not weak or max(h[2] for h in weak) < .02)

    def test_hot_acid_etches_faster(self):
        cold, hot = Simulation(), Simulation()
        for sim, temperature in ((cold, 20), (hot, 300)):
            sim.set_container('mug')
            sim.emit(.85, .35, ACID, .07, temperature)
            for _ in range(180):
                sim.advance(1/120)
        self.assertGreater(max(h[2] for h in hot.holes), max(h[2] for h in cold.holes))

    def test_a_shallow_pit_does_not_leak_yet(self):
        sim = filled(ACID, .6)
        self.assertTrue(sim.holes, 'die Wand muss schon angeätzt sein')
        self.assertEqual(sim.open_holes(), [], 'flache Mulden gehen noch nicht durch')
        self.assertEqual(sim.meta()['holes_open'], 0)
        for polygon in sim.container_polygons:
            self.assertTrue((boundary(sim.pos, polygon)[0] > -sim.spacing).all())

    def test_pits_open_up_as_they_grow(self):
        sim = filled(HF, 4.)
        self.assertTrue(sim.open_holes())
        self.assertEqual(sim.meta()['holes_open'], len(sim.open_holes()))
        for x, y, r in sim.open_holes():
            self.assertGreater(r, 0)

    def test_holes_stay_bounded(self):
        sim = filled(HF, 6.)
        self.assertLessEqual(len(sim.holes), MAX_HOLES)
        self.assertLessEqual(max(h[2] for h in sim.holes), HOLE_MAX+1e-9)

    def test_fluid_escapes_through_a_hole(self):
        sim = Simulation()
        sim.set_container('mug')
        sim.emit(.85, .35, HF, .07, 200)
        for _ in range(600):
            sim.advance(1/120)
        self.assertTrue(sim.holes)
        floor = min(p[:, 1].min() for p in sim.container_polygons)
        self.assertTrue((sim.pos[:, 1] < floor).any(),
                        'Durch die Löcher muss Flüssigkeit unter das Gefäss laufen')

    def test_acid_dissolves_obstacles(self):
        sim = Simulation()
        sim.interact('obstacle', .9, .5, .08)
        sim.emit(.9, .62, ACID, .06, 20)
        before = sim.obstacles[0][2]
        for _ in range(240):
            sim.advance(1/120)
        self.assertTrue(not sim.obstacles or sim.obstacles[0][2] < before)

    def test_emptying_and_switching_restores_the_wall(self):
        sim = filled(ACID, 2.)
        self.assertTrue(sim.holes)
        sim.empty_container()
        self.assertEqual(sim.holes, [])
        sim.emit(.85, .35, ACID, .07, 20)
        sim.advance(1/120)
        sim.set_container('glass')
        self.assertEqual(sim.holes, [])


class WireTests(unittest.TestCase):
    def test_meta_reports_holes(self):
        sim = filled(ACID, 2.)
        holes = sim.meta()['holes']
        self.assertEqual(len(holes), len(sim.holes))
        self.assertTrue(all(len(h) == 3 for h in holes))

    def test_share_round_trip_keeps_holes(self):
        sim = filled(ACID, 2.)
        restored = Simulation()
        restore_sim(restored, dump_sim(sim))
        np.testing.assert_allclose(np.asarray(restored.holes), np.asarray(sim.holes))

    def test_old_shares_without_holes_still_load(self):
        data = dump_sim(filled(WATER, .5))
        data.pop('holes')
        restored = Simulation()
        restore_sim(restored, data)
        self.assertEqual(restored.holes, [])


if __name__ == '__main__':
    unittest.main(verbosity=2)
