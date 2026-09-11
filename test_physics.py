import unittest
import numpy as np
from physics import Simulation


class PhysicsTests(unittest.TestCase):
    def pair(self):
        s = Simulation()
        s.pos = np.array([[.85, .5], [.875, .5]])
        s.vel = np.array([[.3, .1], [-.2, -.1]])
        s.kind = np.array([0, 1])
        s.temp = np.full(2, 20.)
        s.fuel = np.ones(2)
        s.burning = np.zeros(2, dtype=bool)
        s.gravity = 0
        s._properties()
        return s

    def test_pair_momentum_conserved_with_unequal_masses(self):
        s = self.pair()
        before = (s.mass[:, None]*s.vel).sum(axis=0)
        s.advance(.01)
        np.testing.assert_allclose((s.mass[:, None]*s.vel).sum(axis=0), before, atol=1e-12)

    def test_gravity_independent_of_density(self):
        s = self.pair()
        s.pos[1, 0] += .3
        s.vel[:] = 0
        s.gravity = 9.81
        s.advance(.02)
        np.testing.assert_allclose(s.vel[:, 1], [-.1962, -.1962], atol=1e-10)

    def test_dam_remains_finite_and_inside_walls(self):
        s = Simulation()
        s.scene('dam')
        mass_before = len(s.pos)
        for _ in range(80):
            s.advance()
        self.assertEqual(len(s.pos), mass_before)
        self.assertTrue(np.isfinite(s.pos).all() and np.isfinite(s.vel).all())
        self.assertTrue((s.pos >= 0).all())
        self.assertTrue((s.pos[:, 0] <= s.width).all())
        self.assertTrue((s.pos[:, 1] <= s.height).all())

    def test_hot_water_does_not_burn_but_oil_consumes_fuel(self):
        s = self.pair()
        s.pos[1, 0] += .3
        s.temp[:] = 700
        s.advance(.02)
        self.assertFalse(s.burning[0])
        self.assertTrue(s.burning[1])
        self.assertEqual(s.fuel[0], 1)
        self.assertLess(s.fuel[1], 1)
        s.temp[:] = 20
        s.advance(.01)
        self.assertFalse(s.burning.any())

    def test_pause_and_overlap_prevention(self):
        s = Simulation()
        self.assertGreater(s.emit(.5, .5), 0)
        self.assertEqual(s.emit(.5, .5), 0)
        before = s.pos.copy()
        s.paused = True
        s.advance()
        np.testing.assert_array_equal(s.pos, before)

    def test_obstacle_and_erasing(self):
        s = Simulation()
        s.emit(.5, .5)
        s.interact('obstacle', .5, .5, .1)
        s.advance(.005)
        self.assertTrue((np.linalg.norm(s.pos-[.5, .5], axis=1) >= .1).all())
        s.interact('erase', .5, .5, .3)
        self.assertEqual(len(s.pos), 0)


if __name__ == '__main__':
    unittest.main(verbosity=2)
