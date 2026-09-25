"""Run with:  python -m unittest discover -s tests   (from Samples/Wasteland)"""

import random
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from wasteland import items  # noqa: E402
from wasteland.anomalies import AnomalyField, Emission  # noqa: E402
from wasteland.combat import HitZone, mitigate, vats_hit_chance  # noqa: E402
from wasteland.datatables import export_all  # noqa: E402
from wasteland.economy import Trader  # noqa: E402
from wasteland.factions import Reputation  # noqa: E402
from wasteland.game import GameSession, run_demo  # noqa: E402
from wasteland.hazards import GasMask, Radiation  # noqa: E402
from wasteland.inventory import Inventory  # noqa: E402
from wasteland.special import Progression, Special, xp_for_level  # noqa: E402
from wasteland.survival import Environment, Vitals  # noqa: E402
from wasteland.world import WorldLayout  # noqa: E402


class SurvivalTests(unittest.TestCase):
    def test_hunger_and_thirst_drain(self):
        v = Vitals()
        v.tick(3600, Environment(air_temp_c=20), "walk")
        self.assertLess(v.energy, 80)
        self.assertLess(v.water, 80)

    def test_bleeding_drains_blood_and_bandage_stops_it(self):
        v = Vitals()
        v.take_damage(10, wound=True)
        v.tick(60, Environment(air_temp_c=20), "idle")
        self.assertLess(v.blood, 5000)
        v.treat(items.get("bandage").effects, random.Random(0))
        self.assertEqual(v.bleeding_wounds, 0)

    def test_cold_and_wet_causes_hypothermia(self):
        v = Vitals()
        for _ in range(6 * 60):
            v.tick(60, Environment(air_temp_c=-5, raining=True), "idle")
        self.assertLess(v.body_temp_c, 35.0)
        self.assertIn("freezing", v.status)

    def test_dirty_water_can_cause_cholera(self):
        v = Vitals()
        rng = random.Random(1)
        for _ in range(20):
            v.consume(items.get("pond_water").effects, rng)
        self.assertIn("cholera", v.diseases)


class HazardTests(unittest.TestCase):
    def test_radiation_reduces_max_health(self):
        r = Radiation()
        r.tick(100, rads_per_sec=5, resistance=0)
        self.assertEqual(r.rads, 500)
        self.assertAlmostEqual(r.max_health_cap(100), 50)

    def test_gas_mask_filter_runs_out(self):
        mask = GasMask(equipped=True)
        mask.insert_filter(10)
        dmg, _ = mask.tick(5, toxic=True)
        self.assertEqual(dmg, 0)
        mask.tick(10, toxic=True)
        dmg, _ = mask.tick(1, toxic=True)
        self.assertGreater(dmg, 0)

    def test_cracked_visor_burns_filter_faster(self):
        good, cracked = GasMask(equipped=True), GasMask(equipped=True, integrity=0.2)
        good.insert_filter(100)
        cracked.insert_filter(100)
        good.tick(10, True)
        cracked.tick(10, True)
        self.assertLess(cracked.filter_sec, good.filter_sec)


class AnomalyTests(unittest.TestCase):
    def test_bolt_reveals_anomaly(self):
        fld = AnomalyField.generate("Test", (0, 0), 50, random.Random(3))
        a = fld.anomalies[0]
        hit = fld.throw_bolt((0, 0), (a.x, a.y))
        self.assertIn(a, hit)
        self.assertGreater(a.revealed_sec, 0)

    def test_emission_cycle(self):
        e = Emission(random.Random(0))
        events = []
        for _ in range(80 * 60):
            events += e.tick(60)
        self.assertIn("emission_warning", events)
        self.assertIn("emission_start", events)
        self.assertIn("emission_end", events)


class ProgressionTests(unittest.TestCase):
    def test_point_buy_budget(self):
        with self.assertRaises(ValueError):
            Special.build({n: 10 for n in ("strength", "perception", "endurance")})

    def test_leveling_grants_perk_points(self):
        prog = Progression(Special(intelligence=1))
        prog.add_xp(xp_for_level(3))
        self.assertGreaterEqual(prog.level, 3)
        self.assertGreaterEqual(prog.perk_points, 2)

    def test_armor_curve(self):
        self.assertEqual(mitigate(50, 0), 50)
        self.assertLess(mitigate(10, 100), 3)
        self.assertLess(vats_hit_chance(10, 0.9, 5, HitZone.HEAD),
                        vats_hit_chance(10, 0.9, 5, HitZone.TORSO))


class InventoryEconomyTests(unittest.TestCase):
    def test_backpack_adds_space(self):
        inv = Inventory()
        self.assertFalse(inv.add(items.make("water_bottle")) and
                         inv.add(items.make("water_bottle")) and
                         inv.add(items.make("water_bottle")))
        inv.equip(items.make("hiking_backpack"))
        self.assertTrue(inv.add(items.make("water_bottle")))

    def test_metro_trader_takes_military_rounds(self):
        inv = Inventory()
        inv.equip(items.make("hiking_backpack"))
        inv.add(items.make("ammo_545_mil", 50))
        trader = Trader("Test", "hansa", {"filter": 2})
        self.assertEqual(trader.currency, "ammo_545_mil")
        self.assertTrue(trader.buy_from(inv, "filter", 1.0, Reputation()))
        self.assertEqual(inv.count("filter"), 1)
        self.assertLess(inv.count("ammo_545_mil"), 50)

    def test_reputation_ripples_to_enemies(self):
        rep = Reputation()
        rep.change("duty", 400)
        self.assertLess(rep.values["freedom"], 0)


class WorldAndGameTests(unittest.TestCase):
    def test_world_is_deterministic(self):
        a, b = WorldLayout(5), WorldLayout(5)
        self.assertEqual([(p.name, round(p.x)) for p in a.pois],
                         [(p.name, round(p.x)) for p in b.pois])

    def test_dead_city_air_is_toxic_but_metro_is_not(self):
        s = GameSession(2)
        cx, cy, _ = s.world.dead_city
        self.assertTrue(s.world.environment_at(cx, cy, s.clock, s.weather).toxic_air)
        self.assertFalse(s.world.environment_at(cx, cy, s.clock, s.weather,
                                                underground=True).toxic_air)

    def test_demo_runs(self):
        s = run_demo(2, seed=3, verbose=False)
        self.assertTrue(s.log)
        self.assertIn("health", s.hud())

    def test_export_datatables(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = export_all(Path(tmp))
            self.assertIn("FWastelandItemRow", out["header"].read_text())
            self.assertTrue(out["FWastelandItemRow"].read_text().startswith("Name,"))


if __name__ == "__main__":
    unittest.main()
