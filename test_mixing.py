"""Emulsion, Zucker, Auflösung in Säure und Dampf."""
import unittest
import numpy as np
from physics import (Simulation, INDEX, STEAM, MILK, SUGAR, FOREVER, FIELDS,
                     STEAM_LIMIT, BOIL_START)
from sharing import dump_sim, restore_sim

COFFEE = INDEX['Kaffee']
WATER = INDEX['Wasser']
CLUMP = INDEX['Kot-Klumpen']
VOMIT = INDEX['Erbrochenes']
ACID = INDEX['Schwefelsäure']


def run(sim, seconds):
    for _ in range(int(seconds*120)):
        sim.advance(1/120)
    return sim


def cup(kind, temperature=20, seconds=.6, container='mug'):
    """Ein Gefäss mit einer Portion Flüssigkeit, kurz zur Ruhe gekommen."""
    sim = Simulation()
    sim.set_container(container)
    sim.emit(.85, .30, kind, .07, temperature)
    return run(sim, seconds)


def puddle(kind, temperature=20, columns=5):
    sim = Simulation()
    for x in np.linspace(.5, 1.3, columns):
        sim.emit(x, .10, kind, .06, temperature)
    return sim


class EmulsionTests(unittest.TestCase):
    def test_milk_and_sugar_start_loaded(self):
        sim = Simulation()
        sim.emit(.9, .5, MILK, .05)
        sim.emit(.4, .5, SUGAR, .05)
        self.assertTrue((sim.milk[sim.kind == MILK] == 1).all())
        self.assertTrue((sim.sugar[sim.kind == SUGAR] == 1).all())
        self.assertTrue((sim.milk[sim.kind == SUGAR] == 0).all())

    def test_milk_lightens_the_coffee(self):
        sim = cup(COFFEE)
        coffee = sim.kind == COFFEE
        self.assertEqual(sim.milk[coffee].max(), 0)
        sim.emit(.85, .45, MILK, .05)
        run(sim, 4.)
        coffee = sim.kind == COFFEE
        self.assertGreater(sim.milk[coffee].mean(), .08,
                           'die Emulsion muss sich im Kaffee verteilen')
        self.assertLess(sim.milk[coffee].max(), 1.001)

    def test_sugar_adds_on_top_of_the_milk(self):
        sim = cup(COFFEE)
        sim.emit(.85, .45, MILK, .05)
        run(sim, 3.)
        before = float(sim.milk[sim.kind == COFFEE].mean())
        sim.emit(.80, .45, SUGAR, .04)
        run(sim, 3.)
        coffee = sim.kind == COFFEE
        self.assertGreater(sim.sugar[coffee].mean(), .03)
        self.assertGreater(sim.milk[coffee].mean(), before*.5,
                           'Zucker darf die Milch nicht verdrängen')

    def test_emulsion_is_conserved_not_invented(self):
        sim = cup(WATER)
        sim.emit(.85, .45, MILK, .05)
        total = float(sim.milk.sum())
        run(sim, 4.)
        self.assertAlmostEqual(float(sim.milk.sum()), total, delta=total*.02)
        self.assertLessEqual(sim.milk.max(), 1.0001)

    def test_payload_carries_milk_and_sugar(self):
        sim = Simulation()
        sim.emit(.9, .5, MILK, .05)
        raw = np.frombuffer(sim.packed(), dtype=np.uint8).reshape(-1, Simulation.STRIDE)
        self.assertEqual(Simulation.STRIDE, 10)
        self.assertTrue((raw[:, 8] == 255).all())
        self.assertTrue((raw[:, 9] == 0).all())


class DissolveTests(unittest.TestCase):
    def test_clumps_dissolve_slowly_in_acid(self):
        sim = run(puddle(ACID), 1.5)
        sim.emit(.9, .40, CLUMP, .05)
        start = int((sim.kind == CLUMP).sum())
        self.assertTrue(start)
        run(sim, 6.)
        middle = int((sim.kind == CLUMP).sum())
        run(sim, 6.)
        end = int((sim.kind == CLUMP).sum())
        self.assertLess(middle, start, 'nach 6 s muss der Angriff begonnen haben')
        self.assertLess(end, middle*.5, 'nach 12 s ist der Klumpen weitgehend weg')

    def test_clumps_survive_plain_water(self):
        sim = run(puddle(WATER), 1.5)
        sim.emit(.9, .40, CLUMP, .05)
        start = int((sim.kind == CLUMP).sum())
        run(sim, 6.)
        self.assertEqual(int((sim.kind == CLUMP).sum()), start)

    def test_vomit_foams_instead_of_dissolving(self):
        sim = run(puddle(ACID), 1.5)
        sim.emit(.9, .40, VOMIT, .05)
        start = int((sim.kind == VOMIT).sum())
        run(sim, 4.)
        self.assertEqual(int((sim.kind == VOMIT).sum()), start,
                         'Erbrochenes selbst löst sich nicht auf')
        self.assertGreater(int((sim.kind == STEAM).sum()), 15,
                           'stattdessen schäumt es kräftig')

    def test_reaction_warms_the_zone(self):
        sim = run(puddle(ACID), 1.5)
        cold = float(sim.temp.mean())
        sim.emit(.9, .40, VOMIT, .05, 20)
        run(sim, 4.)
        liquid = sim.kind != STEAM
        self.assertGreater(float(sim.temp[liquid].mean()), cold+2)


class SteamTests(unittest.TestCase):
    def test_hot_liquid_steams_and_cold_does_not(self):
        self.assertGreater(int((run(cup(WATER, 98), 1.5).kind == STEAM).sum()), 3)
        self.assertEqual(int((run(cup(WATER, 20), 1.5).kind == STEAM).sum()), 0)

    def test_steam_rises(self):
        sim = run(cup(WATER, 98), 1.5)
        steam = sim.kind == STEAM
        self.assertTrue(steam.any())
        self.assertGreater(float(sim.vel[steam, 1].mean()), 0)

    def test_steam_fades_away(self):
        sim = run(cup(WATER, 98), 1.5)
        self.assertTrue(int((sim.kind == STEAM).sum()))
        sim.temp[:] = 20.
        run(sim, 5.)
        self.assertEqual(int((sim.kind == STEAM).sum()), 0)

    def test_steam_stays_within_its_budget(self):
        sim = run(puddle(WATER, 600, columns=7), 5.)
        self.assertLessEqual(int((sim.kind == STEAM).sum()), STEAM_LIMIT)
        self.assertLessEqual(len(sim.pos), sim.limit)

    def test_breached_vessel_steams(self):
        sim = cup(INDEX['Flusssäure'], 20, seconds=6.)
        self.assertTrue(sim.open_holes())
        self.assertTrue(int((sim.kind == STEAM).sum()))

    def test_boil_threshold_is_below_boiling(self):
        self.assertGreater(BOIL_START, 20)
        self.assertLess(BOIL_START, 100)


class StateTests(unittest.TestCase):
    def test_all_fields_stay_the_same_length(self):
        sim = run(cup(WATER, 98), 1.5)
        sim.emit(.85, .45, MILK, .04)
        sim.interact('erase', .85, .30, .06)
        run(sim, 1.)
        for field in FIELDS:
            self.assertEqual(len(getattr(sim, field)), len(sim.pos), field)

    def test_share_round_trip_keeps_mixture_and_steam(self):
        sim = cup(COFFEE, 90)
        sim.emit(.85, .45, MILK, .04)
        run(sim, 2.)
        restored = Simulation()
        restore_sim(restored, dump_sim(sim))
        for field in ('milk', 'sugar', 'life'):
            np.testing.assert_allclose(getattr(restored, field), getattr(sim, field))
        np.testing.assert_array_equal(restored.kind, sim.kind)

    def test_old_shares_gain_neutral_defaults(self):
        data = dump_sim(cup(WATER, 20, seconds=.3))
        for field in ('milk', 'sugar', 'life'):
            data.pop(field)
        restored = Simulation()
        restore_sim(restored, data)
        self.assertEqual(len(restored.milk), len(restored.pos))
        self.assertEqual(restored.milk.max(initial=0), 0)
        self.assertTrue((restored.life == FOREVER).all())


if __name__ == '__main__':
    unittest.main(verbosity=2)
