import unittest
import numpy as np
from physics import Simulation, PRESETS, SCENES
from fluid_server import build_commands


class InclusionTests(unittest.TestCase):
    def test_new_scenes_all_resolutions(self):
        for resolution in ('fein', 'mittel', 'grob'):
            for name, kind in [('diarrhea', 4), ('clumps', 5), ('vomit', 6), ('soup', 7)]:
                with self.subTest(resolution=resolution, scene=name):
                    s = Simulation()
                    s.set_resolution(resolution)
                    build_commands({'action': 'scene', 'scene': name})(s)
                    self.assertIn(kind, s.kind)
                    if kind in (5, 6, 7):
                        self.assertTrue(s.groups)
                    if kind in (6, 7):
                        self.assertIn(kind+2, s.kind)
                    count = s.count()
                    for _ in range(4):
                        s.advance(.01)
                    self.assertEqual(s.count(), count)
                    self.assertTrue(np.isfinite(s.pos).all())
                    self.assertTrue(np.isfinite(s.vel).all())
                    self.assertTrue((s.pos >= 0).all())
                    self.assertTrue((s.pos <= [s.width, s.height]).all())
                    self.assertEqual(len(s.packed()), count*Simulation.STRIDE)
                    s.set_resolution('mittel')
                    self.assertEqual(s.last_scene, name)

    def test_shape_survives_fall_and_stir(self):
        for kind in (5, 6, 7):
            s = Simulation()
            s.emit(.9, .8, kind)
            ids, rest = s.groups[0]
            distances = np.linalg.norm(rest[:, None]-rest[None, :], axis=2)
            initial_y = s.pos[ids, 1].mean()
            s.interact('stir', .87, .8, .1, dx=.05, dy=.01)
            for _ in range(30):
                s.advance(.01)
            actual = np.linalg.norm(s.pos[ids, None]-s.pos[ids][None, :], axis=2)
            np.testing.assert_allclose(actual, distances, atol=1e-8)
            self.assertLess(s.pos[ids, 1].mean(), initial_y)

    def test_erase_remaps_groups_clear_and_limit(self):
        s = Simulation()
        s.emit(.4, .7, 7)
        s.emit(.9, .7, 7)
        s.interact('erase', .4, .7, .2)
        self.assertEqual(len(s.groups), 1)
        ids, _ = s.groups[0]
        self.assertTrue((s.kind[ids] == 9).all())
        s.interact('erase', *s.pos[ids[0]], .008)
        s.advance(.01)
        self.assertTrue(np.isfinite(s.pos).all())
        s.clear()
        self.assertFalse(s.groups)
        s.limit = 3
        s.emit(.5, .5, 7)
        self.assertLessEqual(s.count(), 3)
        self.assertFalse(s.groups)

    def test_letters_not_clipped_and_obstacles_respected(self):
        s = Simulation()
        s.emit(.01, .01, 7)
        self.assertFalse(s.groups)
        s.clear()
        s.interact('obstacle', .5, .5, .07)
        s.emit(.5, .5, 7)
        self.assertFalse(s.groups)
        s.emit(.8, .8, 5)
        for _ in range(60):
            s.advance(.01)
        self.assertTrue(np.isfinite(s.pos).all())
        self.assertTrue((np.linalg.norm(s.pos-[.5,.5], axis=1) >= .07).all())

    def test_selection_and_custom_material(self):
        s = Simulation()
        hidden = [m.name for m in PRESETS if not m.selectable]
        self.assertEqual(hidden, ['Speisestückchen', 'Buchstabennudeln', 'Dampf'])
        self.assertEqual(sum(m.selectable for m in PRESETS), len(PRESETS)-3)
        build_commands({'action':'material'})(s)
        self.assertEqual(s.materials[-1].name, 'Eigenes 1')
        s.emit(.5, .5, len(s.materials)-1)
        s.advance(.01)
        self.assertFalse(s.groups)


if __name__ == '__main__':
    unittest.main()
